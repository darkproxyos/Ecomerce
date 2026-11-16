"""Configuración por variables de entorno.

En Vercel el disco es de solo lectura y efímero, así que los datos (incluidas las
fotos) viven en PostgreSQL. Localmente, si no hay base configurada, se usa SQLite.
"""
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
PUBLIC_DIR = ROOT_DIR / "public"
ON_VERCEL = bool(os.getenv("VERCEL"))


def _database_url() -> tuple[str, bool]:
    """Devuelve (url, es_persistente)."""
    url = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
           or os.getenv("POSTGRES_PRISMA_URL") or "").strip()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url, True
    if ON_VERCEL:
        # Sin base de datos: funciona, pero los datos se pierden. La interfaz lo avisa.
        return "sqlite:////tmp/negocio.db", False
    data_dir = Path(os.getenv("DATA_DIR", ROOT_DIR / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir / 'negocio.db'}", True


DATABASE_URL, DATABASE_PERSISTENT = _database_url()

# Contraseña del panel. En Vercel es obligatoria: sin ella la API no muestra datos.
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "") or ("panel:" + ADMIN_PASSWORD)
SESSION_DAYS = 30
AUTH_REQUIRED = bool(ADMIN_PASSWORD) or ON_VERCEL

# Vercel Cron envía "Authorization: Bearer <CRON_SECRET>".
CRON_SECRET = os.getenv("CRON_SECRET", "")

APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Mexico_City")

# Planificador interno (solo en servidor propio; en Vercel lo hace Vercel Cron).
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "0" if ON_VERCEL else "1") == "1"
SCHEDULER_TICK_SECONDS = int(os.getenv("SCHEDULER_TICK_SECONDS", "60"))
# Tiempo máximo de scraping por ejecución (las funciones de Vercel tienen límite).
RUN_DUE_BUDGET_SECONDS = int(os.getenv("RUN_DUE_BUDGET_SECONDS", "50"))

# Vercel acepta peticiones de hasta 4.5 MB; el navegador comprime las fotos antes de subirlas.
MAX_UPLOAD_MB = 4
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
