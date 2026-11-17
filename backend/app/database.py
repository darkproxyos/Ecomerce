import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL, ON_VERCEL

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
elif ON_VERCEL:
    # Funciones serverless: sin pool propio (usa la URL "pooled" de Neon/Supabase).
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


_tables_ready = False


def ensure_tables() -> None:
    """Crea las tablas la primera vez (en serverless no hay evento de arranque fiable)."""
    global _tables_ready
    if not _tables_ready:
        Base.metadata.create_all(engine)
        add_missing_columns()
        _tables_ready = True


def add_missing_columns() -> None:
    """Agrega columnas nuevas a tablas que ya existían (create_all solo crea tablas).

    Se agregan sin NOT NULL para que funcione con filas existentes en SQLite y PostgreSQL.
    """
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}'))
                logging.getLogger("db").info("Columna agregada: %s.%s", table.name, col.name)


def get_db():
    ensure_tables()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
