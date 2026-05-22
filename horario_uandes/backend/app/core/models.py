from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TipoReunion(Enum):
    CLAS = "CLAS"
    AYUD = "AYUD"
    LABT = "LABT"


class TipoProfesor(Enum):
    JORNADA = "JORNADA"
    HONORARIO = "HONORARIO"
    PENDIENTE = "PENDIENTE"


class Dia(Enum):
    L = "L"
    M = "M"
    X = "X"
    J = "J"
    V = "V"


@dataclass
class Profesor:
    rut: str
    nombre: str
    tipo: TipoProfesor


@dataclass
class Curso:
    codigo: str
    titulo: str
    # Unión de semestres por carrera a través de los 3 planes de estudio.
    # carrera ∈ {"Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA", "ICQ"}
    # semestre es un STRING que preserva sufijos de mención: "9a", "10f", "1", etc.
    # Un mismo curso puede pertenecer a múltiples semestres de una carrera si
    # los planes difieren (ej. ICC-"7" en PE2022 y ICC-"6" en PE2025).
    semestres_por_carrera: dict[str, set[str]] = field(default_factory=dict)
    # Planes en los que aparece este curso (para reportes y conteo)
    planes: set[str] = field(default_factory=set)
    clases_horas: int = 0
    ayudantias_horas: int = 0
    laboratorios_horas: int = 0
    sala_especial: Optional[str] = None


@dataclass
class Seccion:
    id: str                         # "{codigo_curso}-{seccion}-{componente}"
    codigo_curso: str
    seccion: str
    componente: TipoReunion
    rut_profesor: str
    afecta_disponibilidad: bool
    cantidad_bloques_necesarios: int = 1
    bloques_asignados: list = field(default_factory=list)  # lista de BloqueHorario


@dataclass
class DatosProblema:
    cursos: dict[str, Curso] = field(default_factory=dict)        # codigo → Curso
    secciones: list[Seccion] = field(default_factory=list)
    profesores: dict[str, Profesor] = field(default_factory=dict)  # rut → Profesor
