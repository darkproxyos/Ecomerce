"""Configuración guardada en la base de datos (tabla settings)."""
from sqlalchemy.orm import Session

from ..models import Setting

DEFAULTS: dict[str, str] = {
    "business_name": "Mi Negocio",
    "currency": "MXN",
    "ml_site": "MLM",
    # Comisión estimada por canal (porcentaje sobre el total de la venta).
    "fee_mercadolibre_pct": "13",
    "fee_marketplace_pct": "0",
    "fee_directo_pct": "0",
    "fee_otro_pct": "0",
    # Alertas de competencia: avisar si el competidor está X% más barato.
    "alert_cheaper_pct": "0",
    # Integración Mercado Libre (OAuth)
    "ml_app_id": "",
    "ml_client_secret": "",
    "ml_redirect_uri": "",
    "ml_access_token": "",
    "ml_refresh_token": "",
    "ml_token_expires": "",
    "ml_user_id": "",
    "ml_nickname": "",
}

SECRET_KEYS = {"ml_client_secret", "ml_access_token", "ml_refresh_token"}
MASK = "••••••••"


def get_all(db: Session) -> dict[str, str]:
    values = dict(DEFAULTS)
    for row in db.query(Setting).all():
        values[row.key] = row.value
    return values


def get(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    return row.value if row else DEFAULTS.get(key, "")


def get_float(db: Session, key: str, default: float = 0.0) -> float:
    try:
        return float(get(db, key) or default)
    except ValueError:
        return default


def set_many(db: Session, values: dict[str, str]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        if key in SECRET_KEYS and value == MASK:
            continue  # el usuario no cambió el secreto
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=str(value)))
        else:
            row.value = str(value)
    db.commit()


def public_view(db: Session) -> dict[str, str]:
    values = get_all(db)
    for key in SECRET_KEYS:
        if values.get(key):
            values[key] = MASK
    return values
