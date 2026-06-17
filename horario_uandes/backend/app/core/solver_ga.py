"""
solver_ga.py — Fase 2: mejora de restricciones blandas via algoritmo genético (DEAP).

Restricciones blandas (RB):
  RB1 (100): Labs de Programación consecutivos (ING1103-LABT, bloques en día contiguo)
  RB2  (80): Prof jornada no asignado en 8:30 ni 17:30
  RB3  (50): Distintos componentes del mismo curso en días distintos
  RB4  (50): Máximo 1 bloque del mismo componente por curso por día

Pesos configurables en PESOS al inicio del archivo.
"""
from __future__ import annotations

import copy
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from deap import base, creator, tools

from .blocks import MATRIZ_SOLAPAMIENTO, SET_ESTANDAR, TODOS_BLOQUES
from .models import DatosProblema, TipoProfesor, TipoReunion
from .solver_cpsat import disponibilidad_seccion

# ---------------------------------------------------------------------------
# Configuración de pesos
# ---------------------------------------------------------------------------

PESOS: dict[str, int] = {
    "RB1": 100,
    "RB2":  80,
    "RB3":  50,
    "RB4":  50,
}

# Preferencia por la grilla estándar: cada bloque helper (no estándar) usado suma
# esta penalización. Mantiene las clases en los horarios institucionales salvo que
# la disponibilidad del profesor obligue a un horario fuera de la grilla.
PESO_BLOQUE_HELPER = 40

CURSO_PROGRAMACION = "ING1103"

# ---------------------------------------------------------------------------
# Precómputos
# ---------------------------------------------------------------------------

def _hora_a_min(hora: str) -> int:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


_MIN_12_30 = _hora_a_min("12:30")
_HORAS_EXTREMAS = {"8:30", "17:30"}

_DIA_DEL_BLOQUE: list[str] = [b.dia.value for b in TODOS_BLOQUES]
_HORA_INICIO_DEL_BLOQUE: list[str] = [b.hora_inicio for b in TODOS_BLOQUES]
_HORA_FIN_DEL_BLOQUE: list[str] = [b.hora_fin for b in TODOS_BLOQUES]
_MIN_INICIO_BLOQUE: list[int] = [_hora_a_min(b.hora_inicio) for b in TODOS_BLOQUES]
_MIN_FIN_BLOQUE: list[int] = [_hora_a_min(b.hora_fin) for b in TODOS_BLOQUES]


# ---------------------------------------------------------------------------
# Contexto del GA
# ---------------------------------------------------------------------------

@dataclass
class GAContexto:
    reps: list[str]                           # sec_id del representante (uno por grupo)
    rep_n_blocks: list[int]                   # bloques necesarios por rep
    rep_es_ayud: list[bool]
    rep_prof: list[str]                       # rut_profesor
    rep_es_jornada: list[bool]
    rep_disponibles: list[list[int]]          # índices de bloques válidos por rep
    conflictos: list[set[int]]                # rep_idx → set de rep_idx conflictivos
    reps_por_curso: dict[str, dict[str, list[int]]]  # {codigo: {comp_str: [rep_idx, ...]}}
    rep_seccion_ids: list[list[str]]          # todos los sec_id del grupo del rep
    rep_es_prog_labt: list[bool]              # RB1: es ING1103-LABT
    datos: DatosProblema
    sec_by_id: dict[str, Any]


def construir_contexto(
    datos: DatosProblema,
    asignaciones: dict[str, list[int]],
) -> GAContexto:
    """Construye el contexto del GA a partir de la solución CP-SAT."""
    sec_by_id = {s.id: s for s in datos.secciones}

    # Cada sección es su propio representante. El paralelismo ya lo decidió CP-SAT
    # (secciones del mismo curso pueden compartir bloque o no); el GA conserva los
    # bloques por sección y optimiza las restricciones blandas.
    reps_list: list[str] = []
    reps_por_curso: dict[str, dict[str, list[int]]] = defaultdict(dict)
    rep_seccion_ids: list[list[str]] = []

    for sec_id in sorted(asignaciones):
        s = sec_by_id.get(sec_id)
        if not s:
            continue
        rep_idx = len(reps_list)
        reps_list.append(sec_id)
        reps_por_curso[s.codigo_curso].setdefault(s.componente.value, []).append(rep_idx)
        rep_seccion_ids.append([sec_id])

    n_reps = len(reps_list)

    # Atributos por rep
    rep_n_blocks: list[int] = []
    rep_es_ayud: list[bool] = []
    rep_prof: list[str] = []
    rep_es_jornada: list[bool] = []
    rep_disponibles: list[list[int]] = []
    rep_es_prog_labt: list[bool] = []

    for i, rep_id in enumerate(reps_list):
        s = sec_by_id[rep_id]
        rep_n_blocks.append(s.cantidad_bloques_necesarios)

        es_ayud = s.componente == TipoReunion.AYUD
        rep_es_ayud.append(es_ayud)
        rep_prof.append(s.rut_profesor)

        # RB2: penalizar si alguna sección del grupo es dictada por un prof jornada.
        # Solo cuenta si afecta_disponibilidad=True: una sección dictada por un TA
        # (AYUD, o LABT sin prof) no ata al profesor de cátedra a ese bloque.
        es_jornada = any(
            sec_by_id[sid].afecta_disponibilidad
            and datos.profesores.get(sec_by_id[sid].rut_profesor) is not None
            and datos.profesores[sec_by_id[sid].rut_profesor].tipo == TipoProfesor.JORNADA
            for sid in rep_seccion_ids[i]
        )
        rep_es_jornada.append(es_jornada)

        # Bloques disponibles para este rep: EXACTAMENTE el mismo dominio que usa CP-SAT
        # (disponibilidad_seccion ya filtra por duración 2h/3h, RD2 y RD7). Reutilizar la
        # misma función garantiza que el GA nunca mueva una sección fuera de lo permitido.
        rep_disponibles.append(sorted(disponibilidad_seccion(datos, s)))

        rep_es_prog_labt.append(
            s.codigo_curso == CURSO_PROGRAMACION and s.componente == TipoReunion.LABT
        )

    # Grafo de conflictos entre representantes
    conflictos: list[set[int]] = [set() for _ in range(n_reps)]

    def _add(ri: int, rj: int) -> None:
        conflictos[ri].add(rj)
        conflictos[rj].add(ri)

    # NRC: dentro de una MISMA sección (codigo, seccion), los componentes
    # CLAS-k/AYUD-k/LABT-k no se solapan (el alumno asiste a los tres).
    por_nrc: dict[tuple, list[int]] = defaultdict(list)
    for i, rep_id in enumerate(reps_list):
        s = sec_by_id[rep_id]
        por_nrc[(s.codigo_curso, str(s.seccion))].append(i)
    for idxs in por_nrc.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ri, rj = idxs[a], idxs[b]
                if sec_by_id[reps_list[ri]].componente != sec_by_id[reps_list[rj]].componente:
                    _add(ri, rj)

    # RD1: mismo (carrera, semestre), cursos distintos → no solapar
    for carrera in {car for c in datos.cursos.values() for car in c.semestres_por_carrera}:
        grupos_sem: dict[str, list[int]] = defaultdict(list)
        for i, rep_id in enumerate(reps_list):
            s = sec_by_id[rep_id]
            curso = datos.cursos.get(s.codigo_curso)
            if not curso:
                continue
            for sem in curso.semestres_por_carrera.get(carrera, set()):
                grupos_sem[sem].append(i)
        for sem_idxs in grupos_sem.values():
            for a in range(len(sem_idxs)):
                for b in range(a + 1, len(sem_idxs)):
                    ri, rj = sem_idxs[a], sem_idxs[b]
                    if sec_by_id[reps_list[ri]].codigo_curso == sec_by_id[reps_list[rj]].codigo_curso:
                        continue
                    _add(ri, rj)

    # RD3: mismo profesor real (afecta_disponibilidad) → no solapar, en cualquier rol.
    # Se agrupan TODAS las secciones (de todos los reps) por su profesor real y se
    # conecta cada par de reps que comparta profesor. Ya NO se excluye el mismo curso:
    #   - Dos LABT del mismo curso con la misma profesora (caso Biología) DEBEN no solapar.
    #   - Un mismo profesor que dicta LABT de un curso y CLAS de otro tampoco puede solapar.
    # Conectar el mismo par dos veces es inocuo (el grafo es un set).
    por_prof_set: dict[str, set[int]] = defaultdict(set)
    for i, sec_ids in enumerate(rep_seccion_ids):
        for sec_id in sec_ids:
            s = sec_by_id[sec_id]
            if s.afecta_disponibilidad and s.rut_profesor:
                por_prof_set[s.rut_profesor].add(i)
    for prof_idxs in por_prof_set.values():
        idxs = sorted(prof_idxs)
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                _add(idxs[a], idxs[b])

    # RD4: misma sala especial (CLAS/LABT) → no solapar, según capacidad física.
    #   capacidad == 1  → ningún par puede coincidir (incluido mismo curso).
    #   capacidad desconocida o > 1 → solo se conectan cursos distintos.
    # Nota: el grafo de conflictos es binario y no expresa "a lo más C secciones por
    # bloque". Para capacidad > 1 esto puede sub-restringir entre secciones del mismo
    # curso; la factibilidad de capacidad la garantiza CP-SAT (punto de partida del GA,
    # que sí modela RD4 exacto por sub-bloque) y el reporter señala cualquier exceso.
    cap = datos.capacidad_por_sala
    por_sala: dict[str, list[int]] = defaultdict(list)
    for i, rep_id in enumerate(reps_list):
        s = sec_by_id[rep_id]
        if s.componente == TipoReunion.AYUD:
            continue
        curso = datos.cursos.get(s.codigo_curso)
        if curso and curso.sala_especial:
            por_sala[curso.sala_especial].append(i)
    for sala, idxs in por_sala.items():
        capacidad = cap.get(sala)
        if capacidad is None:
            capacidad = 1   # desconocida → asumir 1 sala física (consistente con CP-SAT)
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ri, rj = idxs[a], idxs[b]
                mismo_curso = (
                    sec_by_id[reps_list[ri]].codigo_curso
                    == sec_by_id[reps_list[rj]].codigo_curso
                )
                if capacidad == 1:
                    _add(ri, rj)            # 1 sala física: nunca pueden coincidir
                elif not mismo_curso:
                    _add(ri, rj)            # cap>1: solo cursos distintos (aprox. binaria)

    return GAContexto(
        reps=reps_list,
        rep_n_blocks=rep_n_blocks,
        rep_es_ayud=rep_es_ayud,
        rep_prof=rep_prof,
        rep_es_jornada=rep_es_jornada,
        rep_disponibles=rep_disponibles,
        conflictos=conflictos,
        reps_por_curso=dict(reps_por_curso),
        rep_seccion_ids=rep_seccion_ids,
        rep_es_prog_labt=rep_es_prog_labt,
        datos=datos,
        sec_by_id=sec_by_id,
    )


# ---------------------------------------------------------------------------
# Encode / Decode
# ---------------------------------------------------------------------------

def encode(asignaciones: dict[str, list[int]], ctx: GAContexto) -> list[list[int]]:
    """CP-SAT asignaciones → cromosoma GA (lista de listas de índices de bloques)."""
    return [list(asignaciones[rep_id]) for rep_id in ctx.reps]


def decode(individuo: list[list[int]], ctx: GAContexto) -> dict[str, list[int]]:
    """Cromosoma GA → asignaciones completas (propaga bloques del rep a todo el grupo)."""
    result: dict[str, list[int]] = {}
    for i, bloques in enumerate(individuo):
        for sec_id in ctx.rep_seccion_ids[i]:
            result[sec_id] = list(bloques)
    return result


# ---------------------------------------------------------------------------
# Factibilidad
# ---------------------------------------------------------------------------

def _es_factible(
    rep_idx: int,
    nuevos_bloques: list[int],
    individuo: list[list[int]],
    ctx: GAContexto,
) -> bool:
    """True si asignar nuevos_bloques al rep_idx no viola ninguna restricción dura."""
    # Intra-sección: ningún par de bloques puede solaparse
    for k1 in range(len(nuevos_bloques)):
        for k2 in range(k1 + 1, len(nuevos_bloques)):
            if MATRIZ_SOLAPAMIENTO[nuevos_bloques[k1]][nuevos_bloques[k2]]:
                return False

    # RD7: AYUD solo desde las 12:30
    if ctx.rep_es_ayud[rep_idx]:
        for b in nuevos_bloques:
            if _MIN_INICIO_BLOQUE[b] < _MIN_12_30:
                return False

    # Conflictos con otros representantes (RD1, RD3, RD4, RC inter-comp)
    for j in ctx.conflictos[rep_idx]:
        for b1 in nuevos_bloques:
            for b2 in individuo[j]:
                if MATRIZ_SOLAPAMIENTO[b1][b2]:
                    return False

    return True


# ---------------------------------------------------------------------------
# Fitness
# ---------------------------------------------------------------------------

def calcular_fitness(individuo: list[list[int]], ctx: GAContexto) -> tuple[float]:
    """Calcula la penalización total (minimizar). Retorna (penalty,)."""
    penalty = 0.0

    # RB1: Labs de Programación consecutivos
    # Bloques de ING1103-LABT deben ser en el mismo día y adyacentes entre sí
    for i in range(len(ctx.reps)):
        if not ctx.rep_es_prog_labt[i]:
            continue
        bloques = individuo[i]
        if len(bloques) < 2:
            continue
        for k1 in range(len(bloques)):
            for k2 in range(k1 + 1, len(bloques)):
                b1, b2 = bloques[k1], bloques[k2]
                if _DIA_DEL_BLOQUE[b1] != _DIA_DEL_BLOQUE[b2]:
                    penalty += PESOS["RB1"]
                else:
                    adj = (_MIN_FIN_BLOQUE[b1] == _MIN_INICIO_BLOQUE[b2] or
                           _MIN_FIN_BLOQUE[b2] == _MIN_INICIO_BLOQUE[b1])
                    if not adj:
                        penalty += PESOS["RB1"]

    # RB2: Prof jornada no en extremos (8:30, 17:30)
    # Si múltiples secciones CLAS del mismo curso comparten bloque extremo, solo se
    # penaliza una vez (ya manejado: un rep por grupo cubre todas las secciones).
    for i in range(len(ctx.reps)):
        if not ctx.rep_es_jornada[i]:
            continue
        for b in individuo[i]:
            if _HORA_INICIO_DEL_BLOQUE[b] in _HORAS_EXTREMAS:
                penalty += PESOS["RB2"]
                break  # penalizar el rep una sola vez

    # RB3: Distintos componentes del mismo curso → días distintos.
    # comp_map = {comp_str: [rep_idx, ...]}. Penalizar días compartidos entre cada
    # par de reps de componentes DISTINTOS (cada sección LABT cuenta por separado).
    for comp_map in ctx.reps_por_curso.values():
        comps = list(comp_map.keys())
        for a in range(len(comps)):
            for b in range(a + 1, len(comps)):
                for ri in comp_map[comps[a]]:
                    for rj in comp_map[comps[b]]:
                        dias_a = {_DIA_DEL_BLOQUE[bk] for bk in individuo[ri]}
                        dias_b = {_DIA_DEL_BLOQUE[bk] for bk in individuo[rj]}
                        penalty += len(dias_a & dias_b) * PESOS["RB3"]

    # RB4: Máximo 1 bloque del mismo componente por curso por día
    for i in range(len(ctx.reps)):
        bloques = individuo[i]
        if len(bloques) < 2:
            continue
        cnt = Counter(_DIA_DEL_BLOQUE[b] for b in bloques)
        for count in cnt.values():
            if count > 1:
                penalty += (count - 1) * PESOS["RB4"]

    # Preferencia por la grilla estándar: penalizar cada bloque helper usado.
    for i in range(len(ctx.reps)):
        for b in individuo[i]:
            if b not in SET_ESTANDAR:
                penalty += PESO_BLOQUE_HELPER

    return (penalty,)


# ---------------------------------------------------------------------------
# Mutación
# ---------------------------------------------------------------------------

def mutate_ga(
    individuo: list[list[int]],
    ctx: GAContexto,
    n_intentos: int = 30,
) -> tuple:
    """Muta un representante elegido al azar buscando bloques factibles."""
    orden = list(range(len(ctx.reps)))
    random.shuffle(orden)

    for rep_idx in orden:
        disponibles = ctx.rep_disponibles[rep_idx]
        n = ctx.rep_n_blocks[rep_idx]
        if len(disponibles) < n:
            continue

        for _ in range(n_intentos):
            candidato = sorted(random.sample(disponibles, n))
            if _es_factible(rep_idx, candidato, individuo, ctx):
                individuo[rep_idx] = candidato
                return (individuo,)

    return (individuo,)


# ---------------------------------------------------------------------------
# Cruce
# ---------------------------------------------------------------------------

def cx_uniform_ga(
    ind1: list[list[int]],
    ind2: list[list[int]],
    ctx: GAContexto,
) -> tuple:
    """Cruce uniforme a nivel de representantes con verificación de factibilidad."""
    hijo1 = [list(g) for g in ind1]
    hijo2 = [list(g) for g in ind2]

    for i in range(len(ctx.reps)):
        if random.random() < 0.5:
            if _es_factible(i, ind2[i], hijo1, ctx):
                hijo1[i] = list(ind2[i])
            if _es_factible(i, ind1[i], hijo2, ctx):
                hijo2[i] = list(ind1[i])

    return hijo1, hijo2


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoGA:
    asignaciones: dict[str, list[int]]
    fitness_inicial: float
    fitness_final: float
    n_generaciones: int
    logbook: Any = None


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def ejecutar_ga(
    datos: DatosProblema,
    asignaciones_cpsat: dict[str, list[int]],
    n_generaciones: int = 200,
    pop_size: int = 40,
    cxpb: float = 0.5,
    mutpb: float = 0.4,
    seed: int = 42,
) -> ResultadoGA:
    """Ejecuta el GA de mejora de restricciones blandas."""
    random.seed(seed)

    ctx = construir_contexto(datos, asignaciones_cpsat)

    # Tipos DEAP — crear solo si no existen todavía en el módulo global
    if not hasattr(creator, "FitnessMin"):
        creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
    if not hasattr(creator, "Individual"):
        creator.create("Individual", list, fitness=creator.FitnessMin)

    toolbox = base.Toolbox()
    toolbox.register("evaluate", calcular_fitness, ctx=ctx)
    toolbox.register("mate",     cx_uniform_ga, ctx=ctx)
    toolbox.register("mutate",   mutate_ga, ctx=ctx)
    toolbox.register("select",   tools.selTournament, tournsize=3)
    toolbox.register("clone",    copy.deepcopy)

    # Población inicial:
    #   ind[0]   = solución CP-SAT intacta (punto de partida óptimo)
    #   ind[1..] = copias mutadas de esa solución (diversidad real, factibilidad garantizada)
    # Esto preserva la distribución balanceada que CP-SAT produce y permite al GA
    # explorar el vecindario desde múltiples puntos distintos.
    pop = []
    ind0 = creator.Individual(encode(asignaciones_cpsat, ctx))
    ind0.fitness.values = toolbox.evaluate(ind0)
    pop.append(ind0)

    for _ in range(1, pop_size):
        nuevo = toolbox.clone(ind0)
        toolbox.mutate(nuevo)
        del nuevo.fitness.values
        nuevo.fitness.values = toolbox.evaluate(nuevo)
        pop.append(nuevo)

    print(f"  Población inicial: 1 solución CP-SAT + {pop_size - 1} mutadas (total {pop_size})")

    fitness_inicial = pop[0].fitness.values[0]

    hof = tools.HallOfFame(1)
    hof.update(pop)

    stats = tools.Statistics(key=lambda ind: ind.fitness.values[0])
    stats.register("min", min)
    stats.register("avg", lambda vals: sum(vals) / len(vals))

    logbook = tools.Logbook()
    logbook.header = ["gen", "nevals", "min", "avg"]
    record = stats.compile(pop)
    logbook.record(gen=0, nevals=pop_size, **record)
    print(f"  Gen    0: min={record['min']:.0f}  avg={record['avg']:.0f}")

    # Bucle principal con elitismo (1 individuo preservado por generación)
    for gen in range(1, n_generaciones + 1):
        offspring = toolbox.select(pop, k=pop_size - 1)
        offspring = [toolbox.clone(ind) for ind in offspring]

        # Cruce
        for i in range(0, len(offspring) - 1, 2):
            if random.random() < cxpb:
                offspring[i][:], offspring[i + 1][:] = toolbox.mate(offspring[i], offspring[i + 1])
                del offspring[i].fitness.values
                del offspring[i + 1].fitness.values

        # Mutación
        for ind in offspring:
            if random.random() < mutpb:
                ind, = toolbox.mutate(ind)
                del ind.fitness.values

        # Re-evaluar individuos modificados
        invalid = [ind for ind in offspring if not ind.fitness.valid]
        for ind in invalid:
            ind.fitness.values = toolbox.evaluate(ind)

        # Elitismo: re-insertar el mejor de la generación anterior
        offspring.append(toolbox.clone(hof[0]))
        pop[:] = offspring
        hof.update(pop)

        record = stats.compile(pop)
        logbook.record(gen=gen, nevals=len(invalid), **record)
        if gen % 50 == 0 or gen == n_generaciones:
            print(f"  Gen {gen:4d}: min={record['min']:.0f}  avg={record['avg']:.0f}")

    return ResultadoGA(
        asignaciones=decode(hof[0], ctx),
        fitness_inicial=fitness_inicial,
        fitness_final=hof[0].fitness.values[0],
        n_generaciones=n_generaciones,
        logbook=logbook,
    )


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------

def imprimir_resultado_ga(resultado: ResultadoGA) -> None:
    print("=" * 60)
    print("RESULTADO GA")
    print("=" * 60)
    mejora = resultado.fitness_inicial - resultado.fitness_final
    pct = (mejora / resultado.fitness_inicial * 100) if resultado.fitness_inicial > 0 else 0
    print(f"Fitness inicial (CP-SAT): {resultado.fitness_inicial:.1f}")
    print(f"Fitness final   (GA):     {resultado.fitness_final:.1f}")
    print(f"Mejora:                   {mejora:.1f} ({pct:.1f}%)")
    print(f"Generaciones:             {resultado.n_generaciones}")
