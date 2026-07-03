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
    disponibilidad: set[int] = field(default_factory=set)


@dataclass
class Curso:
    codigo: str
    titulo: str
    semestres_por_carrera: dict[str, set[str]] = field(default_factory=dict)
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
    rut_profesor_2: str = ""        # segundo profesor (co-dictante), "" si no hay
    cantidad_bloques_necesarios: int = 1
    tipos_bloques_necesarios: list[str] = field(default_factory=list)  # [] = normal; ["2h","1h"] = 2+1
    duracion_bloque: str = "2h"
    # True = CLAS de 3h sin distribución definida (3-juntas vs 2+1): NO se programa hasta
    # que el usuario elija la distribución (no se adivina). Ver parser._estructura_bloques.
    distribucion_indefinida: bool = False
    # Metadatos del Maestro para el Excel de salida (formato histórico Horario ING).
    nrc: str = ""
    area: str = ""
    plan: str = ""
    conector: str = ""
    bloques_asignados: list = field(default_factory=list)


@dataclass
class DatosProblema:
    cursos: dict[str, Curso] = field(default_factory=dict)
    secciones: list[Seccion] = field(default_factory=list)
    profesores: dict[str, Profesor] = field(default_factory=dict)
    capacidad_por_sala: dict[str, int] = field(default_factory=dict)