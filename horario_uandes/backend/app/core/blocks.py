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

# Definición de bloques: (hora_inicio, hora_fin, tipo)
_BLOQUES_DEF: list[tuple[str, str, str]] = [
    # 7 bloques de 2h
    ("8:30",  "10:20", "2h"),
    ("10:30", "12:20", "2h"),
    ("12:30", "14:20", "2h"),
    ("14:30", "16:20", "2h"),
    ("15:30", "17:20", "2h"),
    ("16:30", "18:20", "2h"),
    ("17:30", "19:20", "2h"),
    # 2 bloques de 3h
    ("10:30", "13:20", "3h"),
    ("12:30", "15:20", "3h"),
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

    def es_3h(self) -> bool:
        return self.tipo == "3h"

    def __repr__(self) -> str:
        return f"BloqueHorario({self.dia.value} {self.hora_inicio}-{self.hora_fin})"


def generar_bloques_horarios() -> list[BloqueHorario]:
    """Genera los 45 bloques horarios (9 slots × 5 días)."""
    bloques: list[BloqueHorario] = []
    idx = 0
    for dia in Dia:
        for ini, fin, tipo in _BLOQUES_DEF:
            bloques.append(BloqueHorario(
                idx=idx,
                dia=dia,
                hora_inicio=ini,
                hora_fin=fin,
                tipo=tipo,
                sub_bloques=_sub_bloques_de(ini, fin),
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

# Matriz de solapamiento [i][j] = True si TODOS_BLOQUES[i] solapa con TODOS_BLOQUES[j]
MATRIZ_SOLAPAMIENTO: list[list[bool]] = [
    [bloques_se_solapan(TODOS_BLOQUES[i], TODOS_BLOQUES[j]) for j in range(N_BLOQUES)]
    for i in range(N_BLOQUES)
]
