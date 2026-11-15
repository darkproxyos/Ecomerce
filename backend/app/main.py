import asyncio
import base64
import binascii
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registra las tablas)
from .config import (
    ADMIN_PASSWORD, ADMIN_USER, FRONTEND_DIR, GAMES_DIR, SCHEDULER_ENABLED, SCHEDULER_TICK_SECONDS, UPLOAD_DIR,
)
from .database import Base, engine
from .routers import admin, dashboard, market, products, sales
from .services.market import scheduler_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    task = asyncio.create_task(scheduler_loop(SCHEDULER_TICK_SECONDS)) if SCHEDULER_ENABLED else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Dashboard de Ventas", lifespan=lifespan)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Protege todo el dashboard si se define la variable ADMIN_PASSWORD."""
    # Los juegos son públicos: cualquiera puede jugar sin la contraseña del panel.
    path = request.url.path
    if not ADMIN_PASSWORD or path == "/api/health" or path.startswith("/juegos/"):
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            user, _, pwd = base64.b64decode(header[6:]).decode().partition(":")
        except (binascii.Error, UnicodeDecodeError):
            user = pwd = ""
        if secrets.compare_digest(user, ADMIN_USER) and secrets.compare_digest(pwd, ADMIN_PASSWORD):
            return await call_next(request)
    return Response("Autenticación requerida", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Dashboard"'})


for r in (dashboard.router, products.router, sales.router, market.router, admin.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
if GAMES_DIR.is_dir():
    app.mount("/juegos", StaticFiles(directory=GAMES_DIR, html=True), name="juegos")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
