"""Configuración, conexión con Mercado Libre y exportaciones CSV."""
import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Customer, Expense, Product, Sale
from ..services import mercadolibre as ml
from ..services import settings as cfg

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return cfg.public_view(db)


@router.put("/settings")
def put_settings(values: dict[str, str], db: Session = Depends(get_db)):
    cfg.set_many(db, values)
    return cfg.public_view(db)


# ------------------------------------------------------------------ Mercado Libre

@router.get("/ml/status")
def ml_status(db: Session = Depends(get_db)):
    s = cfg.get_all(db)
    return {
        "configured": bool(s["ml_app_id"] and s["ml_client_secret"] and s["ml_redirect_uri"]),
        "connected": bool(s["ml_access_token"]),
        "nickname": s["ml_nickname"],
        "user_id": s["ml_user_id"],
        "token_expires": s["ml_token_expires"],
    }


@router.get("/ml/auth-url")
def ml_auth_url(db: Session = Depends(get_db)):
    try:
        return {"url": ml.auth_url(db)}
    except ml.MLError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/ml/callback", response_class=HTMLResponse)
def ml_callback(code: str = "", error: str = "", db: Session = Depends(get_db)):
    """Redirect URI de la app de Mercado Libre: https://TU-DOMINIO/api/ml/callback"""
    if error or not code:
        return HTMLResponse(f"<p>Mercado Libre devolvió un error: {error or 'sin código'}</p>"
                            '<p><a href="/#/configuracion">Volver</a></p>', status_code=400)
    try:
        ml.exchange_code(db, code)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f"<p>No se pudo conectar: {exc}</p>"
                            '<p><a href="/#/configuracion">Volver</a></p>', status_code=400)
    return HTMLResponse('<script>location.href="/#/configuracion?ml=ok"</script>Conectado.')


@router.post("/ml/disconnect")
def ml_disconnect(db: Session = Depends(get_db)):
    cfg.set_many(db, {k: "" for k in ("ml_access_token", "ml_refresh_token", "ml_token_expires",
                                      "ml_user_id", "ml_nickname")})
    return {"ok": True}


@router.post("/ml/sync-orders")
def ml_sync_orders(days: int = 30, db: Session = Depends(get_db)):
    try:
        return ml.sync_orders(db, days)
    except ml.MLError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/ml/sync-listings")
def ml_sync_listings(db: Session = Depends(get_db)):
    try:
        return ml.sync_listings(db)
    except ml.MLError as exc:
        raise HTTPException(502, str(exc)) from exc


# ------------------------------------------------------------------ exportaciones

def _csv(filename: str, header: list[str], rows) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("﻿")  # BOM para que Excel abra bien los acentos
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/products.csv")
def export_products(db: Session = Depends(get_db)):
    rows = [[p.id, p.sku or "", p.name, p.category, p.brand, p.condition, p.cost, p.price,
             p.stock, p.min_stock, p.status, p.supplier, p.description]
            for p in db.query(Product).order_by(Product.name)]
    return _csv("productos.csv", ["id", "sku", "nombre", "categoria", "marca", "condicion", "costo",
                                  "precio", "stock", "stock_minimo", "estado", "proveedor",
                                  "descripcion"], rows)


@router.get("/export/sales.csv")
def export_sales(date_from: date | None = None, date_to: date | None = None,
                 db: Session = Depends(get_db)):
    q = db.query(Sale).options(selectinload(Sale.items), selectinload(Sale.customer))
    if date_from:
        q = q.filter(Sale.date >= date_from)
    if date_to:
        q = q.filter(Sale.date <= date_to)
    rows = []
    for s in q.order_by(Sale.date):
        for i in s.items:
            rows.append([s.id, s.date.isoformat(), s.channel, s.status,
                         s.customer.name if s.customer else "", s.external_id or "",
                         i.description, i.quantity, i.unit_price, i.unit_cost,
                         s.commission, s.shipping_cost, s.total, s.profit])
    return _csv("ventas.csv", ["venta", "fecha", "canal", "estado", "cliente", "id_externo",
                               "articulo", "cantidad", "precio_unit", "costo_unit", "comision",
                               "envio", "total_venta", "utilidad_venta"], rows)


@router.get("/export/customers.csv")
def export_customers(db: Session = Depends(get_db)):
    rows = [[c.id, c.name, c.phone, c.email, c.city, c.channel, c.notes]
            for c in db.query(Customer).order_by(Customer.name)]
    return _csv("clientes.csv", ["id", "nombre", "telefono", "email", "ciudad", "canal", "notas"], rows)


@router.get("/export/expenses.csv")
def export_expenses(db: Session = Depends(get_db)):
    rows = [[e.id, e.date.isoformat(), e.category, e.description, e.amount]
            for e in db.query(Expense).order_by(Expense.date)]
    return _csv("gastos.csv", ["id", "fecha", "categoria", "descripcion", "monto"], rows)


@router.get("/export/meta-catalog.csv")
def export_meta_catalog(request: Request, db: Session = Depends(get_db)):
    """Catálogo en el formato de Meta Commerce Manager (Facebook/Instagram/Marketplace)."""
    base = str(request.base_url).rstrip("/")
    currency = cfg.get(db, "currency")
    brand_default = cfg.get(db, "business_name")
    rows = []
    products = (db.query(Product).options(selectinload(Product.images))
                .filter(Product.status == "activo").all())
    for p in products:
        imgs = [f"{base}/uploads/{i.filename}" for i in p.images]
        rows.append([
            p.sku or f"P{p.id}", p.name[:150], (p.description or p.name)[:9999],
            "in stock" if p.stock > 0 else "out of stock",
            "new" if p.condition == "nuevo" else "used",
            f"{p.price:.2f} {currency}", f"{base}/#/productos/{p.id}",
            imgs[0] if imgs else "", ",".join(imgs[1:10]), p.brand or brand_default,
            p.stock, p.category,
        ])
    return _csv("catalogo_meta.csv", ["id", "title", "description", "availability", "condition",
                                      "price", "link", "image_link", "additional_image_link",
                                      "brand", "quantity_to_sell_on_facebook", "product_type"], rows)
