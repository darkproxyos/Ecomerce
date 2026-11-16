"""Fecha y hora en la zona del negocio (los servidores de Vercel usan UTC)."""
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import APP_TIMEZONE

try:
    TZ = ZoneInfo(APP_TIMEZONE)
except ZoneInfoNotFoundError:
    TZ = ZoneInfo("UTC")


def now() -> datetime:
    """Hora local sin zona (así se guarda en la base)."""
    return datetime.now(TZ).replace(tzinfo=None)


def today() -> date:
    return now().date()
