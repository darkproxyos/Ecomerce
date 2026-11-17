from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .. import clock
from ..config import ALLOWED_IMAGE_TYPES, MAX_UPLOAD_MB
from ..database import get_db
from ..models import Listing, Product, ProductImage, Sale, SaleItem
from ..schemas import (
    ImageOut, ListingIn, ListingOut, ProductIn, ProductOut, QuickSaleIn, SaleIn, SaleItemIn, SaleOut,
)
from ..services import mercadolibre as ml
from ..services import settings as cfg

router = APIRouter(prefix="/api", tags=["productos"])


def image_url(img: ProductImage) -> str:
    # El número de versión evita que el navegador muestre una foto vieja en caché.
    return f"/api/images/{img.id}?v={img.size}"


def images_out(images: list[ProductImage]) -> list[ImageOut]:
    return [ImageOut(id=i.id, filename=i.filename, position=i.position, url=image_url(i)) for i in images]


def aging_cfg(db: Session) -> tuple[int, int]:
    return int(cfg.get_float(db, "aging_warn_days", 14)), int(cfg.get_float(db, "aging_clear_days", 30))


def product_out(p: Product, units_sold: int = 0, aging: tuple[int, int] = (14, 30)) -> ProductOut:
    out = ProductOut.model_validate(p)
    out.images = images_out(p.images)
    out.margin = round(p.price - p.cost, 2)
    out.margin_pct = round((p.price - p.cost) / p.price * 100, 1) if p.price else 0
    out.low_stock = p.stock <= p.min_stock
    out.units_sold = units_sold
    # Rotación: solo cuenta para lo que está a la venta y con existencias.
    if p.status == "activo" and p.stock > 0:
        since = p.listed_at or p.created_at
        out.days_listed = max(0, (clock.now() - since).days)
        warn, clear = aging
        if out.days_listed >= clear:
            out.aging = "liquidar"
            out.suggested_price = round(max(p.cost, p.price * 0.8))
        elif out.days_listed >= warn:
            out.aging = "bajar"
            out.suggested_price = round(max(p.cost, p.price * 0.9))
    return out


def _units_sold(db: Session) -> dict[int, int]:
    rows = (
        db.query(SaleItem.product_id, func.sum(SaleItem.quantity))
        .join(Sale).filter(Sale.status != "cancelado", SaleItem.product_id.isnot(None))
        .group_by(SaleItem.product_id).all()
    )
    return {pid: int(n) for pid, n in rows}


def _get(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(404, "Producto no encontrado")
    return p


@router.get("/products", response_model=list[ProductOut])
def list_products(q: str = "", category: str = "", status: str = "", low_stock: bool = False,
                  aging: str = "", db: Session = Depends(get_db)):
    query = db.query(Product).options(selectinload(Product.images), selectinload(Product.listings))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like),
                                 Product.brand.ilike(like), Product.description.ilike(like)))
    if category:
        query = query.filter(Product.category == category)
    if status:
        query = query.filter(Product.status == status)
    if low_stock:
        query = query.filter(Product.stock <= Product.min_stock)
    sold, ag = _units_sold(db), aging_cfg(db)
    out = [product_out(p, sold.get(p.id, 0), ag) for p in query.order_by(Product.updated_at.desc()).all()]
    if aging == "any":
        out = [p for p in out if p.aging]
    elif aging:
        out = [p for p in out if p.aging == aging]
    return out


@router.get("/categories", response_model=list[str])
def categories(db: Session = Depends(get_db)):
    rows = db.query(Product.category).filter(Product.category != "").distinct().all()
    return sorted(r[0] for r in rows)


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    return product_out(_get(db, product_id), _units_sold(db).get(product_id, 0), aging_cfg(db))


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Ya existe un producto con ese SKU") from exc


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(data: ProductIn, db: Session = Depends(get_db)):
    p = Product(**data.model_dump())
    if p.status == "activo":
        p.listed_at = clock.now()
    db.add(p)
    _commit(db)
    db.refresh(p)
    return product_out(p, 0, aging_cfg(db))


@router.put("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, data: ProductIn, db: Session = Depends(get_db)):
    p = _get(db, product_id)
    was_active = p.status == "activo"
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    if p.status == "activo" and (not was_active or p.listed_at is None):
        p.listed_at = clock.now()  # se vuelve a publicar: los días empiezan de nuevo
    _commit(db)
    db.refresh(p)
    return product_out(p, _units_sold(db).get(p.id, 0), aging_cfg(db))


@router.post("/products/{product_id}/relist", response_model=ProductOut)
def relist_product(product_id: int, db: Session = Depends(get_db)):
    """Marca el artículo como recién publicado (después de renovar o republicar el anuncio)."""
    p = _get(db, product_id)
    p.listed_at = clock.now()
    if p.status in ("pausado", "borrador"):
        p.status = "activo"
    db.commit()
    db.refresh(p)
    return product_out(p, _units_sold(db).get(p.id, 0), aging_cfg(db))


@router.post("/products/{product_id}/quick-sale", response_model=SaleOut, status_code=201)
def quick_sale(product_id: int, data: QuickSaleIn, db: Session = Depends(get_db)):
    """'Vendido' en un toque: crea la venta, descuenta stock y marca agotado si ya no queda."""
    from .sales import create_sale  # import local para evitar ciclo

    p = _get(db, product_id)
    if p.stock < data.quantity:
        raise HTTPException(409, f"Solo hay {p.stock} en stock de \"{p.name}\"")
    sale = create_sale(SaleIn(
        channel=data.channel, status=data.status, customer_name=data.customer_name,
        shipping_cost=data.shipping_cost, commission=data.commission,
        items=[SaleItemIn(product_id=p.id, quantity=data.quantity, unit_price=data.price)],
    ), db)
    db.refresh(p)
    if p.stock <= 0 and p.status == "activo":
        p.status = "agotado"
        db.commit()
    return sale


@router.post("/products/{product_id}/duplicate", response_model=ProductOut, status_code=201)
def duplicate_product(product_id: int, db: Session = Depends(get_db)):
    src = _get(db, product_id)
    data = ProductIn.model_validate(src, from_attributes=True).model_dump()
    data.update(sku=None, name=f"{src.name} (copia)", status="borrador", stock=0)
    p = Product(**data)
    db.add(p)
    db.commit()
    db.refresh(p)
    return product_out(p, 0, aging_cfg(db))


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, product_id))
    db.commit()


# ------------------------------------------------------------------ fotos

@router.post("/products/{product_id}/images", response_model=list[ImageOut])
async def upload_images(product_id: int, files: list[UploadFile] = File(...),
                        db: Session = Depends(get_db)):
    p = _get(db, product_id)
    pos = max((i.position for i in p.images), default=-1) + 1
    for f in files:
        ctype = (f.content_type or "").lower()
        if ctype == "image/jpg":
            ctype = "image/jpeg"
        if ctype not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(400, f"Formato no permitido: {f.filename} (usa JPG, PNG, WEBP o GIF)")
        content = await f.read()
        if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(400, f"{f.filename} supera {MAX_UPLOAD_MB} MB")
        p.images.append(ProductImage(filename=(f.filename or "")[:255], content_type=ctype,
                                     size=len(content), data=content, position=pos))
        pos += 1
    db.commit()
    db.refresh(p)
    return images_out(p.images)


@router.get("/images/{image_id}", include_in_schema=False)
def get_image(image_id: int, db: Session = Depends(get_db)):
    """Sirve la foto. Es pública para que Facebook/Meta pueda leerla desde el catálogo."""
    img = db.get(ProductImage, image_id)
    if img is None or img.data is None:
        raise HTTPException(404, "Imagen no encontrada")
    return Response(img.data, media_type=img.content_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.delete("/images/{image_id}", status_code=204)
def delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(ProductImage, image_id)
    if img is None:
        raise HTTPException(404, "Imagen no encontrada")
    db.delete(img)
    db.commit()


@router.post("/images/{image_id}/cover", status_code=204)
def set_cover(image_id: int, db: Session = Depends(get_db)):
    """Pone la imagen como portada (posición 0)."""
    img = db.get(ProductImage, image_id)
    if img is None:
        raise HTTPException(404, "Imagen no encontrada")
    ordered = [img] + [i for i in img.product.images if i.id != img.id]
    for idx, i in enumerate(ordered):
        i.position = idx
    db.commit()


# ------------------------------------------------------------------ publicaciones

@router.get("/listings", response_model=list[ListingOut])
def list_listings(channel: str = "", db: Session = Depends(get_db)):
    q = db.query(Listing)
    if channel:
        q = q.filter(Listing.channel == channel)
    return q.order_by(Listing.created_at.desc()).all()


@router.post("/listings", response_model=ListingOut, status_code=201)
def create_listing(data: ListingIn, db: Session = Depends(get_db)):
    if data.product_id is not None:
        _get(db, data.product_id)
    listing = Listing(**data.model_dump())
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


@router.put("/listings/{listing_id}", response_model=ListingOut)
def update_listing(listing_id: int, data: ListingIn, db: Session = Depends(get_db)):
    listing = db.get(Listing, listing_id)
    if listing is None:
        raise HTTPException(404, "Publicación no encontrada")
    for k, v in data.model_dump().items():
        setattr(listing, k, v)
    db.commit()
    db.refresh(listing)
    return listing


@router.delete("/listings/{listing_id}", status_code=204)
def delete_listing(listing_id: int, db: Session = Depends(get_db)):
    listing = db.get(Listing, listing_id)
    if listing is None:
        raise HTTPException(404, "Publicación no encontrada")
    db.delete(listing)
    db.commit()


@router.post("/listings/{listing_id}/push")
def push_listing(listing_id: int, db: Session = Depends(get_db)):
    """Actualiza precio y stock de la publicación en Mercado Libre."""
    listing = db.get(Listing, listing_id)
    if listing is None:
        raise HTTPException(404, "Publicación no encontrada")
    if listing.channel != "mercadolibre" or not listing.external_id:
        raise HTTPException(400, "Solo publicaciones de Mercado Libre con ID (ej. MLM123456)")
    try:
        ml.push_listing(db, listing)
    except ml.MLError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}
