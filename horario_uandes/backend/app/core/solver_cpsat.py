"""
solver_cpsat.py — Fase 1: restricciones duras via CP-SAT.

Implementación incremental (PRD §8):
  Paso 2 (ACTUAL): RD1 solo Plan Común + RC (sincronización de secciones)
  Paso 3:          RD1 + ICI
  Paso 4:          RD1 + IOC, ICE, ICC, ICA
  Paso 5:          Múltiples bloques por sección
  Paso 6:          RD3, RD4, RD7, RD8

RD1 — Sin topes mismo semestre/carrera:
  Cursos DISTINTOS del mismo (carrera, semestre) no pueden tener bloques solapados.
  RD1 aplica SOLO entre cursos distintos; secciones del mismo curso no se restringen
  entre sí por RD1 (son grupos paralelos de alumnos distintos).

RC — Restricción de paralelismo de secciones del mismo curso:
  1. Sincronización: todas las secciones CLAS del mismo curso van al mismo bloque.
     Ídem para AYUD y LABT. (Práctica normal de la universidad.)
  2. No solapamiento intra-curso: los bloques de CLAS, AYUD y LABT del mismo curso
     deben ser mutuamente no solapados (los alumnos de cada sección asisten a los tres).

Solapamiento: verificado por sub-bloques (MATRIZ_SOLAPAMIENTO), NO por igualdad de índice.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .blocks import MATRIZ_SOLAPAMIENTO, N_BLOQUES, TODOS_BLOQUES
from .models import DatosProblema, TipoReunion


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoSolver:
    asignaciones: dict[str, int] = field(default_factory=dict)
    estado: str = "UNKNOWN"
    n_rd1: int = 0   # restricciones RD1 agregadas
    n_rc: int = 0    # restricciones RC (sincronización + no solapamiento intra-curso)


# ---------------------------------------------------------------------------
# Precómputo
# ---------------------------------------------------------------------------

_PARES_SOLAPAN: list[tuple[int, int]] = [
    (i, j)
    for i in range(N_BLOQUES)
    for j in range(N_BLOQUES)
    if MATRIZ_SOLAPAMIENTO[i][j]
]


# ---------------------------------------------------------------------------
# Helper: RC — Restricción de paralelismo de secciones
# ---------------------------------------------------------------------------

def _agregar_rc(
    model: cp_model.CpModel,
    x: dict[str, cp_model.IntVar],
    secciones: list,
) -> int:
    """
    Para cada curso en el modelo:
      - Sincroniza todas sus secciones CLAS al mismo bloque (id1 == id2 == ...).
        Ídem para AYUD y LABT.
      - Agrega no-solapamiento entre bloques de distintos componentes del mismo curso:
        CLAS ↔ AYUD, CLAS ↔ LABT, AYUD ↔ LABT.

    Retorna el número de restricciones agregadas.
    """
    # Agrupar por (codigo_curso, componente)
    grupos: dict[tuple, list] = defaultdict(list)
    for s in secciones:
        if s.id in x:
            grupos[(s.codigo_curso, s.componente)].append(s)

    codigos = {s.codigo_curso for s in secciones if s.id in x}
    n = 0

    for codigo in codigos:
        # Obtener el representante de cada componente (primera sección del tipo)
        rep: dict[TipoReunion, cp_model.IntVar] = {}

        for comp in TipoReunion:
            secs = grupos.get((codigo, comp), [])
            if not secs:
                continue
            rep[comp] = x[secs[0].id]

            # 1. Sincronización: todas las secciones del mismo componente → mismo bloque
            for s in secs[1:]:
                model.Add(rep[comp] == x[s.id])
                n += 1

        # 2. No solapamiento entre distintos componentes del mismo curso
        componentes = list(rep.keys())
        for i in range(len(componentes)):
            for j in range(i + 1, len(componentes)):
                model.AddForbiddenAssignments(
                    [rep[componentes[i]], rep[componentes[j]]],
                    _PARES_SOLAPAN,
                )
                n += 1

    return n


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def resolver(
    datos: DatosProblema,
    carreras: list[str] | None = None,
    tiempo_limite_s: float = 60.0,
) -> ResultadoSolver:
    """
    Asigna 1 bloque por sección aplicando RD1 (para las carreras indicadas) y RC.

    Args:
        carreras:  Carreras a restringir con RD1. Por defecto ["Plan Común"] (paso 2).
    """
    if carreras is None:
        carreras = ["Plan Común"]

    model = cp_model.CpModel()

    # 1. Secciones en el modelo (cursos que pertenecen a alguna carrera restringida)
    codigos_restringidos = {
        c.codigo
        for c in datos.cursos.values()
        if any(car in c.semestres_por_carrera for car in carreras)
    }
    secciones = [s for s in datos.secciones if s.codigo_curso in codigos_restringidos]

    # 2. Variables
    x: dict[str, cp_model.IntVar] = {
        s.id: model.NewIntVar(0, N_BLOQUES - 1, s.id)
        for s in secciones
    }

    # 3. RC: sincronización + no solapamiento intra-curso
    n_rc = _agregar_rc(model, x, secciones)

    # 4. RD1: pares de secciones de CURSOS DISTINTOS en el mismo (carrera, semestre)
    n_rd1 = 0
    for carrera in carreras:
        grupos: dict[str, list] = defaultdict(list)
        for s in secciones:
            curso = datos.cursos.get(s.codigo_curso)
            if not curso:
                continue
            for sem in curso.semestres_por_carrera.get(carrera, set()):
                grupos[sem].append(s)

        for sem, secs in grupos.items():
            for i in range(len(secs)):
                for j in range(i + 1, len(secs)):
                    s1, s2 = secs[i], secs[j]
                    if s1.codigo_curso == s2.codigo_curso:
                        continue
                    model.AddForbiddenAssignments(
                        [x[s1.id], x[s2.id]], _PARES_SOLAPAN
                    )
                    n_rd1 += 1

    # 5. Resolver
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
        return ResultadoSolver(estado=estado, n_rd1=n_rd1, n_rc=n_rc)

    return ResultadoSolver(
        asignaciones={sec_id: solver.Value(var) for sec_id, var in x.items()},
        estado=estado,
        n_rd1=n_rd1,
        n_rc=n_rc,
    )


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------

def verificar_topes(
    datos: DatosProblema,
    asignaciones: dict[str, int],
    carrera: str,
) -> list[tuple[str, str, str]]:
    """
    Retorna (sec1_id, sec2_id, semestre) de cada tope RD1 encontrado en la solución.
    """
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
                if MATRIZ_SOLAPAMIENTO[asignaciones[id1]][asignaciones[id2]]:
                    topes.append((id1, id2, sem))

    return topes


def verificar_rc(
    datos: DatosProblema,
    asignaciones: dict[str, int],
) -> dict[str, list]:
    """
    Verifica las restricciones RC en la solución. Retorna dict con violaciones:
      "desync":    [(sec1_id, sec2_id)] pares del mismo curso/componente con bloques distintos
      "solapan":   [(sec1_id, sec2_id)] pares de distintos componentes del mismo curso que solapan
    """
    sec_by_id = {s.id: s for s in datos.secciones}
    asig_secs = [sec_by_id[sid] for sid in asignaciones if sid in sec_by_id]

    # Agrupar por (codigo_curso, componente)
    por_cc: dict[tuple, list[str]] = defaultdict(list)
    for s in asig_secs:
        por_cc[(s.codigo_curso, s.componente)].append(s.id)

    codigos = {s.codigo_curso for s in asig_secs}
    desync: list[tuple] = []
    solapan: list[tuple] = []

    for codigo in codigos:
        # Verificar sincronización: todas las secciones del mismo componente → mismo bloque
        for comp in TipoReunion:
            ids = por_cc.get((codigo, comp), [])
            if len(ids) < 2:
                continue
            bloque_ref = asignaciones[ids[0]]
            for sid in ids[1:]:
                if asignaciones[sid] != bloque_ref:
                    desync.append((ids[0], sid))

        # Verificar no solapamiento entre componentes distintos
        comps_presentes = [c for c in TipoReunion if (codigo, c) in por_cc]
        for i in range(len(comps_presentes)):
            for j in range(i + 1, len(comps_presentes)):
                c1, c2 = comps_presentes[i], comps_presentes[j]
                sid1 = por_cc[(codigo, c1)][0]
                sid2 = por_cc[(codigo, c2)][0]
                if MATRIZ_SOLAPAMIENTO[asignaciones[sid1]][asignaciones[sid2]]:
                    solapan.append((sid1, sid2))

    return {"desync": desync, "solapan": solapan}


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def imprimir_resultado(datos: DatosProblema, resultado: ResultadoSolver) -> None:
    print("=" * 60)
    print("RESULTADO CP-SAT")
    print("=" * 60)
    print(f"Estado:               {resultado.estado}")
    print(f"Secciones asignadas:  {len(resultado.asignaciones)}")
    print(f"Restricciones RD1:    {resultado.n_rd1}")
    print(f"Restricciones RC:     {resultado.n_rc}")

    if not resultado.asignaciones:
        return

    conteo: dict[int, int] = defaultdict(int)
    for idx in resultado.asignaciones.values():
        conteo[idx] += 1

    print("\nDistribución por bloque:")
    for bloque_idx in sorted(conteo):
        b = TODOS_BLOQUES[bloque_idx]
        print(f"  {b.dia.value} {b.hora_inicio}-{b.hora_fin} ({b.tipo}): "
              f"{conteo[bloque_idx]} sección(es)")
