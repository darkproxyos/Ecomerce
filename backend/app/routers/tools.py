"""Mi ruta (avance del negocio) y respaldo / restauración de datos."""
import datetime as dt

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .. import clock
from ..config import ALLOWED_IMAGE_TYPES, MAX_UPLOAD_MB
from ..database import Base, engine, get_db
from ..models import Product, ProductImage
from ..schemas import RoadmapTaskIn
from ..services import roadmap as rm
from ..services import settings as cfg

router = APIRouter(prefix="/api", tags=["herramientas"])


# ------------------------------------------------------------------ Mi ruta

@router.get("/roadmap")
def get_roadmap(db: Session = Depends(get_db)):
    data = rm.roadmap(db)
    data["initial_capital"] = cfg.get_float(db, "initial_capital")
    return data


@router.put("/roadmap/tasks/{task_id}")
def mark_task(task_id: str, data: RoadmapTaskIn, db: Session = Depends(get_db)):
    if task_id not in rm.TASK_IDS:
        raise HTTPException(404, "Tarea no encontrada")
    rm.set_task(db, task_id, data.done)
    return {"ok": True}


# ------------------------------------------------------------------ respaldo

BACKUP_FORMAT = "panel-ventas-respaldo"
# Orden de inserción (respeta las llaves foráneas). Las fotos van aparte.
TABLES = ["products", "customers", "listings", "sales", "sale_items", "expenses", "watch_items",
          "price_snapshots", "market_searches", "market_results", "opportunities", "settings"]
# Credenciales que nunca salen en un respaldo (se reconectan en el panel nuevo).
PRIVATE_SETTINGS = cfg.SECRET_KEYS | {"ml_token_expires", "ml_user_id", "ml_nickname"}


def _dump_value(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    return v


def _load_value(col, v):
    if v is None:
        return None
    try:
        py = col.type.python_type
    except NotImplementedError:
        return v
    if py is dt.datetime and isinstance(v, str):
        return dt.datetime.fromisoformat(v)
    if py is dt.date and isinstance(v, str):
        return dt.date.fromisoformat(v[:10])
    if py is bool:
        return bool(v)
    return v


@router.get("/backup")
def backup(db: Session = Depends(get_db)):
    """Todos los datos en JSON. Las fotos se listan sin su contenido: el navegador las
    descarga una por una y arma el archivo (así no choca con el límite de 4.5 MB de Vercel)."""
    tables = Base.metadata.tables
    out: dict = {}
    for name in TABLES:
        table = tables[name]
        rows = [dict(r._mapping) for r in db.execute(table.select())]
        if name == "settings":
            rows = [r for r in rows if r["key"] not in PRIVATE_SETTINGS]
        out[name] = [{k: _dump_value(v) for k, v in r.items()} for r in rows]
    images = tables["product_images"]
    cols = [c for c in images.columns if c.name != "data"]
    out["product_images"] = [{k: _dump_value(v) for k, v in dict(r._mapping).items()}
                             for r in db.execute(images.select().with_only_columns(*cols))]
    return {"format": BACKUP_FORMAT, "version": 1, "exported_at": clock.now().isoformat(), "tables": out}


def _reset_sequences(conn) -> None:
    if engine.dialect.name != "postgresql":
        return
    for name, table in Base.metadata.tables.items():
        if "id" in table.columns and table.columns["id"].primary_key:
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {name}), 1), "
                f"(SELECT MAX(id) FROM {name}) IS NOT NULL)"))


@router.post("/restore")
def restore(payload: dict, db: Session = Depends(get_db)):
    """Reemplaza TODOS los datos por los del respaldo (sin fotos; esas se suben después)."""
    if payload.get("format") != BACKUP_FORMAT or not isinstance(payload.get("tables"), dict):
        raise HTTPException(400, "El archivo no es un respaldo de este panel")
    data = payload["tables"]
    tables = Base.metadata.tables
    db.close()
    counts = {}
    with engine.begin() as conn:
        conn.execute(tables["product_images"].delete())
        for name in reversed(TABLES):
            stmt = tables[name].delete()
            if name == "settings":
                stmt = stmt.where(tables[name].c.key.notin_(PRIVATE_SETTINGS))
            conn.execute(stmt)
        for name in TABLES:
            rows = data.get(name) or []
            table = tables[name]
            if name == "settings":
                rows = [r for r in rows if r.get("key") not in PRIVATE_SETTINGS]
            clean = [{c.name: _load_value(c, r.get(c.name)) for c in table.columns if c.name in r}
                     for r in rows]
            if clean:
                conn.execute(table.insert(), clean)
            counts[name] = len(clean)
        _reset_sequences(conn)
    counts["fotos_pendientes"] = len(data.get("product_images") or [])
    return counts


@router.post("/restore/image")
async def restore_image(product_id: int = Form(...), position: int = Form(0),
                        file: UploadFile = File(...), db: Session = Depends(get_db)):
    if db.get(Product, product_id) is None:
        raise HTTPException(404, "Producto no encontrado")
    ctype = (file.content_type or "").lower().replace("image/jpg", "image/jpeg")
    if ctype not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Formato de imagen no permitido")
    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"La foto supera {MAX_UPLOAD_MB} MB")
    db.add(ProductImage(product_id=product_id, position=position, filename=(file.filename or "")[:255],
                        content_type=ctype, size=len(content), data=content))
    db.commit()
    return {"ok": True}


@router.get("/backup/summary")
def backup_summary(db: Session = Depends(get_db)):
    tables = Base.metadata.tables
    return {name: db.execute(func.count().select().select_from(tables[name])).scalar()
            for name in ["products", "product_images", "sales", "customers", "expenses", "opportunities"]}
