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
    # Índices de bloques donde el profesor está disponible (de TODOS_BLOQUES).
    # Set vacío = disponibilidad total (no hay datos o los campos del Maestro estaban vacíos).
    disponibilidad: set[int] = field(default_factory=set)


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
    tipos_bloques_necesarios: list[str] = field(default_factory=list)  # [] = todos iguales; ["2h","1h"] = 2+1
    bloques_asignados: list = field(default_factory=list)

@dataclass
class DatosProblema:
    cursos: dict[str, Curso] = field(default_factory=dict)         # codigo → Curso
    secciones: list[Seccion] = field(default_factory=list)
    profesores: dict[str, Profesor] = field(default_factory=dict)  # rut → Profesor
    # sala_name → cantidad de salas físicas de ese tipo
    # sala_name = el NOMBRE que aparece en Curso.sala_especial (parte antes de " EN HORARIO DE ")
    # Ej: {"LABT COMPUTACION": 4, "LABT ELECTRICA": 1, "SALA CON ENCHUFE INDIVIDUAL": 8}
    capacidad_por_sala: dict[str, int] = field(default_factory=dict)
