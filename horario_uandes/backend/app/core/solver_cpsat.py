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

Fallback: si CP-SAT retorna INFEASIBLE, resolver_con_fallback() relaja restricciones
progresivamente hasta encontrar alguna solución parcial que pueda pasar al GA y al
reporter (las violaciones se documentan en el reporte final).
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
    # Campos de fallback: indican si se relajaron restricciones para obtener la solución.
    nivel_relajacion: int = 0        # 0 = solución completa; >0 = restricciones relajadas
    advertencia_relajacion: str = "" # mensaje para mostrar en el frontend


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
                
    prof = datos.profesores.get(s.rut_profesor) if s.rut_profesor else None
    tiene = usar_rd2 and s.afecta_disponibilidad and prof is not None and bool(prof.disponibilidad)
    if tiene:
        return {b for b in base if b in prof.disponibilidad}
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
    _forzar_rd1: bool = True,
) -> ResultadoSolver:
    """
    Asigna bloques a nivel de SECCIÓN.

    Restricciones duras activas según parámetros:
      RD2  — disponibilidad del profesor (o grilla estándar si no hay datos).
             AYUD solo desde 12:30 (RD7, siempre activo).
      intra — los bloques de una sección no se solapan entre sí (siempre activo).
      NRC  — componentes de la misma sección no se solapan (siempre activo).
      RD1  — secciones de cursos DISTINTOS del mismo (carrera, semestre) no se solapan.
             Controlado por _forzar_rd1 (True por defecto; False solo en último fallback).
      RD3  — un profesor no dicta dos secciones a la vez. Controlado por usar_rd3.
      RD4  — capacidad de salas especiales. Controlado por usar_rd4.

    Objetivo: minimizar bloques helper (preferir la grilla estándar).
    """
    if carreras is None:
        carreras = ["Plan Común"]

    model = cp_model.CpModel()

    codigos_restringidos = {
        c.codigo
        for c in datos.cursos.values()
        if any(car in c.semestres_por_carrera for car in carreras)
    }
    secciones = [s for s in datos.secciones if s.codigo_curso in codigos_restringidos]

    # Variables por sección (dominio = disponibilidad de la sección)
    dom_de: dict[str, list[int]] = {}
    x: dict[str, list[cp_model.IntVar]] = {}
    for s in secciones:
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

    def _nover(a_vars, b_vars) -> int:
        c = 0
        for v1 in a_vars:
            for v2 in b_vars:
                model.AddForbiddenAssignments([v1, v2], _PARES_SOLAPAN)
                c += 1
        return c

    # Intra-sección (siempre activo)
    n_intra = 0
    for s in secciones:
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
                    n_rc += _nover(x[grp[i].id], x[grp[j].id])

    # RD1: cursos DISTINTOS del mismo (carrera, semestre) no se solapan
    n_rd1 = 0
    if _forzar_rd1:
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
                        n_rd1 += _nover(x[grp[i].id], x[grp[j].id])

    # RD3: un profesor no dicta dos secciones a la vez
    n_rd3 = 0
    if usar_rd3:
        por_prof: dict[str, list] = defaultdict(list)
        for s in secciones:
            if s.afecta_disponibilidad and s.rut_profesor:
                por_prof[s.rut_profesor].append(s)
        for grp in por_prof.values():
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    n_rd3 += _nover(x[grp[i].id], x[grp[j].id])

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
                        n_rd4 += _nover(x[ss[i].id], x[ss[j].id])
            else:
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

    # Preferencia por la grilla estándar: minimizar uso de bloques helper.
    helper_indicators = []
    for s in secciones:
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

    asignaciones = {
        sec_id: [solver.Value(v) for v in vars_]
        for sec_id, vars_ in x.items()
    }

    return ResultadoSolver(
        asignaciones=asignaciones,
        estado=estado,
        n_rd1=n_rd1, n_rd2=0, n_rc=n_rc, n_intra=n_intra,
        n_rd3=n_rd3, n_rd4=n_rd4, n_rd7=n_rd7, n_rd8=n_rd8,
    )


# ---------------------------------------------------------------------------
# Fallback progresivo — función principal a usar desde routes.py
# ---------------------------------------------------------------------------

def resolver_con_fallback(
    datos: DatosProblema,
    carreras: list[str] | None = None,
    tiempo_limite_s: float = 60.0,
) -> ResultadoSolver:
    """
    Orden de relajación revisado: RD2 (disponibilidad, negociable con el profesor)
    se relaja ANTES que RD3 (unicidad física) y RD4 (capacidad física).

      Nivel 0 — Completo (RD1 + RD2 + RD3 + RD4)
      Nivel 1 — Sin RD4 (salas especiales)
      Nivel 2 — Sin RD2 (disponibilidad del profesor)
      Nivel 3 — Sin RD2 ni RD4
      Nivel 4 — Sin RD2 ni RD3 ni RD4  ← antes era nivel 4, ahora RD3 cae aquí
      Nivel 5 — Solo intra + NRC (emergencia total)
    """
    niveles: list[dict] = [
        dict(usar_rd2=True,  usar_rd3=True,  usar_rd4=True,  forzar_rd1=True,
             label="Solución completa (todas las restricciones)"),
        dict(usar_rd2=True,  usar_rd3=True,  usar_rd4=False, forzar_rd1=True,
             label="Sin salas especiales (RD4 relajada)"),
        dict(usar_rd2=False, usar_rd3=True,  usar_rd4=True,  forzar_rd1=True,
             label="Sin disponibilidad de profesor (RD2 relajada) — consultar al profesor"),
        dict(usar_rd2=False, usar_rd3=True,  usar_rd4=False, forzar_rd1=True,
             label="Sin RD2 ni RD4 — solo topes de malla y unicidad de profesor"),
        dict(usar_rd2=False, usar_rd3=False, usar_rd4=False, forzar_rd1=True,
             label="Sin RD2, RD3 ni RD4 — solo topes de malla (solución de emergencia)"),
        dict(usar_rd2=False, usar_rd3=False, usar_rd4=False, forzar_rd1=False,
             label="Sin restricciones inter-sección — solución de último recurso"),
    ]

    for nivel, params in enumerate(niveles):
        if nivel > 0:
            print(f"[FALLBACK nivel {nivel}] Reintentando CP-SAT: {params['label']}")

        resultado = resolver(
            datos,
            carreras=carreras,
            tiempo_limite_s=tiempo_limite_s,
            usar_rd2=params["usar_rd2"],
            usar_rd3=params["usar_rd3"],
            usar_rd4=params["usar_rd4"],
            _forzar_rd1=params["forzar_rd1"],
        )

        if resultado.estado in ("OPTIMAL", "FEASIBLE"):
            resultado.nivel_relajacion = nivel
            if nivel == 0:
                resultado.advertencia_relajacion = ""
            else:
                resultado.advertencia_relajacion = (
                    f"⚠ Solución parcial (nivel {nivel}/5): {params['label']}. "
                    "Las restricciones omitidas aparecerán como violaciones en el reporte."
                )
                print(f"[FALLBACK] ✓ Solución encontrada en nivel {nivel}: {params['label']}")
            return resultado

    # Nunca debería llegar aquí, pero retornamos INFEASIBLE limpio si ocurre.
    print("[FALLBACK] ✗ No se encontró solución en ningún nivel.")
    ultimo = ResultadoSolver(estado="INFEASIBLE")
    ultimo.nivel_relajacion = len(niveles)
    ultimo.advertencia_relajacion = (
        "❌ No se encontró ninguna solución. "
        "Revisa los datos de disponibilidad y salas en el maestro."
    )
    return ultimo


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


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def imprimir_resultado(datos: DatosProblema, resultado: ResultadoSolver) -> None:
    print("=" * 60)
    print("RESULTADO CP-SAT")
    print("=" * 60)
    print(f"Estado:               {resultado.estado}")
    if resultado.nivel_relajacion > 0:
        print(f"Nivel de relajación:  {resultado.nivel_relajacion}/5")
        print(f"Advertencia:          {resultado.advertencia_relajacion}")
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