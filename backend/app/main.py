import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlencode

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import models  # noqa: F401  (registra las tablas)
from .config import (
    ADMIN_PASSWORD, AUTH_REQUIRED, CRON_SECRET, DATABASE_PERSISTENT, DATABASE_URL, ON_VERCEL,
    PUBLIC_DIR, SCHEDULER_ENABLED, SCHEDULER_TICK_SECONDS, SESSION_DAYS, SESSION_SECRET,
)
from .database import ensure_tables, get_db
from .routers import admin, dashboard, market, products, sales
from .services import market as market_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

COOKIE = "panel_session"


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        ensure_tables()
    except Exception:  # noqa: BLE001 - p. ej. base aún no configurada; se reintenta en cada petición
        log.exception("No se pudieron crear las tablas al arrancar")
    task = None
    if SCHEDULER_ENABLED:
        task = asyncio.create_task(market_service.scheduler_loop(SCHEDULER_TICK_SECONDS))
    yield
    if task:
        task.cancel()


app = FastAPI(title="Panel de Ventas", lifespan=lifespan)


# ------------------------------------------------------------------ sesión

def _sign(payload: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    expires = str(int(time.time()) + SESSION_DAYS * 86400)
    return f"{expires}.{_sign(expires)}"


def valid_token(token: str) -> bool:
    expires, _, sig = token.partition(".")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(expires))


PUBLIC_API = {"/api/health", "/api/status", "/api/login", "/api/logout", "/api/cron"}


def _is_public(request: Request) -> bool:
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC_API:
        return True
    # Las fotos son públicas (las lee el catálogo de Meta y las etiquetas <img>).
    return request.method == "GET" and path.startswith("/api/images/")


@app.middleware("http")
async def auth(request: Request, call_next):
    if not AUTH_REQUIRED or _is_public(request):
        return await call_next(request)
    if not ADMIN_PASSWORD:
        return JSONResponse({"detail": "Falta configurar ADMIN_PASSWORD en Vercel", "setup": True},
                            status_code=503)
    if valid_token(request.cookies.get(COOKIE, "")):
        return await call_next(request)
    return JSONResponse({"detail": "Inicia sesión", "login": True}, status_code=401)


class LoginIn(BaseModel):
    password: str


@app.post("/api/login")
def login(data: LoginIn):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "Falta configurar ADMIN_PASSWORD")
    if not secrets.compare_digest(data.password.encode(), ADMIN_PASSWORD.encode()):
        time.sleep(1)  # frena intentos de adivinar la contraseña
        raise HTTPException(401, "Contraseña incorrecta")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, make_token(), max_age=SESSION_DAYS * 86400, httponly=True,
                    secure=ON_VERCEL, samesite="lax", path="/")
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/api/status")
def status(request: Request):
    """Estado de la instalación: lo usa la pantalla de bienvenida/configuración."""
    db_ok, db_error = True, ""
    try:
        ensure_tables()
    except Exception as exc:  # noqa: BLE001
        db_ok, db_error = False, str(exc).splitlines()[0][:300]
    return {
        "vercel": ON_VERCEL,
        "auth_required": AUTH_REQUIRED,
        "password_configured": bool(ADMIN_PASSWORD),
        "logged_in": (not AUTH_REQUIRED) or valid_token(request.cookies.get(COOKIE, "")),
        "database": "postgres" if DATABASE_URL.startswith("postgresql") else "sqlite",
        "database_persistent": DATABASE_PERSISTENT,
        "database_ok": db_ok,
        "database_error": db_error,
        "cron_configured": bool(CRON_SECRET) or not ON_VERCEL,
    }


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/cron")
def cron(request: Request, db: Session = Depends(get_db)):
    """Ejecutado por Vercel Cron (ver vercel.json). Revisa precios y búsquedas pendientes."""
    if not CRON_SECRET:
        raise HTTPException(503, "Configura CRON_SECRET para activar las revisiones automáticas")
    if not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {CRON_SECRET}"):
        raise HTTPException(401, "No autorizado")
    return market_service.run_due(db)


for r in (dashboard.router, products.router, sales.router, market.router, admin.router):
    app.include_router(r)


class VercelPathFix:
    """Si Vercel entrega la ruta reescrita (/api/index?path=products), recupera la original."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and scope.get("path") in ("/api/index", "/api/index.py"):
            params = parse_qs(scope.get("query_string", b"").decode(), keep_blank_values=True)
            sub = params.pop("path", [""])[0].lstrip("/")
            path = f"/api/{sub}" if sub else "/api/health"
            scope = dict(scope, path=path, raw_path=path.encode(),
                         query_string=urlencode(params, doseq=True).encode())
        await self.app(scope, receive, send)


app.add_middleware(VercelPathFix)  # se agrega al final para que sea la capa más externa


# En Vercel los archivos de public/ los sirve su CDN. En un servidor propio los sirve FastAPI.
if not ON_VERCEL and PUBLIC_DIR.is_dir():
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(PUBLIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
