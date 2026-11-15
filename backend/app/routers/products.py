import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import ALLOWED_IMAGE_EXT, MAX_UPLOAD_MB, UPLOAD_DIR
from ..database import get_db
from ..models import Listing, Product, ProductImage, Sale, SaleItem
from ..schemas import ImageOut, ListingIn, ListingOut, ProductIn, ProductOut
from ..services import mercadolibre as ml

router = APIRouter(prefix="/api", tags=["productos"])


def image_url(filename: str) -> str:
    return f"/uploads/{filename}"


def product_out(p: Product, units_sold: int = 0) -> ProductOut:
    out = ProductOut.model_validate(p)
    out.images = [ImageOut(id=i.id, filename=i.filename, position=i.position, url=image_url(i.filename))
                  for i in p.images]
    out.margin = round(p.price - p.cost, 2)
    out.margin_pct = round((p.price - p.cost) / p.price * 100, 1) if p.price else 0
    out.low_stock = p.stock <= p.min_stock
    out.units_sold = units_sold
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
                  db: Session = Depends(get_db)):
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
    sold = _units_sold(db)
    return [product_out(p, sold.get(p.id, 0)) for p in query.order_by(Product.updated_at.desc()).all()]


@router.get("/categories", response_model=list[str])
def categories(db: Session = Depends(get_db)):
    rows = db.query(Product.category).filter(Product.category != "").distinct().all()
    return sorted(r[0] for r in rows)


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    return product_out(_get(db, product_id), _units_sold(db).get(product_id, 0))


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Ya existe un producto con ese SKU") from exc


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(data: ProductIn, db: Session = Depends(get_db)):
    p = Product(**data.model_dump())
    db.add(p)
    _commit(db)
    db.refresh(p)
    return product_out(p)


@router.put("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, data: ProductIn, db: Session = Depends(get_db)):
    p = _get(db, product_id)
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    _commit(db)
    db.refresh(p)
    return product_out(p, _units_sold(db).get(p.id, 0))


@router.post("/products/{product_id}/duplicate", response_model=ProductOut, status_code=201)
def duplicate_product(product_id: int, db: Session = Depends(get_db)):
    src = _get(db, product_id)
    data = ProductIn.model_validate(src, from_attributes=True).model_dump()
    data.update(sku=None, name=f"{src.name} (copia)", status="borrador", stock=0)
    p = Product(**data)
    db.add(p)
    db.commit()
    db.refresh(p)
    return product_out(p)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    p = _get(db, product_id)
    files = [i.filename for i in p.images]
    db.delete(p)
    db.commit()
    for f in files:
        (UPLOAD_DIR / f).unlink(missing_ok=True)


# ------------------------------------------------------------------ fotos

@router.post("/products/{product_id}/images", response_model=list[ImageOut])
async def upload_images(product_id: int, files: list[UploadFile] = File(...),
                        db: Session = Depends(get_db)):
    p = _get(db, product_id)
    pos = max((i.position for i in p.images), default=-1) + 1
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_IMAGE_EXT:
            raise HTTPException(400, f"Formato no permitido: {f.filename} (usa JPG, PNG, WEBP o GIF)")
        content = await f.read()
        if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(400, f"{f.filename} supera {MAX_UPLOAD_MB} MB")
        name = f"{uuid.uuid4().hex}{ext}"
        (UPLOAD_DIR / name).write_bytes(content)
        p.images.append(ProductImage(filename=name, position=pos))
        pos += 1
    db.commit()
    db.refresh(p)
    return [ImageOut(id=i.id, filename=i.filename, position=i.position, url=image_url(i.filename))
            for i in p.images]


@router.delete("/images/{image_id}", status_code=204)
def delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(ProductImage, image_id)
    if img is None:
        raise HTTPException(404, "Imagen no encontrada")
    filename = img.filename
    db.delete(img)
    db.commit()
    (UPLOAD_DIR / filename).unlink(missing_ok=True)


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
