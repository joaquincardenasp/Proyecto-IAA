"""
diagnostico.py — Fase 2 del asistente: cuando no hay horario factible, explica POR QUÉ
y sugiere ACCIONES concretas. NO relaja restricciones: solo reporta y guía al usuario.

Entrada: el ResultadoParcial de resolver_por_partes (con sus unidades bloqueadas).
Salida: un Diagnostico con, por cada unidad bloqueada, la causa y sugerencias accionables.

Dos capas de análisis:
  Capa 1 — Imposibilidad aislada (sin solver): secciones que NO pueden colocarse por sí
           solas (sin bloques válidos, días insuficientes, 2+1 sin par no solapante). Son
           los diagnósticos más precisos y accionables.
  Capa 2 — Restricción culpable (con solver, en aislamiento): se re-resuelve la unidad SOLA
           (sin las secciones ya colocadas). Si es factible en aislamiento, el bloqueo se
           debe a CONTENCIÓN con otros semestres (profesor/sala compartidos). Si es
           INFEASIBLE en aislamiento, se prueban combinaciones desactivando RD2/RD3/RD4
           —solo para diagnosticar, nunca se devuelve ese horario— para señalar qué
           restricción lo provoca.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .blocks import (
    BLOQUES_1H,
    BLOQUES_2H_SET,
    MATRIZ_SOLAPAMIENTO,
    TODOS_BLOQUES,
)
from .models import DatosProblema, TipoReunion
from .solver_cpsat import (
    ResultadoParcial,
    disponibilidad_seccion,
    resolver,
)

_TIEMPO_DIAG_S = 15.0  # límite por solve de diagnóstico (en aislamiento)


# ---------------------------------------------------------------------------
# Estructuras de salida
# ---------------------------------------------------------------------------

@dataclass
class Sugerencia:
    causa: str            # código: "sin_bloques" | "dias_insuficientes" | "2mas1_sin_par" |
                          #         "RD2" | "RD3" | "RD4" | "contencion" | "combinacion"
    severidad: str        # "alta" | "media"
    mensaje: str          # explicación legible para Francisca
    acciones: list[str] = field(default_factory=list)   # acciones concretas sugeridas
    secciones: list[str] = field(default_factory=list)  # ids involucrados
    profesores: list[str] = field(default_factory=list) # nombres/ruts
    bloques: list[str] = field(default_factory=list)     # ["Lunes 17:30-19:20", ...]


@dataclass
class DiagnosticoUnidad:
    carrera: str
    semestre: str
    causa_principal: str
    sugerencias: list[Sugerencia] = field(default_factory=list)


@dataclass
class Diagnostico:
    unidades: list[DiagnosticoUnidad] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers de presentación
# ---------------------------------------------------------------------------

_DIA_NOMBRE = {"L": "Lunes", "M": "Martes", "X": "Miércoles", "J": "Jueves", "V": "Viernes"}


def _bloque_nombre(b: int) -> str:
    blk = TODOS_BLOQUES[b]
    dia = _DIA_NOMBRE.get(blk.dia.value, blk.dia.value)
    helper = "" if blk.es_estandar else " (helper)"
    return f"{dia} {blk.hora_inicio}-{blk.hora_fin}{helper}"


def _prof_nombre(datos: DatosProblema, rut: str) -> str:
    p = datos.profesores.get(rut)
    if p and p.nombre:
        return p.nombre
    return rut or "(sin profesor)"


def _titulo(datos: DatosProblema, codigo: str) -> str:
    c = datos.cursos.get(codigo)
    return c.titulo if c and c.titulo else codigo


def _etiqueta_seccion(datos: DatosProblema, s) -> str:
    return f"{s.id} ({_titulo(datos, s.codigo_curso)})"


def _max_no_solapados(bloques: list[int]) -> int:
    """
    Máximo número de bloques mutuamente NO solapados dentro de un conjunto.
    Interval scheduling voraz (por hora de término) — exacto para grafos de intervalos.
    Es el máximo de sesiones no solapadas que una sección puede tener en su disponibilidad.
    """
    ordenados = sorted(bloques, key=lambda b: max(TODOS_BLOQUES[b].sub_bloques))
    elegidos: list[int] = []
    for b in ordenados:
        if all(not MATRIZ_SOLAPAMIENTO[b][c] for c in elegidos):
            elegidos.append(b)
    return len(elegidos)


# ---------------------------------------------------------------------------
# Capa 1 — Imposibilidad aislada (sin solver)
# ---------------------------------------------------------------------------

def detectar_imposibilidades(datos: DatosProblema, secciones: list) -> list[Sugerencia]:
    """
    Detecta secciones IMPOSIBLES por sí solas (independiente del resto del horario).
    Solo marca casos DEFINITIVAMENTE imposibles → mensajes 100% accionables.
    """
    sugerencias: list[Sugerencia] = []
    for s in secciones:
        dom = sorted(disponibilidad_seccion(datos, s))
        prof = _prof_nombre(datos, s.rut_profesor)
        etiqueta = _etiqueta_seccion(datos, s)

        # (a) Sin ningún bloque válido (duración / disponibilidad / AYUD ≥ 12:30)
        if not dom:
            sugerencias.append(Sugerencia(
                causa="sin_bloques",
                severidad="alta",
                mensaje=(
                    f"La sección {etiqueta} no tiene NINGÚN bloque válido: su duración "
                    f"({s.duracion_bloque}) no calza con ninguna franja donde el profesor "
                    f"{prof} esté disponible."
                ),
                acciones=[
                    f"Revisar la disponibilidad declarada del profesor {prof}.",
                    "Verificar que la distribución de horas del curso sea correcta.",
                ],
                secciones=[s.id],
                profesores=[prof],
            ))
            continue

        # (b) Sección 2+1: ¿existe un par (2h, 1h) que NO se solape?
        if s.tipos_bloques_necesarios == ["2h", "1h"]:
            dom_2h = [b for b in dom if b in BLOQUES_2H_SET]
            dom_1h = [b for b in dom if b in BLOQUES_1H]
            hay_par = any(
                not MATRIZ_SOLAPAMIENTO[b2][b1] for b2 in dom_2h for b1 in dom_1h
            )
            if not hay_par:
                sugerencias.append(Sugerencia(
                    causa="2mas1_sin_par",
                    severidad="alta",
                    mensaje=(
                        f"La sección {etiqueta} es de distribución 2+1 (un bloque de 2h y "
                        f"uno de 1h en horarios distintos), pero con la disponibilidad del "
                        f"profesor {prof} los únicos bloques de 2h y de 1h se solapan entre "
                        f"sí, así que no caben las dos sesiones."
                    ),
                    acciones=[
                        f"Ampliar la disponibilidad del profesor {prof} a otro día/franja.",
                        "Evaluar con el cliente cambiar la distribución a un único bloque de 2h.",
                    ],
                    secciones=[s.id],
                    profesores=[prof],
                    bloques=[_bloque_nombre(b) for b in dom],
                ))
            continue

        # (c) No caben las sesiones necesarias en días/horarios no solapados
        n_nec = s.cantidad_bloques_necesarios
        if n_nec > 1 and _max_no_solapados(dom) < n_nec:
            dias = sorted({TODOS_BLOQUES[b].dia.value for b in dom})
            sugerencias.append(Sugerencia(
                causa="dias_insuficientes",
                severidad="alta",
                mensaje=(
                    f"La sección {etiqueta} necesita {n_nec} bloques semanales en horarios "
                    f"que no se solapen, pero la disponibilidad del profesor {prof} solo "
                    f"permite ubicar {_max_no_solapados(dom)} "
                    f"(disponible en los días {', '.join(_DIA_NOMBRE.get(d, d) for d in dias)})."
                ),
                acciones=[
                    f"Consultar al profesor {prof} si puede agregar disponibilidad en otro día.",
                    f"Reasignar una parte de la carga de {etiqueta} a otro profesor.",
                ],
                secciones=[s.id],
                profesores=[prof],
                bloques=[_bloque_nombre(b) for b in dom],
            ))
    return sugerencias


# ---------------------------------------------------------------------------
# Capa 2 — Restricción culpable (con solver, en aislamiento)
# ---------------------------------------------------------------------------

def identificar_restriccion_culpable(
    datos: DatosProblema,
    secciones: list,
    carreras: list[str],
) -> tuple[bool, list[str]]:
    """
    Re-resuelve la unidad SOLA (sin fijadas de otras unidades).

    Retorna (factible_en_aislamiento, culpables):
      - factible_en_aislamiento=True → la unidad por sí sola sí cabe; el bloqueo real es
        contención de recursos con otros semestres (se maneja aparte).
      - culpables → lista de restricciones que, al desactivarse, vuelven factible la unidad
        (["RD2"], ["RD4"], ["RD2","RD4"], …). Vacía si ni desactivándolas de a una se logra.
    """
    def _factible(**kw) -> bool:
        r = resolver(datos, carreras=carreras, tiempo_limite_s=_TIEMPO_DIAG_S,
                     secciones=secciones, **kw)
        return r.estado in ("OPTIMAL", "FEASIBLE")

    if _factible():
        return True, []

    culpables: list[str] = []
    if _factible(usar_rd2=False):
        culpables.append("RD2")
    if _factible(usar_rd3=False):
        culpables.append("RD3")
    if _factible(usar_rd4=False):
        culpables.append("RD4")
    return False, culpables


def _detalle_contencion(datos, secs_unidad, asignaciones, sec_by_id):
    """Profesores y salas que la unidad comparte con secciones ya colocadas."""
    profs_unidad = {s.rut_profesor for s in secs_unidad
                    if s.afecta_disponibilidad and s.rut_profesor}
    salas_unidad = set()
    for s in secs_unidad:
        if s.componente != TipoReunion.AYUD:
            curso = datos.cursos.get(s.codigo_curso)
            if curso and curso.sala_especial:
                salas_unidad.add(curso.sala_especial)

    profs_comp: set[str] = set()
    salas_comp: set[str] = set()
    for sid in asignaciones:
        fs = sec_by_id.get(sid)
        if not fs:
            continue
        if fs.afecta_disponibilidad and fs.rut_profesor in profs_unidad:
            profs_comp.add(fs.rut_profesor)
        curso = datos.cursos.get(fs.codigo_curso)
        if curso and curso.sala_especial in salas_unidad:
            salas_comp.add(curso.sala_especial)
    return profs_comp, salas_comp


_LABEL_RD = {
    "RD2": "disponibilidad de los profesores",
    "RD3": "un mismo profesor asignado a secciones que deben coincidir en horario",
    "RD4": "capacidad de las salas especiales",
}
_ACCIONES_RD = {
    "RD2": [
        "Consultar a los profesores del semestre si pueden ampliar su disponibilidad.",
        "Reasignar alguna sección a un profesor con más disponibilidad.",
    ],
    "RD3": [
        "Reasignar una de las secciones en conflicto a otro profesor.",
    ],
    "RD4": [
        "Mover una sección a otro bloque/día para no saturar la sala especial.",
        "Evaluar habilitar una sala adicional del tipo requerido.",
    ],
}


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def diagnosticar(
    datos: DatosProblema,
    resultado: ResultadoParcial,
    carreras: list[str],
) -> Diagnostico:
    """Construye el diagnóstico completo a partir de las unidades bloqueadas."""
    sec_by_id = {s.id: s for s in datos.secciones}
    diag = Diagnostico()

    for unidad in resultado.bloqueadas:
        secs = [sec_by_id[sid] for sid in unidad.secciones if sid in sec_by_id]

        # Capa 1 — imposibilidades aisladas
        sugerencias = detectar_imposibilidades(datos, secs)
        if sugerencias:
            diag.unidades.append(DiagnosticoUnidad(
                carrera=unidad.carrera, semestre=unidad.semestre,
                causa_principal=sugerencias[0].causa, sugerencias=sugerencias,
            ))
            continue

        # Capa 2 — restricción culpable (aislamiento)
        factible_solo, culpables = identificar_restriccion_culpable(datos, secs, carreras)

        if factible_solo:
            profs_comp, salas_comp = _detalle_contencion(
                datos, secs, resultado.asignaciones, sec_by_id
            )
            partes = []
            acciones = []
            if profs_comp:
                nombres = [_prof_nombre(datos, r) for r in profs_comp]
                partes.append(f"profesores compartidos con otros semestres ({', '.join(nombres)})")
                acciones.append(
                    "Revisar la carga de esos profesores entre semestres; reasignar o "
                    "ampliar disponibilidad para liberar horario."
                )
            if salas_comp:
                partes.append(f"salas especiales compartidas ({', '.join(sorted(salas_comp))})")
                acciones.append(
                    "Redistribuir el uso de esas salas especiales entre semestres."
                )
            if not partes:
                partes.append("recursos compartidos con otros semestres")
                acciones.append("Revisar profesores y salas en común con el resto del horario.")

            sug = Sugerencia(
                causa="contencion",
                severidad="media",
                mensaje=(
                    f"El semestre {unidad.semestre} de {unidad.carrera} sí cabría por sí solo, "
                    f"pero choca con lo ya programado por {'; '.join(partes)}."
                ),
                acciones=acciones,
                secciones=[s.id for s in secs],
                profesores=[_prof_nombre(datos, r) for r in profs_comp],
            )
            diag.unidades.append(DiagnosticoUnidad(
                carrera=unidad.carrera, semestre=unidad.semestre,
                causa_principal="contencion", sugerencias=[sug],
            ))
            continue

        # Infeasible en aislamiento → señalar restricción(es) culpables
        if culpables:
            sugs = []
            for rd in culpables:
                sugs.append(Sugerencia(
                    causa=rd,
                    severidad="alta",
                    mensaje=(
                        f"En el semestre {unidad.semestre} de {unidad.carrera}, el conflicto "
                        f"proviene de {_LABEL_RD.get(rd, rd)}: al considerarla, no existe "
                        f"forma de ubicar todas las secciones sin choques."
                    ),
                    acciones=_ACCIONES_RD.get(rd, []),
                    secciones=[s.id for s in secs],
                ))
            causa_principal = culpables[0]
        else:
            sugs = [Sugerencia(
                causa="combinacion",
                severidad="alta",
                mensaje=(
                    f"En el semestre {unidad.semestre} de {unidad.carrera} no hay horario "
                    f"factible, y no se debe a una sola restricción: es la combinación de "
                    f"disponibilidad de profesores, unicidad de profesor y salas."
                ),
                acciones=[
                    "Revisar en conjunto disponibilidad de profesores y asignación de salas "
                    "de este semestre.",
                    "Considerar reasignar secciones a otros profesores.",
                ],
                secciones=[s.id for s in secs],
            )]
            causa_principal = "combinacion"

        diag.unidades.append(DiagnosticoUnidad(
            carrera=unidad.carrera, semestre=unidad.semestre,
            causa_principal=causa_principal, sugerencias=sugs,
        ))

    return diag