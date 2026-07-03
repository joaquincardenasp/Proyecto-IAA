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
    tipo: str           # "RD1", "RD3", "RD4", "RB1", ..., "RB4"
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


# ---------------------------------------------------------------------------
# Diagnóstico (cuando no hay horario completo factible)
# ---------------------------------------------------------------------------

class SugerenciaItem(BaseModel):
    causa: str                              # "2mas1_sin_par", "RD2", "contencion", ...
    severidad: str                          # "alta" | "media"
    mensaje: str                            # explicación legible
    acciones: list[str] = Field(default_factory=list)
    secciones: list[str] = Field(default_factory=list)
    profesores: list[str] = Field(default_factory=list)
    bloques: list[str] = Field(default_factory=list)


class DiagnosticoUnidadItem(BaseModel):
    carrera: str
    semestre: str
    causa_principal: str
    sugerencias: list[SugerenciaItem] = Field(default_factory=list)


class DiagnosticoResult(BaseModel):
    unidades: list[DiagnosticoUnidadItem] = Field(default_factory=list)


class DecisionSeccion(BaseModel):
    """Una sección que requiere/admite una decisión estructural del usuario."""
    sec_id: str
    codigo: str
    titulo: str
    seccion: str
    profesor: str
    tipo: str                 # "distribucion" (3h sin definir) | "duracion_1h" (componente de 1h)
    opciones: list[str]       # ["3-juntas", "2+1"] o ["1h", "2h"]
    actual: str               # opción vigente ("" si indefinida)
    requerida: bool           # True = bloquea la programación; False = ajuste opcional
    mensaje: str


class SolveResult(BaseModel):
    # FACTIBLE (horario completo) | PARCIAL (subconjunto + diagnóstico) | INFEASIBLE (solo diagnóstico)
    estado: str = "FACTIBLE"
    metricas: Optional[MetricasResult] = None
    secciones: list[SeccionAsignada] = Field(default_factory=list)
    reporte: Optional[ReporteDetallado] = None
    diagnostico: Optional[DiagnosticoResult] = None
    # Secciones que requieren decisión (distribución 3h) o admiten un ajuste (componente 1h).
    decisiones: list[DecisionSeccion] = Field(default_factory=list)


class DecisionRequest(BaseModel):
    sec_id: str
    opcion: str               # "3-juntas" | "2+1" (distribución) o "1h" | "2h" (duración)


# ---------------------------------------------------------------------------
# Persistencia: planificaciones y versiones
# ---------------------------------------------------------------------------

class PlanificacionInfo(BaseModel):
    id: int
    nombre: str
    creada: str
    actualizada: str
    maestro_nombre: str = ""
    salas_nombre: str = ""
    n_versiones: int = 0
    activa: bool = False
    # Estado derivado del autoguardado (para las tarjetas del inicio)
    tiene_horario: bool = False
    estado_horario: str = ""          # FACTIBLE | PARCIAL | INFEASIBLE | ""
    n_secciones: int = 0
    n_conflictos: int = 0             # violaciones duras del reporte


class VersionInfo(BaseModel):
    id: int
    planificacion_id: int
    nombre: str
    creada: str
    es_autosave: bool = False


class GuardarVersionRequest(BaseModel):
    nombre: str


# ---------------------------------------------------------------------------
# Edición manual del horario (click-para-mover)
# ---------------------------------------------------------------------------

class BloqueValido(BaseModel):
    bloque: int                 # índice del bloque en el catálogo
    dia: str
    hora_inicio: str
    hora_fin: str
    es_helper: bool
    actual: bool                # True si es el bloque que ocupa hoy la sección
    estado: str                 # "valido" | "conflicto"
    motivos: list[str] = Field(default_factory=list)


class BloquesValidosRequest(BaseModel):
    sec_id: str
    indice: int = 0             # cuál de los bloques de la sección se está moviendo


class BloquesValidosResponse(BaseModel):
    sec_id: str
    indice: int
    candidatos: list[BloqueValido] = Field(default_factory=list)


class ConflictoItem(BaseModel):
    tipo: str                   # "RD1" | "RD2" | ... | "intra" | "NRC"
    motivo: str


class ConflictoActivo(BaseModel):
    tipo: str                   # "RD1" | "RD3" | ... | "intra" | "NRC"
    motivo: str
    secciones: list[str]        # ids de las secciones involucradas


class MoverRequest(BaseModel):
    sec_id: str
    indice: int
    destino: int                # índice del bloque destino en el catálogo


class MoverResponse(BaseModel):
    sec_id: str
    seccion: SeccionAsignada    # sección con su nueva asignación
    conflictos: list[ConflictoItem] = Field(default_factory=list)