"""
models_db.py — Modelos ORM (SQLAlchemy) de persistencia.

Jerarquía:
  Planificacion  (un "proyecto" de horario; posee sus archivos de entrada como blobs)
    └── Version  (snapshots del horario dentro de la planificación; estado en JSON)

Los archivos de entrada (Maestro, salas) se guardan como BLOBs (bytes crudos del .xlsx)
para que la planificación sea autocontenida y persista entre sesiones/redeploys.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text, Boolean,
)
from sqlalchemy.orm import relationship

from .database import Base


class Planificacion(Base):
    __tablename__ = "planificacion"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(200), nullable=False)
    creada = Column(DateTime, default=datetime.utcnow)
    actualizada = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Dueño de la planificación (email de la sesión). Cada usuario solo ve/gestiona las suyas.
    owner_email = Column(String(320), default="", index=True)

    # Archivos de entrada como blobs (bytes del .xlsx)
    maestro_nombre = Column(String(300), default="")
    maestro_bytes = Column(LargeBinary)
    salas_nombre = Column(String(300), default="")
    salas_bytes = Column(LargeBinary)

    versiones = relationship(
        "Version", back_populates="planificacion",
        cascade="all, delete-orphan", order_by="Version.creada",
    )


class Version(Base):
    __tablename__ = "version"

    id = Column(Integer, primary_key=True)
    planificacion_id = Column(
        Integer, ForeignKey("planificacion.id", ondelete="CASCADE"), nullable=False,
    )
    nombre = Column(String(200), nullable=False)
    creada = Column(DateTime, default=datetime.utcnow)
    es_autosave = Column(Boolean, default=False)   # True = snapshot automático (no manual)
    estado_json = Column(Text)                     # estado del horario serializado a JSON

    planificacion = relationship("Planificacion", back_populates="versiones")
