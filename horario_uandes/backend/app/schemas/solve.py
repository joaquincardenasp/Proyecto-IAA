from __future__ import annotations
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


class SolveResult(BaseModel):
    metricas: MetricasResult
    secciones: list[SeccionAsignada]
