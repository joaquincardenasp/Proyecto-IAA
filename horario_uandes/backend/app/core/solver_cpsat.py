"""
solver_cpsat.py — Fase 1: restricciones duras via CP-SAT.

Implementación incremental (PRD §8):
  Paso 2:  RD1 solo Plan Común + RC
  Paso 3:  RD1 + ICI
  Paso 4:  RD1 + IOC, ICE, ICC, ICA, ICQ
  Paso 5:  Múltiples bloques por sección
  Paso 6:  RD3, RD4, RD7, RD8 (ACTUAL)

RD1 — Sin topes mismo semestre/carrera:
  Cursos DISTINTOS del mismo (carrera, semestre) no pueden tener bloques solapados.

RC — Paralelismo de secciones del mismo curso:
  1. Sincronización: todas las secciones CLAS van al mismo bloque. Ídem AYUD, LABT.
  2. No solapamiento: ningún bloque de CLAS puede solapar con ningún bloque de AYUD/LABT.

Intra-sección: bloques de la misma sección no pueden solaparse entre sí.

RD3 — Unicidad de profesor:
  Un profesor no puede dictar 2 secciones con afecta_disponibilidad=True simultáneamente.

RD4 — Sala especial única:
  Dos secciones con la misma sala especial no pueden coincidir.

RD7 — Ayudantías desde 12:30:
  Los bloques asignados a secciones AYUD deben iniciar a las 12:30 o después.

RD8 — Prof lab/cátedra:
  Si el prof de lab es el mismo que el de cátedra (mismo curso), no pueden coincidir.
  Nota: ya cubierto completamente por RC. Se cuenta para documentar.

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
    asignaciones: dict[str, list[int]] = field(default_factory=dict)  # sec_id → [bloque_idx, ...]
    estado: str = "UNKNOWN"
    n_rd1: int = 0
    n_rc: int = 0
    n_intra: int = 0
    n_rd3: int = 0
    n_rd4: int = 0
    n_rd7: int = 0
    n_rd8: int = 0   # siempre 0 (cubierto por RC), se mantiene para documentar


# ---------------------------------------------------------------------------
# Precómputo
# ---------------------------------------------------------------------------

_PARES_SOLAPAN: list[tuple[int, int]] = [
    (i, j)
    for i in range(N_BLOQUES)
    for j in range(N_BLOQUES)
    if MATRIZ_SOLAPAMIENTO[i][j]
]


def _hora_a_min(hora: str) -> int:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


_MIN_12_30 = 12 * 60 + 30

_BLOQUES_PROHIBIDOS_AYUD: list[int] = [
    i for i, b in enumerate(TODOS_BLOQUES)
    if _hora_a_min(b.hora_inicio) < _MIN_12_30
]


# ---------------------------------------------------------------------------
# Helper: RC
# ---------------------------------------------------------------------------

def _agregar_rc(
    model: cp_model.CpModel,
    x: dict[str, list[cp_model.IntVar]],
    secciones: list,
) -> int:
    grupos: dict[tuple, list] = defaultdict(list)
    for s in secciones:
        if s.id in x:
            grupos[(s.codigo_curso, s.componente)].append(s)

    codigos = {s.codigo_curso for s in secciones if s.id in x}
    n = 0

    for codigo in codigos:
        rep: dict[TipoReunion, list[cp_model.IntVar]] = {}

        for comp in TipoReunion:
            secs = grupos.get((codigo, comp), [])
            if not secs:
                continue
            rep[comp] = x[secs[0].id]
            for s in secs[1:]:
                for k, var in enumerate(rep[comp]):
                    model.Add(var == x[s.id][k])
                    n += 1

        componentes = list(rep.keys())
        for i in range(len(componentes)):
            for j in range(i + 1, len(componentes)):
                for vi in rep[componentes[i]]:
                    for vj in rep[componentes[j]]:
                        model.AddForbiddenAssignments([vi, vj], _PARES_SOLAPAN)
                        n += 1

    return n


# ---------------------------------------------------------------------------
# Helper: RD3 — Unicidad de profesor
# ---------------------------------------------------------------------------

def _agregar_rd3(
    model: cp_model.CpModel,
    x: dict[str, list[cp_model.IntVar]],
    secciones: list,
) -> int:
    """Un profesor no puede dictar 2 secciones con afecta_disponibilidad=True simultáneamente.

    Excluye pares del MISMO curso: RC ya los maneja (secciones paralelas van al mismo
    bloque intencionalmente; si el mismo prof dicta CLAS-1 y CLAS-2, es válido).
    """
    por_prof: dict[str, list] = defaultdict(list)
    for s in secciones:
        if s.afecta_disponibilidad and s.id in x:
            por_prof[s.rut_profesor].append(s)

    n = 0
    for secs in por_prof.values():
        for i in range(len(secs)):
            for j in range(i + 1, len(secs)):
                if secs[i].codigo_curso == secs[j].codigo_curso:
                    continue  # mismo curso → manejado por RC
                for v1 in x[secs[i].id]:
                    for v2 in x[secs[j].id]:
                        model.AddForbiddenAssignments([v1, v2], _PARES_SOLAPAN)
                        n += 1
    return n


# ---------------------------------------------------------------------------
# Helper: RD4 — Sala especial única
# ---------------------------------------------------------------------------

def _agregar_rd4(
    model: cp_model.CpModel,
    x: dict[str, list[cp_model.IntVar]],
    secciones: list,
    cursos: dict,
) -> int:
    """Dos secciones de CURSOS DISTINTOS con la misma sala especial no pueden coincidir.

    Solo aplica a CLAS y LABT (AYUD no usa sala especial).
    Excluye pares del MISMO curso: las secciones paralelas (CLAS-1/CLAS-2) van al mismo
    bloque intencionalmente (usan salas del mismo tipo, no la misma sala física).
    """
    por_sala: dict[str, list] = defaultdict(list)
    for s in secciones:
        if s.id not in x:
            continue
        if s.componente.value == "AYUD":
            continue  # AYUD no usa sala especial
        curso = cursos.get(s.codigo_curso)
        if curso and curso.sala_especial:
            por_sala[curso.sala_especial].append(s)

    n = 0
    for secs in por_sala.values():
        for i in range(len(secs)):
            for j in range(i + 1, len(secs)):
                if secs[i].codigo_curso == secs[j].codigo_curso:
                    continue  # mismo curso → permitido (salas paralelas del mismo tipo)
                for v1 in x[secs[i].id]:
                    for v2 in x[secs[j].id]:
                        model.AddForbiddenAssignments([v1, v2], _PARES_SOLAPAN)
                        n += 1
    return n


# ---------------------------------------------------------------------------
# Helper: RD7 — Ayudantías desde 12:30
# ---------------------------------------------------------------------------

def _agregar_rd7(
    model: cp_model.CpModel,
    x: dict[str, list[cp_model.IntVar]],
    secciones: list,
) -> int:
    """Bloques de AYUD deben iniciar a las 12:30 o después."""
    n = 0
    for s in secciones:
        if s.componente != TipoReunion.AYUD or s.id not in x:
            continue
        for var in x[s.id]:
            for forbidden in _BLOQUES_PROHIBIDOS_AYUD:
                model.Add(var != forbidden)
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
    Asigna bloques a cada sección aplicando todas las restricciones duras.

    Args:
        carreras:        Carreras a restringir con RD1. Por defecto ["Plan Común"].
        tiempo_limite_s: Tiempo máximo en segundos.
    """
    if carreras is None:
        carreras = ["Plan Común"]

    model = cp_model.CpModel()

    # 1. Secciones en el modelo
    codigos_restringidos = {
        c.codigo
        for c in datos.cursos.values()
        if any(car in c.semestres_por_carrera for car in carreras)
    }
    secciones = [s for s in datos.secciones if s.codigo_curso in codigos_restringidos]

    # 2. Variables: una lista de IntVars por sección
    x: dict[str, list[cp_model.IntVar]] = {
        s.id: [
            model.NewIntVar(0, N_BLOQUES - 1, f"{s.id}_b{k}")
            for k in range(s.cantidad_bloques_necesarios)
        ]
        for s in secciones
    }

    # 3. Intra-sección
    n_intra = 0
    for s in secciones:
        vars_ = x[s.id]
        for k1 in range(len(vars_)):
            for k2 in range(k1 + 1, len(vars_)):
                model.AddForbiddenAssignments([vars_[k1], vars_[k2]], _PARES_SOLAPAN)
                n_intra += 1

    # 4. RC: sincronización + no solapamiento intra-curso
    n_rc = _agregar_rc(model, x, secciones)

    # 5. RD1: no topes entre cursos distintos del mismo (carrera, semestre)
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
                    for v1 in x[s1.id]:
                        for v2 in x[s2.id]:
                            model.AddForbiddenAssignments([v1, v2], _PARES_SOLAPAN)
                            n_rd1 += 1

    # 6. RD3: unicidad de profesor (afecta_disponibilidad=True)
    n_rd3 = _agregar_rd3(model, x, secciones)

    # 7. RD4: sala especial única
    n_rd4 = _agregar_rd4(model, x, secciones, datos.cursos)

    # 8. RD7: ayudantías desde 12:30
    n_rd7 = _agregar_rd7(model, x, secciones)

    # 9. RD8: cubierto completamente por RC (mismo curso, CLAS vs LABT)
    n_rd8 = 0

    # 10. Resolver
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
            estado=estado, n_rd1=n_rd1, n_rc=n_rc, n_intra=n_intra,
            n_rd3=n_rd3, n_rd4=n_rd4, n_rd7=n_rd7, n_rd8=n_rd8,
        )

    return ResultadoSolver(
        asignaciones={
            sec_id: [solver.Value(v) for v in vars_]
            for sec_id, vars_ in x.items()
        },
        estado=estado,
        n_rd1=n_rd1, n_rc=n_rc, n_intra=n_intra,
        n_rd3=n_rd3, n_rd4=n_rd4, n_rd7=n_rd7, n_rd8=n_rd8,
    )


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


def verificar_rc(
    datos: DatosProblema,
    asignaciones: dict[str, list[int]],
) -> dict[str, list]:
    """
    Verifica RC en la solución. Retorna:
      "desync":  [(sec1_id, sec2_id)] pares del mismo curso/componente con bloques distintos
      "solapan": [(sec1_id, sec2_id)] pares de componentes distintos del mismo curso que solapan
    """
    sec_by_id = {s.id: s for s in datos.secciones}
    asig_secs = [sec_by_id[sid] for sid in asignaciones if sid in sec_by_id]

    por_cc: dict[tuple, list[str]] = defaultdict(list)
    for s in asig_secs:
        por_cc[(s.codigo_curso, s.componente)].append(s.id)

    codigos = {s.codigo_curso for s in asig_secs}
    desync: list[tuple] = []
    solapan: list[tuple] = []

    for codigo in codigos:
        for comp in TipoReunion:
            ids = por_cc.get((codigo, comp), [])
            if len(ids) < 2:
                continue
            bloques_ref = asignaciones[ids[0]]
            for sid in ids[1:]:
                if asignaciones[sid] != bloques_ref:
                    desync.append((ids[0], sid))

        comps_presentes = [c for c in TipoReunion if (codigo, c) in por_cc]
        for i in range(len(comps_presentes)):
            for j in range(i + 1, len(comps_presentes)):
                c1, c2 = comps_presentes[i], comps_presentes[j]
                sid1 = por_cc[(codigo, c1)][0]
                sid2 = por_cc[(codigo, c2)][0]
                if any(MATRIZ_SOLAPAMIENTO[b1][b2]
                       for b1 in asignaciones[sid1]
                       for b2 in asignaciones[sid2]):
                    solapan.append((sid1, sid2))

    return {"desync": desync, "solapan": solapan}


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
    """Retorna (sec1_id, sec2_id, sala) de conflictos de sala especial entre CURSOS DISTINTOS."""
    sec_by_id = {s.id: s for s in datos.secciones}
    por_sala: dict[str, list[str]] = defaultdict(list)
    for sec_id in asignaciones:
        s = sec_by_id.get(sec_id)
        if not s or s.componente.value == "AYUD":
            continue
        curso = datos.cursos.get(s.codigo_curso)
        if curso and curso.sala_especial:
            por_sala[curso.sala_especial].append(sec_id)

    conflictos = []
    for sala, ids in por_sala.items():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id1, id2 = ids[i], ids[j]
                s1, s2 = sec_by_id[id1], sec_by_id[id2]
                if s1.codigo_curso == s2.codigo_curso:
                    continue
                if any(MATRIZ_SOLAPAMIENTO[b1][b2]
                       for b1 in asignaciones[id1]
                       for b2 in asignaciones[id2]):
                    conflictos.append((id1, id2, sala))
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
    print(f"Secciones asignadas:  {len(resultado.asignaciones)}")
    total_bloques = sum(len(b) for b in resultado.asignaciones.values())
    print(f"Bloques totales:      {total_bloques}")
    print(f"Restricciones RD1:    {resultado.n_rd1}")
    print(f"Restricciones RC:     {resultado.n_rc}")
    print(f"Restricciones intra:  {resultado.n_intra}")
    print(f"Restricciones RD3:    {resultado.n_rd3}")
    print(f"Restricciones RD4:    {resultado.n_rd4}")
    print(f"Restricciones RD7:    {resultado.n_rd7}")

    if not resultado.asignaciones:
        return

    conteo: dict[int, int] = defaultdict(int)
    for bloques in resultado.asignaciones.values():
        for idx in bloques:
            conteo[idx] += 1

    print("\nDistribución por bloque:")
    for bloque_idx in sorted(conteo):
        b = TODOS_BLOQUES[bloque_idx]
        print(f"  {b.dia.value} {b.hora_inicio}-{b.hora_fin} ({b.tipo}): "
              f"{conteo[bloque_idx]} asignación(es)")
