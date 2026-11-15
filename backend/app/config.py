import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
FRONTEND_DIR = ROOT_DIR / "frontend"
GAMES_DIR = ROOT_DIR / "games"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'negocio.db'}")

# Si se define, todo el dashboard pide usuario/contraseña (HTTP Basic).
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# Cada cuántos segundos revisa el planificador si hay tareas de scraping pendientes.
SCHEDULER_TICK_SECONDS = int(os.getenv("SCHEDULER_TICK_SECONDS", "60"))
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "1") == "1"

MAX_UPLOAD_MB = 10
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
