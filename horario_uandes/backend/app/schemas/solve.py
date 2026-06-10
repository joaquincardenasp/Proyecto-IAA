from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class SolveRequest(BaseModel):
    carreras: list[str] = ["Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA", "ICQ"]
    n_generaciones: int = Field(200, ge=1, le=1000)
    pop_size: int = Field(40, ge=4, le=200)
    tiempo_limite_cpsat: float = Field(60.0, ge=5.0, le=300.0)
    seed: int = 42


class StatusResponse(BaseModel):
    status: str       # idle | running | ready | error
    progress: str = ""
    error: str = ""


class BloqueAsignado(BaseModel):
    dia: str
    hora_inicio: str
    hora_fin: str
    tipo_bloque: str  # 2h | 3h


class SeccionAsignada(BaseModel):
    id: str
    codigo: str
    titulo: str
    seccion: str
    tipo: str         # CLAS | AYUD | LABT
    profesor: str
    bloques: list[BloqueAsignado]
    carreras: str
    semestres: str


class MetricasResult(BaseModel):
    fitness_cpsat: float
    fitness_ga: float
    mejora_pct: float
    n_secciones: int
    n_bloques_totales: int
    estado_cpsat: str


# ---------------------------------------------------------------------------
# Reporte de violaciones
# ---------------------------------------------------------------------------

class SeccionRef(BaseModel):
    id: str
    codigo: str
    titulo: str
    seccion: str
    tipo: str   # CLAS | AYUD | LABT


class ViolacionItem(BaseModel):
    tipo: str           # "RD1", "RD3", "RD4", "RB1", ..., "RB5"
    descripcion: str    # label corto: "Tope de malla", "Conflicto de profesor", ...
    mensaje: str        # descripción completa legible para Francisca
    secciones: list[SeccionRef]
    bloques: list[str]  # ["Martes 10:30-12:20", ...]
    contexto: str       # "ICI · semestre 5", "Prof. Juan Pérez", "Sala LABT COMP."
    penalizacion: Optional[float] = None  # None para duras, float para blandas


class ResumenReporte(BaseModel):
    total_duras: int
    total_blandas: int
    por_tipo_dura: dict[str, int]     # {"RD1": 2, "RD3": 0, ...}
    por_tipo_blanda: dict[str, int]   # {"RB1": 0, "RB2": 3, ...}
    penalizacion_total: float
    penalizacion_por_rb: dict[str, float]  # {"RB2": 240, ...}


class ReporteDetallado(BaseModel):
    resumen: ResumenReporte
    violaciones_duras: list[ViolacionItem]
    violaciones_blandas: list[ViolacionItem]


class SolveResult(BaseModel):
    metricas: MetricasResult
    secciones: list[SeccionAsignada]
    reporte: Optional[ReporteDetallado] = None
