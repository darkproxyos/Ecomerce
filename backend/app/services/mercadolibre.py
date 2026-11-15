"""Integración con la API oficial de Mercado Libre.

Requiere crear una aplicación en https://developers.mercadolibre.com.mx/devcenter
y configurar App ID, Client Secret y Redirect URI en la sección Configuración.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from ..models import Customer, Listing, Product, Sale, SaleItem
from . import settings as cfg
from .inventory import apply_stock

API = "https://api.mercadolibre.com"
AUTH_DOMAINS = {
    "MLM": "auth.mercadolibre.com.mx",
    "MLA": "auth.mercadolibre.com.ar",
    "MCO": "auth.mercadolibre.com.co",
    "MLC": "auth.mercadolibre.cl",
    "MLU": "auth.mercadolibre.com.uy",
    "MPE": "auth.mercadolibre.com.pe",
    "MEC": "auth.mercadolibre.com.ec",
    "MLB": "auth.mercadolivre.com.br",
}


class MLError(Exception):
    pass


def auth_url(db: Session) -> str:
    s = cfg.get_all(db)
    if not s["ml_app_id"] or not s["ml_redirect_uri"]:
        raise MLError("Configura primero App ID y Redirect URI de tu aplicación de Mercado Libre")
    domain = AUTH_DOMAINS.get(s["ml_site"], AUTH_DOMAINS["MLM"])
    query = urlencode({
        "response_type": "code",
        "client_id": s["ml_app_id"],
        "redirect_uri": s["ml_redirect_uri"],
    })
    return f"https://{domain}/authorization?{query}"


def _save_token(db: Session, data: dict) -> None:
    expires = datetime.now() + timedelta(seconds=int(data.get("expires_in", 21600)) - 120)
    values = {
        "ml_access_token": data["access_token"],
        "ml_token_expires": expires.isoformat(timespec="seconds"),
        "ml_user_id": str(data.get("user_id", "")),
    }
    if data.get("refresh_token"):
        values["ml_refresh_token"] = data["refresh_token"]
    cfg.set_many(db, values)


def _token_request(payload: dict) -> dict:
    resp = httpx.post(f"{API}/oauth/token", data=payload,
                      headers={"accept": "application/json"}, timeout=20)
    if resp.status_code != 200:
        raise MLError(f"Mercado Libre rechazó el token ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def exchange_code(db: Session, code: str) -> None:
    s = cfg.get_all(db)
    data = _token_request({
        "grant_type": "authorization_code",
        "client_id": s["ml_app_id"],
        "client_secret": s["ml_client_secret"],
        "code": code,
        "redirect_uri": s["ml_redirect_uri"],
    })
    _save_token(db, data)
    me = api_get(db, "/users/me")
    cfg.set_many(db, {"ml_nickname": me.get("nickname", ""), "ml_user_id": str(me.get("id", ""))})


def access_token(db: Session) -> str:
    """Devuelve un token válido, renovándolo si expiró. '' si no hay conexión."""
    s = cfg.get_all(db)
    token = s["ml_access_token"]
    if not token:
        return ""
    expires = s["ml_token_expires"]
    if expires and datetime.fromisoformat(expires) < datetime.now() and s["ml_refresh_token"]:
        data = _token_request({
            "grant_type": "refresh_token",
            "client_id": s["ml_app_id"],
            "client_secret": s["ml_client_secret"],
            "refresh_token": s["ml_refresh_token"],
        })
        _save_token(db, data)
        token = data["access_token"]
    return token


def api_get(db: Session, path: str, params: dict | None = None) -> dict:
    token = access_token(db)
    if not token:
        raise MLError("Mercado Libre no está conectado")
    resp = httpx.get(f"{API}{path}", params=params,
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if resp.status_code != 200:
        raise MLError(f"GET {path} → HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def api_put(db: Session, path: str, body: dict) -> dict:
    token = access_token(db)
    if not token:
        raise MLError("Mercado Libre no está conectado")
    resp = httpx.put(f"{API}{path}", json=body,
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if resp.status_code not in (200, 201):
        raise MLError(f"PUT {path} → HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _seller_sku(item: dict) -> str:
    if item.get("seller_custom_field"):
        return str(item["seller_custom_field"])
    for attr in item.get("attributes") or []:
        if attr.get("id") == "SELLER_SKU" and attr.get("value_name"):
            return str(attr["value_name"])
    return ""


def sync_listings(db: Session) -> dict:
    user_id = cfg.get(db, "ml_user_id")
    ids: list[str] = []
    offset = 0
    while True:
        page = api_get(db, f"/users/{user_id}/items/search", {"limit": 50, "offset": offset})
        ids += page.get("results", [])
        offset += 50
        if offset >= page.get("paging", {}).get("total", 0) or offset >= 1000:
            break

    created = updated = 0
    for i in range(0, len(ids), 20):
        batch = api_get(db, "/items", {"ids": ",".join(ids[i:i + 20])})
        for entry in batch:
            item = entry.get("body") or {}
            if not item.get("id"):
                continue
            listing = db.query(Listing).filter_by(channel="mercadolibre", external_id=item["id"]).first()
            if listing is None:
                listing = Listing(channel="mercadolibre", external_id=item["id"])
                db.add(listing)
                created += 1
            else:
                updated += 1
            listing.title = item.get("title", "")
            listing.url = item.get("permalink", "")
            listing.price = float(item.get("price") or 0)
            listing.status = {"active": "activa", "paused": "pausada"}.get(item.get("status"), "cerrada")
            if listing.product_id is None:
                sku = _seller_sku(item)
                if sku:
                    product = db.query(Product).filter_by(sku=sku).first()
                    if product:
                        listing.product_id = product.id
    db.commit()
    return {"publicaciones": len(ids), "nuevas": created, "actualizadas": updated}


def _find_product(db: Session, item: dict) -> Product | None:
    listing = db.query(Listing).filter_by(channel="mercadolibre", external_id=item.get("id", "")).first()
    if listing and listing.product:
        return listing.product
    sku = item.get("seller_sku") or item.get("seller_custom_field")
    if sku:
        return db.query(Product).filter_by(sku=str(sku)).first()
    return None


def import_order(db: Session, order: dict) -> str:
    """Crea o actualiza una venta a partir de un pedido de ML. Devuelve 'nueva'/'actualizada'."""
    ext_id = str(order["id"])
    status = {"paid": "pagado", "cancelled": "cancelado", "invalid": "cancelado"}.get(
        order.get("status", ""), "pendiente"
    )
    sale = db.query(Sale).filter_by(channel="mercadolibre", external_id=ext_id).first()
    if sale is not None:
        if sale.status != status and status == "cancelado":
            apply_stock(sale, restore=True)
            sale.status = status
        elif sale.status == "pendiente" and status == "pagado":
            sale.status = status
        return "actualizada"

    buyer = order.get("buyer") or {}
    customer = None
    if buyer.get("nickname"):
        customer = db.query(Customer).filter_by(name=buyer["nickname"], channel="mercadolibre").first()
        if customer is None:
            customer = Customer(name=buyer["nickname"], channel="mercadolibre")
            db.add(customer)
            db.flush()

    sale = Sale(
        channel="mercadolibre",
        external_id=ext_id,
        status=status,
        date=date.fromisoformat(order.get("date_created", date.today().isoformat())[:10]),
        customer_id=customer.id if customer else None,
        commission=0,
        notes=f"Importado de Mercado Libre (pack {order.get('pack_id') or '-'})",
    )
    commission = 0.0
    for oi in order.get("order_items", []):
        item = oi.get("item") or {}
        qty = int(oi.get("quantity") or 1)
        product = _find_product(db, item)
        commission += float(oi.get("sale_fee") or 0) * qty
        sale.items.append(SaleItem(
            product_id=product.id if product else None,
            product=product,
            description=item.get("title", ""),
            quantity=qty,
            unit_price=float(oi.get("unit_price") or 0),
            unit_cost=product.cost if product else 0,
        ))
    sale.commission = round(commission, 2)
    db.add(sale)
    if status != "cancelado":
        apply_stock(sale)
    return "nueva"


def sync_orders(db: Session, days: int = 30) -> dict:
    user_id = cfg.get(db, "ml_user_id")
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000-00:00")
    counts = {"nueva": 0, "actualizada": 0}
    offset = 0
    while True:
        page = api_get(db, "/orders/search", {
            "seller": user_id, "sort": "date_desc", "limit": 50, "offset": offset,
            "order.date_created.from": since,
        })
        for order in page.get("results", []):
            counts[import_order(db, order)] += 1
        offset += 50
        if offset >= page.get("paging", {}).get("total", 0) or offset >= 2000:
            break
    db.commit()
    return {"nuevas": counts["nueva"], "actualizadas": counts["actualizada"]}


def push_listing(db: Session, listing: Listing) -> dict:
    """Envía precio y stock local a la publicación de Mercado Libre."""
    body: dict = {"price": listing.price}
    if listing.product is not None:
        body["available_quantity"] = max(listing.product.stock, 0)
    return api_put(db, f"/items/{listing.external_id}", body)
