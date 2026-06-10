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

from .blocks import (
    BLOQUES_HELPER,
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
    n_rd1: int = 0
    n_rd2: int = 0
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

# Cobertura por sub-bloque: (dia, minuto_inicio_subbloque) → índices de bloque que lo cubren.
# Sirve para la capacidad de salas: dos bloques DISTINTOS que comparten un sub-bloque
# ocupan la sala en ese instante (ej. 10:30-13:20 y 12:30-15:20 comparten 12:30).
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
# Helper: RC
# ---------------------------------------------------------------------------

def _agregar_rc(
    model: cp_model.CpModel,
    x: dict[str, list[cp_model.IntVar]],
    secciones: list,
) -> int:
    """
    RC — Consistencia de secciones paralelas.

    CLAS y AYUD: todas las secciones del mismo curso y componente van al MISMO bloque
    (sincronización obligatoria — cada sección tiene distintos alumnos pero se dictan
    simultáneamente, cada una en su propia sala de clase).

    LABT: NO se sincronizan. Cada sección de laboratorio obtiene su propio bloque
    independiente, porque:
      (a) El número de salas físicas limita cuántas secciones pueden ser paralelas (RD4).
      (b) Si el mismo profesor dicta varios labs, no pueden coincidir (RD3).
    La restricción de que LABT no solape con CLAS SÍ se mantiene (para cada sección LABT
    individualmente vs el bloque de CLAS del mismo curso).
    """
    grupos: dict[tuple, list] = defaultdict(list)
    for s in secciones:
        if s.id in x:
            grupos[(s.codigo_curso, s.componente)].append(s)

    codigos = {s.codigo_curso for s in secciones if s.id in x}
    n = 0

    for codigo in codigos:
        # ── Sincronizar CLAS y AYUD ───────────────────────────────────────────
        rep: dict[TipoReunion, list[cp_model.IntVar]] = {}

        for comp in (TipoReunion.CLAS, TipoReunion.AYUD):
            secs = grupos.get((codigo, comp), [])
            if not secs:
                continue
            rep[comp] = x[secs[0].id]
            for s in secs[1:]:
                for k, var in enumerate(rep[comp]):
                    model.Add(var == x[s.id][k])
                    n += 1

        # ── CLAS no puede solapar con AYUD ────────────────────────────────────
        comp_list = list(rep.keys())
        for i in range(len(comp_list)):
            for j in range(i + 1, len(comp_list)):
                for vi in rep[comp_list[i]]:
                    for vj in rep[comp_list[j]]:
                        model.AddForbiddenAssignments([vi, vj], _PARES_SOLAPAN)
                        n += 1

        # ── LABT: independiente, pero no puede solapar con CLAS ni AYUD ──────
        labt_secs = grupos.get((codigo, TipoReunion.LABT), [])
        for s_labt in labt_secs:
            for comp_vars in rep.values():
                for v_labt in x[s_labt.id]:
                    for v_comp in comp_vars:
                        model.AddForbiddenAssignments([v_labt, v_comp], _PARES_SOLAPAN)
                        n += 1

    return n


# ---------------------------------------------------------------------------
# Helper: RD2 — Disponibilidad de profesor
# ---------------------------------------------------------------------------

def _agregar_rd2(
    model: cp_model.CpModel,
    x: dict[str, list[cp_model.IntVar]],
    secciones: list,
    datos,          # DatosProblema
) -> int:
    """
    RD2 — Disponibilidad de profesor: una sección con afecta_disponibilidad=True
    solo puede asignarse a bloques en que el profesor está disponible.

    La disponibilidad se lee de Profesor.disponibilidad (set[int] de índices de bloque).
    Si el set está vacío → disponibilidad total asumida (sin restricción).
    Solo aplica a secciones con afecta_disponibilidad=True.
    """
    n = 0
    for s in secciones:
        if not s.afecta_disponibilidad or s.id not in x:
            continue
        prof = datos.profesores.get(s.rut_profesor)
        if not prof or not prof.disponibilidad:
            continue  # sin datos → disponibilidad total
        for var in x[s.id]:
            for block_idx in range(N_BLOQUES):
                if block_idx not in prof.disponibilidad:
                    model.Add(var != block_idx)
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
            por_prof[s.rut_profesor].append(s)  # ← todas las sin profesor quedan agrupadas juntas

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
    datos,          # DatosProblema completo (necesario para cursos y capacidad_por_sala)
) -> int:
    """
    RD4 — Sala especial: en cada bloque, la cantidad de secciones asignadas
    a un mismo tipo de sala no puede superar la cantidad de salas físicas disponibles.

    La capacidad viene de datos.capacidad_por_sala (leído de la hoja SALAS ESPECIALES).

    Tres casos según si la capacidad es conocida y su valor:

      capacidad desconocida (sala no en dict)
          → Solo se restringen cursos DISTINTOS (pairwise). Las secciones del
            MISMO curso NO se restringen: RC ya las sincroniza al mismo bloque y
            sin datos de capacidad no podemos saber si hay conflicto real.
            Este es el comportamiento conservador cuando falta el archivo de salas.

      capacidad = 1 (1 sala física, dato explícito)
          → Pairwise sobre TODOS los pares, incluido mismo curso. Si un curso
            tiene más secciones paralelas que salas físicas, CP-SAT reportará
            INFEASIBLE correctamente.

      capacidad > 1 (C salas físicas)
          → Sum constraint: at most C secciones en el mismo bloque. Incluye
            mismo curso. RC garantiza que las secciones de un mismo grupo
            de componente van al mismo bloque, por lo que el conteo es correcto.

    Solo aplica a CLAS y LABT (AYUD no usa sala especial).
    """
    por_sala: dict[str, list] = defaultdict(list)
    for s in secciones:
        if s.id not in x:
            continue
        if s.componente == TipoReunion.AYUD:
            continue
        curso = datos.cursos.get(s.codigo_curso)
        if curso and curso.sala_especial:
            por_sala[curso.sala_especial].append(s)

    cap = datos.capacidad_por_sala   # {sala_name: n_salas_fisicas}
    n = 0

    for sala, secs in por_sala.items():
        capacidad = cap.get(sala, None)  # None = sin datos de capacidad física

        if capacidad is None:
            # Capacidad desconocida: solo restringir cursos distintos (conservador)
            # No tocar pares del mismo curso para no contradecir RC.
            for i in range(len(secs)):
                for j in range(i + 1, len(secs)):
                    if secs[i].codigo_curso == secs[j].codigo_curso:
                        continue
                    for v1 in x[secs[i].id]:
                        for v2 in x[secs[j].id]:
                            model.AddForbiddenAssignments([v1, v2], _PARES_SOLAPAN)
                            n += 1

        elif capacidad == 1:
            # 1 sala física (dato explícito): ningún par puede solaparse
            for i in range(len(secs)):
                for j in range(i + 1, len(secs)):
                    for v1 in x[secs[i].id]:
                        for v2 in x[secs[j].id]:
                            model.AddForbiddenAssignments([v1, v2], _PARES_SOLAPAN)
                            n += 1

        else:
            # C > 1 salas físicas: at most (capacidad) secciones en el mismo bloque.
            # La restricción intra-sección garantiza que los bloques de una misma
            # sección están en días distintos, por lo que cada variable aporta
            # a lo sumo 1 indicator por bloque.
            for block_idx in range(N_BLOQUES):
                indicators = []
                for s in secs:
                    for var in x[s.id]:
                        b = model.NewBoolVar(f"rd4_b{block_idx}_{s.id}")
                        model.Add(var == block_idx).OnlyEnforceIf(b)
                        model.Add(var != block_idx).OnlyEnforceIf(b.Not())
                        indicators.append(b)
                if len(indicators) > capacidad:
                    model.Add(sum(indicators) <= capacidad)
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
# Agrupación de secciones paralelas
# ---------------------------------------------------------------------------

def disponibilidad_seccion(
    datos: DatosProblema, s, usar_rd2: bool = True
) -> set[int]:
    """
    Bloques en que una sección PUEDE dictarse:
      - AYUD → solo desde 12:30 (RD7)
      - con disponibilidad declarada → bloques del profesor (estándar + helper)
      - sin disponibilidad → solo bloques ESTÁNDAR (preserva la grilla institucional)
    """
    es_ayud = s.componente == TipoReunion.AYUD
    base = {b for b in range(N_BLOQUES)
            if not es_ayud or b not in _BLOQUES_PROHIBIDOS_AYUD}
    prof = datos.profesores.get(s.rut_profesor) if s.rut_profesor else None
    tiene = usar_rd2 and s.afecta_disponibilidad and prof is not None and bool(prof.disponibilidad)
    if tiene:
        return {b for b in base if b in prof.disponibilidad}
    return {b for b in base if b in SET_ESTANDAR}


def _puede_alojar(dom: set[int], n: int) -> bool:
    """True si en `dom` caben n bloques mutuamente no solapados."""
    picked: list[int] = []
    for b in sorted(dom):
        if all(not MATRIZ_SOLAPAMIENTO[b][p] for p in picked):
            picked.append(b)
            if len(picked) >= n:
                return True
    return len(picked) >= n


@dataclass
class GrupoParalelo:
    """Conjunto de secciones que se dictan en paralelo (mismo bloque)."""
    ids: list[str]                 # sec_ids sincronizadas a este grupo
    codigo: str
    componente: TipoReunion
    n_blocks: int                  # bloques necesarios (igual para todo el grupo)
    dominio: list[int]             # bloques candidatos = ∩ disponibilidad del grupo
    profesores: set[str]           # ruts que afectan disponibilidad en el grupo
    sala: str | None               # sala especial del curso (si aplica)


def agrupar_paralelas(
    datos: DatosProblema, secciones: list, usar_rd2: bool = True
) -> tuple[list[GrupoParalelo], dict[str, int]]:
    """
    Agrupa las secciones de cada (curso, componente) que PUEDEN dictarse en paralelo.

    Dos secciones pueden ir en el mismo grupo si:
      1. La intersección de la disponibilidad de sus profesores aún aloja los bloques
         necesarios (sus profesores coinciden en horario).
      2. No comparten profesor (un profesor no puede dictar dos secciones a la vez).
      3. No exceden la capacidad de salas físicas (para componentes con sala especial).

    Las secciones que no caben en ningún grupo existente abren un grupo nuevo.
    Retorna (grupos, sec_id → índice de grupo).
    """
    grupos: list[GrupoParalelo] = []
    sec2grupo: dict[str, int] = {}

    por_cc: dict[tuple, list] = defaultdict(list)
    for s in secciones:
        por_cc[(s.codigo_curso, s.componente)].append(s)

    for (cod, comp), secs in por_cc.items():
        curso = datos.cursos.get(cod)
        sala = curso.sala_especial if curso else None
        cap = datos.capacidad_por_sala.get(sala) if sala else None
        usa_sala = sala is not None and comp != TipoReunion.AYUD

        # Precomputar disponibilidad por sección y ordenar de MÁS RÍGIDA a más flexible.
        # Así las secciones con poca disponibilidad forman su grupo primero (o quedan
        # solas) y las flexibles se suman después al grupo que mejor calce, sin quedar
        # encadenadas a un profesor rígido.
        info = []
        for s in secs:
            d = disponibilidad_seccion(datos, s, usar_rd2)
            prof = s.rut_profesor if (s.afecta_disponibilidad and s.rut_profesor) else None
            info.append((s, d, s.cantidad_bloques_necesarios, prof))
        info.sort(key=lambda t: (len(t[1]), str(t[0].seccion)))

        clusters: list[dict] = []
        for s, d, n, prof in info:
            # Entre los clusters donde la sección PUEDE entrar, elegir el de mayor
            # intersección resultante (best-fit: conserva más flexibilidad).
            mejor = None
            mejor_inter: set[int] = set()
            for cl in clusters:
                if prof and prof in cl["profs"]:
                    continue                                  # mismo profesor → no paralelas
                if usa_sala and cap is not None and len(cl["secs"]) >= cap:
                    continue                                  # capacidad de sala llena
                nueva_inter = cl["inter"] & d
                if not _puede_alojar(nueva_inter, max(n, cl["n"])):
                    continue                                  # ya no coinciden en horario
                if mejor is None or len(nueva_inter) > len(mejor_inter):
                    mejor, mejor_inter = cl, nueva_inter

            if mejor is not None:
                mejor["inter"] = mejor_inter
                mejor["secs"].append(s)
                mejor["n"] = max(mejor["n"], n)
                if prof:
                    mejor["profs"].add(prof)
            else:
                clusters.append({
                    "inter": set(d), "secs": [s],
                    "profs": {prof} if prof else set(), "n": n,
                })

        for cl in clusters:
            idx = len(grupos)
            grupos.append(GrupoParalelo(
                ids=[s.id for s in cl["secs"]],
                codigo=cod, componente=comp, n_blocks=cl["n"],
                dominio=sorted(cl["inter"]), profesores=cl["profs"], sala=sala,
            ))
            for s in cl["secs"]:
                sec2grupo[s.id] = idx

    return grupos, sec2grupo


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def resolver(
    datos: DatosProblema,
    carreras: list[str] | None = None,
    tiempo_limite_s: float = 60.0,
    usar_rd2: bool = True,
    usar_rd3: bool = True,
    usar_rd4: bool = True,
) -> ResultadoSolver:
    """
    Asigna bloques a nivel de SECCIÓN. El solver decide el paralelismo por sí mismo:
    para que todos los ramos de un semestre quepan sin topes (RD1 estricto entre cursos
    distintos), pone en paralelo las secciones de un mismo curso donde la disponibilidad
    de sus profesores lo permite. No se pre-agrupa.

    Restricciones duras:
      RD2  — cada sección en la disponibilidad de su profesor (o grilla estándar si no
             hay datos; AYUD solo desde 12:30 = RD7, ya en el dominio).
      intra — los bloques de una sección no se solapan entre sí.
      NRC  — dentro de una sección (CLAS-k/AYUD-k/LABT-k) los componentes no se solapan.
      RD1  — secciones de cursos DISTINTOS del mismo (carrera, semestre) no se solapan;
             las del MISMO curso quedan exentas (pueden ir en paralelo).
      RD3  — un profesor no dicta dos secciones a la vez.
      RD4  — en cada bloque, las secciones que usan un mismo tipo de sala no superan
             las salas físicas disponibles.
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
        dom = sorted(disponibilidad_seccion(datos, s, usar_rd2))
        if not dom:
            return ResultadoSolver(estado="INFEASIBLE")
        dom_de[s.id] = dom
        x[s.id] = [
            model.NewIntVarFromDomain(cp_model.Domain.FromValues(dom), f"{s.id}_b{k}")
            for k in range(s.cantidad_bloques_necesarios)
        ]

    def _nover(a_vars, b_vars) -> int:
        c = 0
        for v1 in a_vars:
            for v2 in b_vars:
                model.AddForbiddenAssignments([v1, v2], _PARES_SOLAPAN)
                c += 1
        return c

    # Intra-sección
    n_intra = 0
    for s in secciones:
        v = x[s.id]
        for k1 in range(len(v)):
            for k2 in range(k1 + 1, len(v)):
                model.AddForbiddenAssignments([v[k1], v[k2]], _PARES_SOLAPAN)
                n_intra += 1

    # NRC: componentes distintos de una misma sección (codigo, seccion) no se solapan
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

    # RD3: un profesor (afecta_disponibilidad) no dicta dos secciones a la vez
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

    # RD4: capacidad de salas — en cada bloque, las secciones que usan un mismo tipo de
    # sala no superan las salas físicas. Incluye secciones del mismo curso (las paralelas
    # consumen una sala cada una).
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
                cap = 1   # sala de capacidad desconocida → asumir 1 sala física (conservador)
            if cap == 1:
                # 1 sala física: ningún par de secciones puede solaparse (mismo o distinto curso)
                for i in range(len(ss)):
                    for j in range(i + 1, len(ss)):
                        n_rd4 += _nover(x[ss[i].id], x[ss[j].id])
            else:
                # cap > 1: a lo más `cap` secciones usando la sala en cada sub-bloque (instante)
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
    """
    Retorna (sec1_id, sec2_id, sala) de violaciones de sala especial.

    Para capacidad = 1: cualquier solapamiento entre dos secciones es una violación.
    Para capacidad > 1: es una violación cuando más de (capacidad) secciones
    coinciden en el mismo bloque.

    Incluye pares del mismo curso (a diferencia de la versión anterior).
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
            capacidad = 1   # desconocida → asumir 1 sala física (consistente con resolver)

        if capacidad == 1:
            # Cualquier solapamiento es violación (incluyendo mismo curso)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    id1, id2 = ids[i], ids[j]
                    if any(MATRIZ_SOLAPAMIENTO[b1][b2]
                           for b1 in asignaciones[id1]
                           for b2 in asignaciones[id2]):
                        conflictos.append((id1, id2, sala))
        else:
            # Violación cuando más de (capacidad) secciones comparten el mismo bloque
            from collections import Counter
            bloque_count: Counter = Counter()
            bloque_secs: dict[int, list[str]] = defaultdict(list)
            for sec_id in ids:
                for b in asignaciones[sec_id]:
                    bloque_count[b] += 1
                    bloque_secs[b].append(sec_id)

            for bloque, count in bloque_count.items():
                if count > capacidad:
                    # Todos los pares en exceso son conflictos
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
    print(f"Secciones asignadas:  {len(resultado.asignaciones)}")
    total_bloques = sum(len(b) for b in resultado.asignaciones.values())
    print(f"Bloques totales:      {total_bloques}")
    print(f"Restricciones RD1:    {resultado.n_rd1}")
    print(f"Restricciones RD2:    {resultado.n_rd2}")
    print(f"Restricciones RC:     {resultado.n_rc}")
    print(f"Restricciones intra:  {resultado.n_intra}")
    print(f"Restricciones RD3:    {resultado.n_rd3}")
    print(f"Restricciones RD4:    {resultado.n_rd4}")
    print(f"Restricciones RD7:    {resultado.n_rd7}")

    if not resultado.asignaciones:
        return

    # Uso de bloques helper (no estándar): debería ser bajo
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
