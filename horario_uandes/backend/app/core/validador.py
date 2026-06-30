"""
validador.py — Validación de un horario fijado manualmente (drag & drop) sin CP-SAT.

Reutiliza las funciones verificar_* de solver_cpsat.py para las restricciones duras
y calcular_fitness/construir_contexto de solver_ga.py para la penalización blanda,
evaluando directamente sobre las asignaciones que llegan del frontend (ya fijas,
sin optimizar nada — es un chequeo, no una búsqueda).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .blocks import TODOS_BLOQUES
from .models import DatosProblema
from .solver_cpsat import (
    disponibilidad_seccion,
    verificar_intra,
    verificar_rd3,
    verificar_rd4,
    verificar_rd7,
    verificar_topes,
)
from .solver_ga import calcular_fitness, construir_contexto


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ViolacionDura:
    tipo: str
    secciones: list[str] = field(default_factory=list)
    bloques: list[int] = field(default_factory=list)
    mensaje: str = ""


@dataclass
class ResultadoValidacion:
    factible: bool
    violaciones_duras: list[ViolacionDura] = field(default_factory=list)
    penalizacion_blanda: float = 0.0


def _bloque_label(idx: int) -> str:
    b = TODOS_BLOQUES[idx]
    return f"{b.dia.value} {b.hora_inicio}-{b.hora_fin}"


# ---------------------------------------------------------------------------
# Validación principal
# ---------------------------------------------------------------------------

def validar_horario(
    datos: DatosProblema,
    asignaciones: dict[str, list[int]],
    carreras: list[str] | None = None,
) -> ResultadoValidacion:
    """
    Evalúa un horario YA FIJO (lo que el usuario armó arrastrando bloques), sin
    correr CP-SAT. Solo recorre las asignaciones y marca qué restricciones duras
    se violan, igual que hacían los scripts diag_*.py pero reutilizable desde la API.
    """
    sec_by_id = {s.id: s for s in datos.secciones}
    # Ignorar ids que no existen en datos, o secciones sin bloques asignados aún
    asignaciones = {sid: bs for sid, bs in asignaciones.items() if sid in sec_by_id and bs}

    violaciones: list[ViolacionDura] = []

    # ── Intra-sección: bloques de la misma sección que se solapan entre sí ──
    for sec_id, b1, b2 in verificar_intra(asignaciones):
        violaciones.append(ViolacionDura(
            tipo="INTRA",
            secciones=[sec_id],
            bloques=[b1, b2],
            mensaje=(f"La sección {sec_id} tiene bloques que se solapan entre sí: "
                     f"{_bloque_label(b1)} y {_bloque_label(b2)}."),
        ))

    # ── RD1: topes de malla (cursos distintos, mismo carrera+semestre) ──
    carreras_a_chequear = carreras or sorted({
        car for c in datos.cursos.values() for car in c.semestres_por_carrera
    })
    vistos_rd1: set[frozenset] = set()
    for carrera in carreras_a_chequear:
        for id1, id2, sem in verificar_topes(datos, asignaciones, carrera):
            clave = frozenset((id1, id2, carrera, sem))
            if clave in vistos_rd1:
                continue
            vistos_rd1.add(clave)
            violaciones.append(ViolacionDura(
                tipo="RD1",
                secciones=[id1, id2],
                mensaje=(f"Tope de malla: {id1} y {id2} se solapan para "
                         f"{carrera} · semestre {sem}."),
            ))

    # ── RD2: disponibilidad del profesor ──
    for sec_id, bloques in asignaciones.items():
        s = sec_by_id[sec_id]
        dom = disponibilidad_seccion(datos, s, usar_rd2=True)
        fuera = [b for b in bloques if b not in dom]
        if fuera:
            violaciones.append(ViolacionDura(
                tipo="RD2",
                secciones=[sec_id],
                bloques=fuera,
                mensaje=(f"La sección {sec_id} quedó fuera de la disponibilidad de su "
                         f"profesor en: {', '.join(_bloque_label(b) for b in fuera)}."),
            ))

    # ── RD3: un profesor no puede dictar dos secciones a la vez ──
    for id1, id2 in verificar_rd3(datos, asignaciones):
        violaciones.append(ViolacionDura(
            tipo="RD3",
            secciones=[id1, id2],
            mensaje=f"El mismo profesor queda asignado a la vez en {id1} y {id2}.",
        ))

    # ── RD4: capacidad de salas especiales ──
    for id1, id2, sala in verificar_rd4(datos, asignaciones):
        violaciones.append(ViolacionDura(
            tipo="RD4",
            secciones=[id1, id2],
            mensaje=f"Sala especial '{sala}' sin capacidad: {id1} y {id2} se solapan.",
        ))

    # ── RD7: ayudantías antes de las 12:30 ──
    for sec_id, b in verificar_rd7(datos, asignaciones):
        violaciones.append(ViolacionDura(
            tipo="RD7",
            secciones=[sec_id],
            bloques=[b],
            mensaje=f"La ayudantía {sec_id} quedó antes de las 12:30 ({_bloque_label(b)}).",
        ))

    # ── Penalización blanda: reutiliza calcular_fitness del GA, sin evolucionar ──
    penalizacion_blanda = 0.0
    if asignaciones:
        try:
            ctx = construir_contexto(datos, asignaciones)
            individuo = [list(asignaciones[rep_id]) for rep_id in ctx.reps]
            penalizacion_blanda = calcular_fitness(individuo, ctx)[0]
        except Exception:
            # Si el horario manual quedó muy inconsistente para construir el
            # contexto del GA, no rompemos la validación dura por eso.
            penalizacion_blanda = -1.0

    return ResultadoValidacion(
        factible=len(violaciones) == 0,
        violaciones_duras=violaciones,
        penalizacion_blanda=penalizacion_blanda,
    )