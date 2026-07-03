"""
solver_cpsat.py — Fase 1: restricciones duras via CP-SAT.

Modelo a NIVEL DE SECCIÓN. Cada sección tiene su(s) variable(s) de bloque, con dominio
= sus bloques disponibles. El solver decide el paralelismo por sí mismo: para que todos
los ramos de un semestre quepan sin topes (RD1 estricto entre cursos distintos), pone en
paralelo las secciones de un mismo curso donde la disponibilidad lo permite. No se
pre-agrupan secciones.

Restricciones duras (ver README.md §2 para el detalle completo):

  RD2 — Disponibilidad de profesor:
    Cada sección solo puede usar bloques donde su profesor está disponible. Implementada
    como el DOMINIO de la variable (disponibilidad_seccion). JORNADA = grilla estándar
    completa; HONORARIO = bloques declarados en el formulario. AYUD = grilla estándar
    desde 12:30 (la dicta un TA).

  Intra-sección — los bloques de una misma sección no se solapan entre sí.

  NRC — dentro de una misma sección (CLAS-k/AYUD-k/LABT-k) los componentes no se solapan
    (el alumno asiste a los tres).

  RD1 — Sin topes de malla:
    Secciones de cursos DISTINTOS del mismo (carrera, semestre) no se solapan. Las del
    MISMO curso quedan exentas (pueden ir en paralelo).

  RD3 — Unicidad de profesor:
    Un profesor con afecta_disponibilidad=True no dicta dos secciones a la vez, en
    cualquier rol/curso (el profesor de laboratorio se trata aparte del de cátedra).

  RD4 — Capacidad de salas especiales:
    En cada sub-bloque, las secciones que usan un mismo tipo de sala no superan las salas
    físicas. Capacidad 1 → pares no se solapan; capacidad N → a lo más N en paralelo.

  RD7 — Ayudantías desde 12:30: garantizado por el dominio de las secciones AYUD.

Objetivo: minimizar el uso de bloques helper (preferir la grilla institucional estándar).

Solapamiento: verificado por sub-bloques (MATRIZ_SOLAPAMIENTO), NO por igualdad de índice.

Sin relajación automática: el modelo se resuelve SIEMPRE con todas las restricciones duras.
Si CP-SAT retorna INFEASIBLE, NO se relaja nada — la causa se diagnostica aparte
(app/core/diagnostico.py) y se guía al usuario a resolverla. Los parámetros usar_rd2/
usar_rd3/usar_rd4 existen solo para que el módulo de diagnóstico pueda aislar, mediante
pruebas internas que nunca se devuelven al usuario, qué restricción provoca el conflicto.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .blocks import (
    BLOQUES_HELPER,
    BLOQUES_1H,
    BLOQUES_2H_SET,
    BLOQUES_3H_SET,
    MATRIZ_SOLAPAMIENTO,
    N_BLOQUES,
    SET_ESTANDAR,
    TODOS_BLOQUES,
)

from .models import DatosProblema, TipoReunion


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoSolver:
    asignaciones: dict[str, list[int]] = field(default_factory=dict)  # sec_id → [bloque_idx, ...]
    estado: str = "UNKNOWN"
    # Conteos de restricciones agregadas al modelo (para diagnóstico).
    n_rd1: int = 0
    n_rd2: int = 0   # RD2 va en el dominio de cada variable, no como restricción aparte → 0
    n_rc: int = 0    # NRC: componentes de la misma sección que no se solapan
    n_intra: int = 0
    n_rd3: int = 0
    n_rd4: int = 0
    n_rd7: int = 0   # RD7 va en el dominio de las AYUD → 0
    n_rd8: int = 0   # no usado en el modelo actual


@dataclass
class UnidadBloqueada:
    """Una unidad (carrera, semestre) que no se pudo colocar en la resolución por partes."""
    carrera: str
    semestre: str
    secciones: list[str] = field(default_factory=list)  # ids de secciones no colocadas


@dataclass
class ResultadoParcial:
    """
    Resultado de resolver_por_partes.

    estado:
      FACTIBLE   — el modelo completo se resolvió con todas las restricciones duras.
      PARCIAL    — el modelo completo era INFEASIBLE; se colocó el subconjunto de unidades
                   factibles (respetando TODAS las duras entre ellas) y quedaron unidades
                   bloqueadas para diagnosticar.
      INFEASIBLE — no se pudo colocar ninguna unidad.
    """
    estado: str = "UNKNOWN"
    asignaciones: dict[str, list[int]] = field(default_factory=dict)  # solo lo colocado
    bloqueadas: list[UnidadBloqueada] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Precómputo
# ---------------------------------------------------------------------------

_PARES_SOLAPAN: list[tuple[int, int]] = [
    (i, j)
    for i in range(N_BLOQUES)
    for j in range(N_BLOQUES)
    if MATRIZ_SOLAPAMIENTO[i][j]
]

# Cobertura por sub-bloque: (dia, minuto_inicio_subbloque) → índices de bloque que lo cubren.
_COBERTURA_SUBBLOQUE: dict[tuple[str, int], list[int]] = defaultdict(list)
for _i, _b in enumerate(TODOS_BLOQUES):
    for _sub in _b.sub_bloques:
        _COBERTURA_SUBBLOQUE[(_b.dia.value, _sub)].append(_i)


def _hora_a_min(hora: str) -> int:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


_MIN_12_30 = 12 * 60 + 30

_BLOQUES_PROHIBIDOS_AYUD: list[int] = [
    i for i, b in enumerate(TODOS_BLOQUES)
    if _hora_a_min(b.hora_inicio) < _MIN_12_30
]

# ── Horarios protegidos para minors (RD8) ───────────────────────────────────
# Los alumnos de semestres 3, 4 y 5 toman minors en ventanas protegidas; ningún curso de
# ingeniería de esos semestres puede ocupar un bloque que toque estas franjas de 50 min.
SEMESTRES_PROTEGIDOS_MINOR: set[str] = {"3", "4", "5"}

# (día → minutos de inicio de las franjas de 50 min protegidas)
_MINOR_SUBS_POR_DIA: dict[str, set[int]] = {
    "M": {17 * 60 + 30, 18 * 60 + 30},   # Martes 17:30-18:20 y 18:30-19:20
    "X": {17 * 60 + 30, 18 * 60 + 30},   # Miércoles 17:30-18:20 y 18:30-19:20
    "V": {10 * 60 + 30, 11 * 60 + 30},   # Viernes 10:30-11:20 y 11:30-12:20
}

# Un bloque está protegido si toca (comparte una franja de 50 min con) una ventana de minor.
BLOQUES_PROTEGIDOS_MINOR: set[int] = {
    i for i, b in enumerate(TODOS_BLOQUES)
    if b.sub_bloques & _MINOR_SUBS_POR_DIA.get(b.dia.value, set())
}


def seccion_en_semestre_protegido(datos: DatosProblema, s) -> bool:
    """True si el curso de la sección pertenece a semestre 3, 4 o 5 en alguna carrera."""
    curso = datos.cursos.get(s.codigo_curso)
    if not curso:
        return False
    return any(
        sems & SEMESTRES_PROTEGIDOS_MINOR
        for sems in curso.semestres_por_carrera.values()
    )


# ---------------------------------------------------------------------------
# Disponibilidad de sección
# ---------------------------------------------------------------------------

def disponibilidad_seccion(
    datos: DatosProblema, s, usar_rd2: bool = True
) -> set[int]:
    """
    Bloques en que una sección PUEDE dictarse:
      - DURACIÓN: solo bloques cuyo tipo (2h/3h) coincide con duracion_bloque de la
        sección. Una clase de 2h no puede ir en un bloque de 3h ni viceversa (RD6).
      - AYUD → solo desde 12:30 (RD7)
      - con disponibilidad declarada → bloques del profesor (estándar + helper)
      - sin disponibilidad → todos los bloques de su duración. La preferencia por la
        grilla estándar NO se fuerza aquí (sería demasiado rígido para los cursos de 3h,
        que solo tienen 2 bloques estándar): se maneja de forma blanda con el objetivo
        de minimizar bloques helper (CP-SAT) y la penalización PESO_BLOQUE_HELPER (GA).
    """
    es_ayud = s.componente == TipoReunion.AYUD
    tipos = getattr(s, "tipos_bloques_necesarios", [])
    dur = getattr(s, "duracion_bloque", "2h")
    if tipos:
        # Sección 2+1: incluir bloques de todos los tipos necesarios
        tipos_validos = set(tipos)
        base = {b for b in range(N_BLOQUES)
                if TODOS_BLOQUES[b].tipo in tipos_validos
                and (not es_ayud or b not in _BLOQUES_PROHIBIDOS_AYUD)}
    else:
        base = {b for b in range(N_BLOQUES)
                if TODOS_BLOQUES[b].tipo == dur
                and (not es_ayud or b not in _BLOQUES_PROHIBIDOS_AYUD)}
                
    # RD2: la sección debe caber en la disponibilidad de TODOS sus profesores que afectan
    # (profesor 1 y, si existe, profesor 2 co-dictante). JORNADA = disponibilidad vacía =
    # sin restricción. Se intersecta con cada profesor con disponibilidad declarada.
    if usar_rd2 and s.afecta_disponibilidad:
        for rut in (s.rut_profesor, getattr(s, "rut_profesor_2", "")):
            if not rut:
                continue
            prof = datos.profesores.get(rut)
            if prof and prof.disponibilidad:
                base = {b for b in base if b in prof.disponibilidad}

    # RD8: horarios protegidos para minors. Cursos de semestre 3/4/5 no pueden ocupar los
    # bloques que tocan las ventanas de minor (Ma/Mi 17:30-19:20, Vi 10:30-12:20).
    if seccion_en_semestre_protegido(datos, s):
        base = {b for b in base if b not in BLOQUES_PROTEGIDOS_MINOR}

    return base


# ---------------------------------------------------------------------------
# Función principal del solver
# ---------------------------------------------------------------------------

def resolver(
    datos: DatosProblema,
    carreras: list[str] | None = None,
    tiempo_limite_s: float = 60.0,
    usar_rd2: bool = True,
    usar_rd3: bool = True,
    usar_rd4: bool = True,
    secciones: list | None = None,
    fijadas: dict[str, list[int]] | None = None,
) -> ResultadoSolver:
    """
    Asigna bloques a nivel de SECCIÓN.

    Restricciones duras activas según parámetros:
      RD2  — disponibilidad del profesor (o grilla estándar si no hay datos).
             AYUD solo desde 12:30 (RD7, siempre activo).
      intra — los bloques de una sección no se solapan entre sí (siempre activo).
      NRC  — componentes de la misma sección no se solapan (siempre activo).
      RD1  — secciones de cursos DISTINTOS del mismo (carrera, semestre) no se solapan
             (siempre activo).
      RD3  — un profesor no dicta dos secciones a la vez. Controlado por usar_rd3.
      RD4  — capacidad de salas especiales. Controlado por usar_rd4.

    Parámetros para resolución incremental (usados por resolver_por_partes):
      secciones — conjunto explícito de secciones a modelar. Si es None, se derivan de
                  `carreras` (comportamiento por defecto, idéntico al histórico).
      fijadas   — {sec_id: [bloques]} de secciones ya colocadas en unidades previas. Se
                  incluyen en el modelo con dominio fijo (pinneadas) para que las secciones
                  activas respeten RD1/RD3/RD4 contra ellas. NO se devuelven en el resultado.

    Objetivo: minimizar bloques helper (preferir la grilla estándar).
    """
    if carreras is None:
        carreras = ["Plan Común"]

    fijadas = fijadas or {}

    model = cp_model.CpModel()

    if secciones is None:
        codigos_restringidos = {
            c.codigo
            for c in datos.cursos.values()
            if any(car in c.semestres_por_carrera for car in carreras)
        }
        secciones = [s for s in datos.secciones if s.codigo_curso in codigos_restringidos]

    fijas_ids = set(fijadas)

    # Variables por sección (dominio = disponibilidad; las fijadas van pinneadas).
    dom_de: dict[str, list[int]] = {}
    x: dict[str, list[cp_model.IntVar]] = {}
    for s in secciones:
        if s.id in fijas_ids:
            # Sección ya colocada: variables con dominio de un solo valor (constante).
            bloques_fijos = fijadas[s.id]
            dom_de[s.id] = list(bloques_fijos)
            x[s.id] = [
                model.NewIntVarFromDomain(cp_model.Domain.FromValues([b]), f"{s.id}_fix{k}")
                for k, b in enumerate(bloques_fijos)
            ]
            continue

        dom_base = sorted(disponibilidad_seccion(datos, s, usar_rd2))
        if not dom_base:
            return ResultadoSolver(estado="INFEASIBLE")
        dom_de[s.id] = dom_base

        tipos = s.tipos_bloques_necesarios  # [] o ["2h","1h"]
        vars_seccion = []
        for k in range(s.cantidad_bloques_necesarios):
            if tipos and k < len(tipos):
                filtro = {"1h": BLOQUES_1H, "2h": BLOQUES_2H_SET, "3h": BLOQUES_3H_SET}.get(tipos[k])
                dom_k = sorted(b for b in dom_base if filtro is None or b in filtro)
            else:
                # sin tipo específico: excluir bloques de 1h (no aplican a clases normales)
                dom_k = sorted(b for b in dom_base if b not in BLOQUES_1H)
            if not dom_k:
                return ResultadoSolver(estado="INFEASIBLE")
            vars_seccion.append(
                model.NewIntVarFromDomain(cp_model.Domain.FromValues(dom_k), f"{s.id}_b{k}")
            )
        x[s.id] = vars_seccion

    def _nover(a_id, b_id) -> int:
        # No genera restricciones entre dos secciones ya fijadas (redundante).
        if a_id in fijas_ids and b_id in fijas_ids:
            return 0
        c = 0
        for v1 in x[a_id]:
            for v2 in x[b_id]:
                model.AddForbiddenAssignments([v1, v2], _PARES_SOLAPAN)
                c += 1
        return c

    # Intra-sección (siempre activo; innecesario para las pinneadas)
    n_intra = 0
    for s in secciones:
        if s.id in fijas_ids:
            continue
        v = x[s.id]
        for k1 in range(len(v)):
            for k2 in range(k1 + 1, len(v)):
                model.AddForbiddenAssignments([v[k1], v[k2]], _PARES_SOLAPAN)
                n_intra += 1

    # NRC: componentes distintos de la misma sección no se solapan (siempre activo)
    n_rc = 0
    por_nrc: dict[tuple, list] = defaultdict(list)
    for s in secciones:
        por_nrc[(s.codigo_curso, str(s.seccion))].append(s)
    for grp in por_nrc.values():
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                if grp[i].componente != grp[j].componente:
                    n_rc += _nover(grp[i].id, grp[j].id)

    # RD1: cursos DISTINTOS del mismo (carrera, semestre) no se solapan (siempre activo)
    n_rd1 = 0
    vistos_rd1: set[frozenset] = set()
    for carrera in carreras:
        por_sem: dict[str, list] = defaultdict(list)
        for s in secciones:
            curso = datos.cursos.get(s.codigo_curso)
            if not curso:
                continue
            for sem in curso.semestres_por_carrera.get(carrera, set()):
                por_sem[sem].append(s)
        for grp in por_sem.values():
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    if grp[i].codigo_curso == grp[j].codigo_curso:
                        continue
                    par = frozenset((grp[i].id, grp[j].id))
                    if par in vistos_rd1:
                        continue
                    vistos_rd1.add(par)
                    n_rd1 += _nover(grp[i].id, grp[j].id)

    # RD3: un profesor no dicta dos secciones a la vez (incluye al profesor 2 co-dictante).
    n_rd3 = 0
    if usar_rd3:
        por_prof: dict[str, list] = defaultdict(list)
        for s in secciones:
            if not s.afecta_disponibilidad:
                continue
            for rut in (s.rut_profesor, s.rut_profesor_2):
                if rut:
                    por_prof[rut].append(s)
        vistos_rd3: set[frozenset] = set()  # un mismo par puede compartir dos profesores
        for grp in por_prof.values():
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    if grp[i].id == grp[j].id:
                        continue
                    par = frozenset((grp[i].id, grp[j].id))
                    if par in vistos_rd3:
                        continue
                    vistos_rd3.add(par)
                    n_rd3 += _nover(grp[i].id, grp[j].id)

    # RD4: capacidad de salas especiales
    n_rd4 = 0
    if usar_rd4:
        por_sala: dict[str, list] = defaultdict(list)
        for s in secciones:
            if s.componente == TipoReunion.AYUD:
                continue
            curso = datos.cursos.get(s.codigo_curso)
            if curso and curso.sala_especial:
                por_sala[curso.sala_especial].append(s)
        for sala, ss in por_sala.items():
            cap = datos.capacidad_por_sala.get(sala)
            if cap is None:
                cap = 1
            if cap == 1:
                for i in range(len(ss)):
                    for j in range(i + 1, len(ss)):
                        n_rd4 += _nover(ss[i].id, ss[j].id)
            else:
                # Las secciones fijadas cuentan para la capacidad (indicador pinneado).
                for (dia, sub), blks in _COBERTURA_SUBBLOQUE.items():
                    blkset = set(blks)
                    inds = []
                    for s in ss:
                        bvars = [bb for bb in dom_de[s.id] if bb in blkset]
                        if not bvars:
                            continue
                        for var in x[s.id]:
                            bi = model.NewBoolVar(f"rd4_{dia}_{sub}_{s.id}_{len(inds)}")
                            model.AddAllowedAssignments([var], [[bb] for bb in bvars]).OnlyEnforceIf(bi)
                            model.AddForbiddenAssignments([var], [[bb] for bb in bvars]).OnlyEnforceIf(bi.Not())
                            inds.append(bi)
                    if len(inds) > cap:
                        model.Add(sum(inds) <= cap)
                        n_rd4 += 1

    n_rd7 = 0
    n_rd8 = 0

    # Preferencia por la grilla estándar: minimizar uso de bloques helper (solo activas).
    helper_indicators = []
    for s in secciones:
        if s.id in fijas_ids:
            continue
        helpers_dom = [h for h in BLOQUES_HELPER if h in dom_de[s.id]]
        if not helpers_dom:
            continue
        for k, var in enumerate(x[s.id]):
            uh = model.NewBoolVar(f"helper_{s.id}_{k}")
            model.AddAllowedAssignments([var], [[h] for h in helpers_dom]).OnlyEnforceIf(uh)
            model.AddForbiddenAssignments([var], [[h] for h in helpers_dom]).OnlyEnforceIf(uh.Not())
            helper_indicators.append(uh)
    if helper_indicators:
        model.Minimize(sum(helper_indicators))

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_limite_s
    status_code = solver.Solve(model)

    _STATUS = {
        cp_model.OPTIMAL:    "OPTIMAL",
        cp_model.FEASIBLE:   "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN:    "UNKNOWN",
    }
    estado = _STATUS.get(status_code, "UNKNOWN")

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ResultadoSolver(
            estado=estado,
            n_rd1=n_rd1, n_rd2=0, n_rc=n_rc, n_intra=n_intra,
            n_rd3=n_rd3, n_rd4=n_rd4, n_rd7=n_rd7, n_rd8=n_rd8,
        )

    # Se devuelven solo las secciones activas (no las fijadas, ya conocidas).
    asignaciones = {
        sec_id: [solver.Value(v) for v in vars_]
        for sec_id, vars_ in x.items()
        if sec_id not in fijas_ids
    }

    return ResultadoSolver(
        asignaciones=asignaciones,
        estado=estado,
        n_rd1=n_rd1, n_rd2=0, n_rc=n_rc, n_intra=n_intra,
        n_rd3=n_rd3, n_rd4=n_rd4, n_rd7=n_rd7, n_rd8=n_rd8,
    )


# ---------------------------------------------------------------------------
# Resolución por partes (horario parcial) — función principal desde routes.py
# ---------------------------------------------------------------------------

def _sem_key(sem: str) -> tuple:
    """Clave de orden para semestres tipo '1'..'12', '9a', '9f' (por nº y luego sufijo)."""
    num = ""
    for ch in str(sem):
        if ch.isdigit():
            num += ch
        else:
            break
    return (int(num) if num else 999, str(sem))


def _construir_unidades(datos: DatosProblema, secciones: list, carreras: list[str]) -> dict:
    """
    Agrupa secciones en unidades (carrera, semestre) — la granularidad más fina que
    preserva RD1. Una sección puede caer en varias unidades (curso presente en varias
    carreras/semestres); resolver_por_partes la coloca en la primera y la fija en las demás.
    """
    unidades: dict[tuple[str, str], list] = defaultdict(list)
    for s in secciones:
        curso = datos.cursos.get(s.codigo_curso)
        if not curso:
            continue
        for carrera in carreras:
            for sem in curso.semestres_por_carrera.get(carrera, set()):
                unidades[(carrera, sem)].append(s)
    return unidades


def _cohortes(datos, s) -> set:
    """Cohortes (carrera, semestre) a las que pertenece la sección (para RD1)."""
    curso = datos.cursos.get(s.codigo_curso)
    if not curso:
        return set()
    return {(c, se) for c, sems in curso.semestres_por_carrera.items() for se in sems}


def _fijas_relevantes(datos, activas, asignaciones, sec_by_id) -> set:
    """
    Secciones ya colocadas que interactúan con las activas por una restricción dura que
    cruza unidades: RD3 (profesor compartido, incluye prof 2), RD4 (misma sala especial) o
    RD1 (comparten cohorte carrera+semestre). Se decide por **partnership real** entre las
    secciones (no por la clave de la unidad actual): así, una sección que pertenece a varias
    unidades queda correctamente restringida contra todas sus partners ya colocadas, aunque
    su restricción compartida "viva" en otra unidad.
    """
    profs_act: set[str] = set()
    salas_act: set = set()
    cohortes_act: set = set()
    for s in activas:
        if s.afecta_disponibilidad:
            for rut in (s.rut_profesor, s.rut_profesor_2):
                if rut:
                    profs_act.add(rut)
        if s.componente != TipoReunion.AYUD:
            curso = datos.cursos.get(s.codigo_curso)
            if curso and curso.sala_especial:
                salas_act.add(curso.sala_especial)
        cohortes_act |= _cohortes(datos, s)

    rel: set[str] = set()
    for sid in asignaciones:
        fs = sec_by_id.get(sid)
        if not fs:
            continue
        curso = datos.cursos.get(fs.codigo_curso)
        # RD3: profesor compartido (prof 1 o prof 2)
        if fs.afecta_disponibilidad and (
            fs.rut_profesor in profs_act or (fs.rut_profesor_2 and fs.rut_profesor_2 in profs_act)
        ):
            rel.add(sid)
            continue
        # RD4: misma sala especial
        if fs.componente != TipoReunion.AYUD and curso and curso.sala_especial in salas_act:
            rel.add(sid)
            continue
        # RD1: comparte alguna cohorte (carrera, semestre) con alguna activa
        if _cohortes(datos, fs) & cohortes_act:
            rel.add(sid)
    return rel


def resolver_por_partes(
    datos: DatosProblema,
    carreras: list[str] | None = None,
    tiempo_limite_s: float = 60.0,
    tiempo_por_unidad_s: float | None = None,
) -> ResultadoParcial:
    """
    Genera el mejor horario posible SIN relajar restricciones duras.

      1. Intenta el modelo COMPLETO. Si es factible → FACTIBLE (horario total).
      2. Si es INFEASIBLE, descompone en unidades (carrera, semestre) y las resuelve
         incrementalmente: cada unidad respeta como FIJAS las secciones ya colocadas
         (RD1/RD3/RD4 contra ellas). Las unidades que no entran se marcan bloqueadas.
         El horario resultante (parcial) respeta TODAS las restricciones duras entre
         las secciones colocadas — no se inventa ni se relaja nada.

    Las unidades bloqueadas son el input del diagnóstico (Fase 2).
    """
    if carreras is None:
        carreras = ["Plan Común"]

    # 1. Intento completo
    full = resolver(datos, carreras=carreras, tiempo_limite_s=tiempo_limite_s)
    if full.estado in ("OPTIMAL", "FEASIBLE"):
        return ResultadoParcial(estado="FACTIBLE", asignaciones=full.asignaciones)

    # 2. Descomposición por unidad (carrera, semestre)
    codigos = {
        c.codigo for c in datos.cursos.values()
        if any(car in c.semestres_por_carrera for car in carreras)
    }
    todas = [s for s in datos.secciones if s.codigo_curso in codigos]
    sec_by_id = {s.id: s for s in todas}
    unidades = _construir_unidades(datos, todas, carreras)

    claves = sorted(
        unidades,
        key=lambda k: (0 if k[0] == "Plan Común" else 1, k[0], _sem_key(k[1])),
    )
    if tiempo_por_unidad_s is None:
        tiempo_por_unidad_s = max(10.0, tiempo_limite_s / max(1, len(claves)))

    asignaciones: dict[str, list[int]] = {}
    bloqueadas: list[UnidadBloqueada] = []

    for carrera, sem in claves:
        activas = [s for s in unidades[(carrera, sem)] if s.id not in asignaciones]
        if not activas:
            continue  # ya colocadas en unidades previas (curso compartido)

        fijas_rel = _fijas_relevantes(datos, activas, asignaciones, sec_by_id)
        r = resolver(
            datos,
            carreras=carreras,
            tiempo_limite_s=tiempo_por_unidad_s,
            secciones=activas + [sec_by_id[sid] for sid in fijas_rel],
            fijadas={sid: asignaciones[sid] for sid in fijas_rel},
        )
        if r.estado in ("OPTIMAL", "FEASIBLE"):
            asignaciones.update(r.asignaciones)
        else:
            bloqueadas.append(
                UnidadBloqueada(carrera=carrera, semestre=sem,
                                secciones=[s.id for s in activas])
            )

    if not asignaciones:
        return ResultadoParcial(estado="INFEASIBLE", bloqueadas=bloqueadas)
    estado = "FACTIBLE" if not bloqueadas else "PARCIAL"
    return ResultadoParcial(estado=estado, asignaciones=asignaciones, bloqueadas=bloqueadas)


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------

def verificar_topes(
    datos: DatosProblema,
    asignaciones: dict[str, list[int]],
    carrera: str,
) -> list[tuple[str, str, str]]:
    """Retorna (sec1_id, sec2_id, semestre) de cada tope RD1 en la solución."""
    sec_by_id = {s.id: s for s in datos.secciones}

    grupos: dict[str, list[str]] = defaultdict(list)
    for sec_id in asignaciones:
        s = sec_by_id.get(sec_id)
        if not s:
            continue
        curso = datos.cursos.get(s.codigo_curso)
        if not curso:
            continue
        for sem in curso.semestres_por_carrera.get(carrera, set()):
            grupos[sem].append(sec_id)

    topes = []
    for sem, ids in grupos.items():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id1, id2 = ids[i], ids[j]
                s1, s2 = sec_by_id[id1], sec_by_id[id2]
                if s1.codigo_curso == s2.codigo_curso:
                    continue
                if any(MATRIZ_SOLAPAMIENTO[b1][b2]
                       for b1 in asignaciones[id1]
                       for b2 in asignaciones[id2]):
                    topes.append((id1, id2, sem))

    return topes


def verificar_intra(
    asignaciones: dict[str, list[int]],
) -> list[tuple[str, int, int]]:
    """Retorna (sec_id, bloque_a, bloque_b) de cada solapamiento intra-sección."""
    violaciones = []
    for sec_id, bloques in asignaciones.items():
        for k1 in range(len(bloques)):
            for k2 in range(k1 + 1, len(bloques)):
                if MATRIZ_SOLAPAMIENTO[bloques[k1]][bloques[k2]]:
                    violaciones.append((sec_id, bloques[k1], bloques[k2]))
    return violaciones


def verificar_rd3(
    datos: DatosProblema,
    asignaciones: dict[str, list[int]],
) -> list[tuple[str, str]]:
    """Retorna (sec1_id, sec2_id) de conflictos de profesor entre CURSOS DISTINTOS."""
    sec_by_id = {s.id: s for s in datos.secciones}
    por_prof: dict[str, list[str]] = defaultdict(list)
    for sec_id in asignaciones:
        s = sec_by_id.get(sec_id)
        if s and s.afecta_disponibilidad:
            por_prof[s.rut_profesor].append(sec_id)

    conflictos = []
    for ids in por_prof.values():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id1, id2 = ids[i], ids[j]
                s1, s2 = sec_by_id[id1], sec_by_id[id2]
                if s1.codigo_curso == s2.codigo_curso:
                    continue
                if any(MATRIZ_SOLAPAMIENTO[b1][b2]
                       for b1 in asignaciones[id1]
                       for b2 in asignaciones[id2]):
                    conflictos.append((id1, id2))
    return conflictos


def verificar_rd4(
    datos: DatosProblema,
    asignaciones: dict[str, list[int]],
) -> list[tuple[str, str, str]]:
    """
    Retorna (sec1_id, sec2_id, sala) de violaciones de sala especial.
    """
    sec_by_id = {s.id: s for s in datos.secciones}
    por_sala: dict[str, list[str]] = defaultdict(list)
    for sec_id in asignaciones:
        s = sec_by_id.get(sec_id)
        if not s or s.componente == TipoReunion.AYUD:
            continue
        curso = datos.cursos.get(s.codigo_curso)
        if curso and curso.sala_especial:
            por_sala[curso.sala_especial].append(sec_id)

    cap = datos.capacidad_por_sala
    conflictos = []

    for sala, ids in por_sala.items():
        capacidad = cap.get(sala)
        if capacidad is None:
            capacidad = 1

        if capacidad == 1:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    id1, id2 = ids[i], ids[j]
                    if any(MATRIZ_SOLAPAMIENTO[b1][b2]
                           for b1 in asignaciones[id1]
                           for b2 in asignaciones[id2]):
                        conflictos.append((id1, id2, sala))
        else:
            from collections import Counter
            bloque_count: Counter = Counter()
            bloque_secs: dict[int, list[str]] = defaultdict(list)
            for sec_id in ids:
                for b in asignaciones[sec_id]:
                    bloque_count[b] += 1
                    bloque_secs[b].append(sec_id)

            for bloque, count in bloque_count.items():
                if count > capacidad:
                    secs_en_bloque = bloque_secs[bloque]
                    for i in range(len(secs_en_bloque)):
                        for j in range(i + 1, len(secs_en_bloque)):
                            conflictos.append((secs_en_bloque[i], secs_en_bloque[j], sala))

    return conflictos


def verificar_rd7(
    datos: DatosProblema,
    asignaciones: dict[str, list[int]],
) -> list[tuple[str, int]]:
    """Retorna (sec_id, bloque_idx) de cada AYUD asignado antes de las 12:30."""
    sec_by_id = {s.id: s for s in datos.secciones}
    violaciones = []
    for sec_id, bloques in asignaciones.items():
        s = sec_by_id.get(sec_id)
        if not s or s.componente != TipoReunion.AYUD:
            continue
        for b in bloques:
            if _hora_a_min(TODOS_BLOQUES[b].hora_inicio) < _MIN_12_30:
                violaciones.append((sec_id, b))
    return violaciones


def verificar_minor(
    datos: DatosProblema,
    asignaciones: dict[str, list[int]],
) -> list[tuple[str, int]]:
    """Retorna (sec_id, bloque_idx) de cursos de sem 3/4/5 en un horario protegido de minor."""
    sec_by_id = {s.id: s for s in datos.secciones}
    violaciones = []
    for sec_id, bloques in asignaciones.items():
        s = sec_by_id.get(sec_id)
        if not s or not seccion_en_semestre_protegido(datos, s):
            continue
        for b in bloques:
            if b in BLOQUES_PROTEGIDOS_MINOR:
                violaciones.append((sec_id, b))
    return violaciones


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def imprimir_resultado(datos: DatosProblema, resultado: ResultadoSolver) -> None:
    print("=" * 60)
    print("RESULTADO CP-SAT")
    print("=" * 60)
    print(f"Estado:               {resultado.estado}")
    print(f"Secciones asignadas:  {len(resultado.asignaciones)}")
    total_bloques = sum(len(b) for b in resultado.asignaciones.values())
    print(f"Bloques totales:      {total_bloques}")
    print(f"Restricciones RD1:    {resultado.n_rd1}")
    print(f"Restricciones NRC:    {resultado.n_rc}")
    print(f"Restricciones intra:  {resultado.n_intra}")
    print(f"Restricciones RD3:    {resultado.n_rd3}")
    print(f"Restricciones RD4:    {resultado.n_rd4}")

    if not resultado.asignaciones:
        return

    n_helper = sum(
        1 for bloques in resultado.asignaciones.values()
        for b in bloques if not TODOS_BLOQUES[b].es_estandar
    )
    total_bloques = sum(len(b) for b in resultado.asignaciones.values())
    print(f"Bloques helper usados: {n_helper}/{total_bloques} "
          f"(el resto en grilla estándar)")

    conteo: dict[int, int] = defaultdict(int)
    for bloques in resultado.asignaciones.values():
        for idx in bloques:
            conteo[idx] += 1

    print("\nDistribución por bloque:")
    for bloque_idx in sorted(conteo):
        b = TODOS_BLOQUES[bloque_idx]
        print(f"  {b.dia.value} {b.hora_inicio}-{b.hora_fin} ({b.tipo}): "
              f"{conteo[bloque_idx]} asignación(es)")