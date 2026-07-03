"""
database.py — Conexión a la base de datos (persistencia de planificaciones y versiones).

DB-agnóstico vía SQLAlchemy y la variable de entorno DATABASE_URL:
  - Local (por defecto): SQLite en un archivo (horario.db) — cero setup.
  - Producción (Render): Postgres, seteando DATABASE_URL con la connection string.

El código no cambia entre motores; solo la URL.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Ruta por defecto: SQLite junto al backend. En prod, Render entrega DATABASE_URL.
_DEFAULT_SQLITE = "sqlite:///./horario.db"
DATABASE_URL = os.getenv("DATABASE_URL", _DEFAULT_SQLITE)

# Render/Heroku entregan 'postgres://'; SQLAlchemy espera 'postgresql://'.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()


def get_session():
    """Context manager sencillo para una sesión (uso: `with get_session() as db:`)."""
    return SessionLocal()


def init_db() -> None:
    """Crea las tablas si no existen. Se llama al iniciar la app."""
    from . import models_db  # noqa: F401  (registra los modelos en Base)
    Base.metadata.create_all(bind=engine)
    _migrar_owner_email()


def _migrar_owner_email() -> None:
    """
    Migración ligera: agrega planificacion.owner_email si falta (DBs creadas antes de que la
    columna existiera). create_all no altera tablas ya creadas, así que lo hacemos a mano.
    Compatible con SQLite y Postgres (ADD COLUMN básico).
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "planificacion" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("planificacion")}
    if "owner_email" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE planificacion ADD COLUMN owner_email VARCHAR(320)"))
