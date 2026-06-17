"""
Bloques horarios fijos de la Facultad de Ingeniería.

Dos bloques se solapan si son del mismo día Y comparten al menos un sub-bloque
de 50 minutos. La verificación es por sub-bloques, NO por igualdad de índice.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import ClassVar

from .models import Dia


def _min(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


# Sub-bloques: cada slot de 50 min, representado por su minuto de inicio.
# 8:30, 9:30, 10:30, 11:30, 12:30, 13:30, 14:30, 15:30, 16:30, 17:30, 18:30
_SUB_INICIO_MIN = [_min(t) for t in [
    "8:30", "9:30", "10:30", "11:30", "12:30",
    "13:30", "14:30", "15:30", "16:30", "17:30", "18:30",
]]

# Definición de bloques: (hora_inicio, hora_fin, tipo, es_estandar)
#
# Bloques ESTÁNDAR: la grilla institucional preferida. Las clases deberían caer
# aquí salvo que la disponibilidad del profesor obligue a usar un bloque "helper".
#
# Bloques HELPER (es_estandar=False): rellenan los huecos del catálogo estándar
# para que cualquier disponibilidad declarada en sub-bloques de 50 min sea
# representable. El solver los usa solo como último recurso (ver objetivo en
# solver_cpsat: minimizar uso de bloques no estándar).
_BLOQUES_DEF: list[tuple[str, str, str, bool]] = [
    # ── 5 bloques de 2h ESTÁNDAR ──
    ("8:30",  "10:20", "2h", True),
    ("10:30", "12:20", "2h", True),
    ("13:30", "15:20", "2h", True),   # primer bloque de tarde, tras el almuerzo
    ("15:30", "17:20", "2h", True),
    ("17:30", "19:20", "2h", True),
    # ── 2 bloques de 3h ESTÁNDAR (cruzan el horario de almuerzo) ──
    ("10:30", "13:20", "3h", True),   # sub-bloques: 10:30, 11:30, 12:30
    ("12:30", "15:20", "3h", True),   # sub-bloques: 12:30, 13:30, 14:30
    # ── bloques de 2h HELPER (rellenan los inicios 9:30, 11:30, 12:30, 14:30, 16:30) ──
    ("9:30",  "11:20", "2h", False),
    ("11:30", "13:20", "2h", False),
    ("12:30", "14:20", "2h", False),
    ("14:30", "16:20", "2h", False),
    ("16:30", "18:20", "2h", False),
    # ── bloques de 3h HELPER (mañana temprano, tarde y noche) ──
    ("8:30",  "11:20", "3h", False),
    ("9:30",  "12:20", "3h", False),
    ("11:30", "14:20", "3h", False),
    ("13:30", "16:20", "3h", False),
    ("14:30", "17:20", "3h", False),
    ("15:30", "18:20", "3h", False),
    ("16:30", "19:20", "3h", False),   # el caso del profesor disponible solo en la tarde
    # ── bloques de 1h ESTÁNDAR (solo para el componente corto de clases 2+1) ──
    ("8:30",  "9:20",  "1h", True),
    ("9:30",  "10:20", "1h", True),
    ("10:30", "11:20", "1h", True),
    ("11:30", "12:20", "1h", True),
    ("12:30", "13:20", "1h", True),
    ("13:30", "14:20", "1h", True),
    ("14:30", "15:20", "1h", True),
    ("15:30", "16:20", "1h", True),
    ("16:30", "17:20", "1h", True),
    ("17:30", "18:20", "1h", True),
]

BLOQUES_2H = [d for d in _BLOQUES_DEF if d[2] == "2h"]
BLOQUES_3H = [d for d in _BLOQUES_DEF if d[2] == "3h"]


def _sub_bloques_de(inicio: str, fin: str) -> frozenset[int]:
    """Retorna el conjunto de sub-bloque starts (minutos) que caen dentro del bloque."""
    b_ini = _min(inicio)
    b_fin = _min(fin)
    return frozenset(s for s in _SUB_INICIO_MIN if s >= b_ini and s + 50 <= b_fin)


@dataclass(frozen=True)
class SubBloque:
    dia: Dia
    hora_inicio: str
    hora_fin: str


@dataclass(frozen=True)
class BloqueHorario:
    idx: int
    dia: Dia
    hora_inicio: str
    hora_fin: str
    tipo: str                        # "2h" o "3h"
    sub_bloques: frozenset[int]      # minutos de inicio de cada sub-bloque contenido
    es_estandar: bool = True         # True = grilla institucional preferida; False = helper

    def es_3h(self) -> bool:
        return self.tipo == "3h"

    def __repr__(self) -> str:
        marca = "" if self.es_estandar else " (helper)"
        return f"BloqueHorario({self.dia.value} {self.hora_inicio}-{self.hora_fin}{marca})"


def generar_bloques_horarios() -> list[BloqueHorario]:
    """Genera todos los bloques horarios (slots × 5 días), estándar + helper."""
    bloques: list[BloqueHorario] = []
    idx = 0
    for dia in Dia:
        for ini, fin, tipo, es_std in _BLOQUES_DEF:
            bloques.append(BloqueHorario(
                idx=idx,
                dia=dia,
                hora_inicio=ini,
                hora_fin=fin,
                tipo=tipo,
                sub_bloques=_sub_bloques_de(ini, fin),
                es_estandar=es_std,
            ))
            idx += 1
    return bloques


def bloques_se_solapan(b1: BloqueHorario, b2: BloqueHorario) -> bool:
    """True si b1 y b2 son el mismo día y comparten al menos un sub-bloque."""
    if b1.dia != b2.dia:
        return False
    return not b1.sub_bloques.isdisjoint(b2.sub_bloques)


# Pre-computados al importar el módulo
TODOS_BLOQUES: list[BloqueHorario] = generar_bloques_horarios()
N_BLOQUES = len(TODOS_BLOQUES)

# Índices de bloques estándar y helper (para preferir los estándar en el solver)
BLOQUES_ESTANDAR: list[int] = [i for i, b in enumerate(TODOS_BLOQUES) if b.es_estandar]
BLOQUES_HELPER:   list[int] = [i for i, b in enumerate(TODOS_BLOQUES) if not b.es_estandar]
SET_ESTANDAR: frozenset[int] = frozenset(BLOQUES_ESTANDAR)
BLOQUES_1H: frozenset[int] = frozenset(i for i, b in enumerate(TODOS_BLOQUES) if b.tipo == "1h")
BLOQUES_2H_SET: frozenset[int] = frozenset(i for i, b in enumerate(TODOS_BLOQUES) if b.tipo == "2h")
BLOQUES_3H_SET: frozenset[int] = frozenset(i for i, b in enumerate(TODOS_BLOQUES) if b.tipo == "3h")

# Matriz de solapamiento [i][j] = True si TODOS_BLOQUES[i] solapa con TODOS_BLOQUES[j]
MATRIZ_SOLAPAMIENTO: list[list[bool]] = [
    [bloques_se_solapan(TODOS_BLOQUES[i], TODOS_BLOQUES[j]) for j in range(N_BLOQUES)]
    for i in range(N_BLOQUES)
]
