"""
diag_conflicto.py — Encuentra el conflicto MÍNIMO en un semestre infactible.

Prueba capa por capa (CLAS / +AYUD / +LABT) y quita cursos/componentes uno a uno
para identificar la combinación exacta que vuelve INFEASIBLE el modelo.

Ejecutar desde backend/:
    python diag_conflicto.py 2        # analiza el semestre 2 de Plan Común
"""
import sys
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from ortools.sat.python import cp_model

from app.core.parser import cargar_datos
from app.core.blocks import TODOS_BLOQUES, N_BLOQUES, MATRIZ_SOLAPAMIENTO, SET_ESTANDAR
from app.core.models import TipoReunion

INPUTS_DIR = Path(__file__).parent / "inputs"
SEM = sys.argv[1] if len(sys.argv) > 1 else "2"

_PARES = [(i, j) for i in range(N_BLOQUES) for j in range(N_BLOQUES)
          if MATRIZ_SOLAPAMIENTO[i][j]]
_MIN_1230 = 12 * 60 + 30
def _min(h): return int(h.split(":")[0]) * 60 + int(h.split(":")[1])
_PROHIB_AYUD = [i for i, b in enumerate(TODOS_BLOQUES) if _min(b.hora_inicio) < _MIN_1230]


def bs(b):
    bl = TODOS_BLOQUES[b]
    return f"{bl.dia.value} {bl.hora_inicio}{'' if bl.es_estandar else '*'}"


def dom(datos, s):
    es_ayud = s.componente == TipoReunion.AYUD
    base = [b for b in range(N_BLOQUES) if not es_ayud or b not in _PROHIB_AYUD]
    prof = datos.profesores.get(s.rut_profesor) if s.rut_profesor else None
    if s.afecta_disponibilidad and prof and prof.disponibilidad:
        return [b for b in base if b in prof.disponibilidad]
    return [b for b in base if b in SET_ESTANDAR]


def factible(datos, secs, sync_rc=True):
    model = cp_model.CpModel()
    x = {}
    for s in secs:
        d = dom(datos, s)
        if not d:
            return False, f"{s.id} sin bloques"
        x[s.id] = [model.NewIntVarFromDomain(cp_model.Domain.FromValues(d), f"{s.id}_{k}")
                   for k in range(s.cantidad_bloques_necesarios)]
    # intra
    for s in secs:
        v = x[s.id]
        for k1 in range(len(v)):
            for k2 in range(k1 + 1, len(v)):
                model.AddForbiddenAssignments([v[k1], v[k2]], _PARES)
    # RC sync CLAS/AYUD
    if sync_rc:
        g = defaultdict(list)
        for s in secs:
            g[(s.codigo_curso, s.componente)].append(s)
        for (cod, comp), grp in g.items():
            if comp in (TipoReunion.CLAS, TipoReunion.AYUD) and len(grp) > 1:
                base = x[grp[0].id]
                for s in grp[1:]:
                    for k, var in enumerate(base):
                        model.Add(var == x[s.id][k])
    # RD1 entre cursos distintos
    ids = [s.id for s in secs]
    sbi = {s.id: s for s in secs}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if sbi[ids[i]].codigo_curso == sbi[ids[j]].codigo_curso:
                continue
            for v1 in x[ids[i]]:
                for v2 in x[ids[j]]:
                    model.AddForbiddenAssignments([v1, v2], _PARES)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15.0
    st = solver.Solve(model)
    return st in (cp_model.OPTIMAL, cp_model.FEASIBLE), None


def main():
    datos = cargar_datos(INPUTS_DIR)
    secs = [s for s in datos.secciones
            if SEM in datos.cursos.get(s.codigo_curso, type("x", (), {"semestres_por_carrera": {}})()).semestres_por_carrera.get("Plan Común", set())]

    cursos = sorted({s.codigo_curso for s in secs})
    print("\n" + "=" * 64)
    print(f"CONFLICTO EN SEMESTRE {SEM} — {len(cursos)} cursos, {len(secs)} secciones")
    print("=" * 64)
    print(f"Cursos: {cursos}")

    clas = [s for s in secs if s.componente == TipoReunion.CLAS]
    ayud = [s for s in secs if s.componente == TipoReunion.AYUD]
    labt = [s for s in secs if s.componente == TipoReunion.LABT]
    print(f"\nSecciones: CLAS={len(clas)}  AYUD={len(ayud)}  LABT={len(labt)}")

    # Capa por capa
    print("\n── Factibilidad por capa ──")
    f1, _ = factible(datos, clas)
    print(f"  Solo CLAS:          {'✓ FACTIBLE' if f1 else '✗ INFEASIBLE'}")
    f2, _ = factible(datos, clas + ayud)
    print(f"  CLAS + AYUD:        {'✓ FACTIBLE' if f2 else '✗ INFEASIBLE'}")
    f3, _ = factible(datos, clas + ayud + labt)
    print(f"  CLAS + AYUD + LABT: {'✓ FACTIBLE' if f3 else '✗ INFEASIBLE'}")

    # Si CLAS solo ya es infactible, buscar el subconjunto mínimo de cursos
    capa = clas if not f1 else (clas + ayud if not f2 else clas + ayud + labt)
    nombre_capa = "CLAS" if not f1 else ("CLAS+AYUD" if not f2 else "CLAS+AYUD+LABT")
    print(f"\n── Buscando cursos críticos en la capa {nombre_capa} ──")
    base_ok, _ = factible(datos, capa)
    if base_ok:
        print("  (esta capa es factible; el conflicto aparece en una capa superior)")
    else:
        for cod in cursos:
            reducido = [s for s in capa if s.codigo_curso != cod]
            if not reducido:
                continue
            fr, _ = factible(datos, reducido)
            marca = "→ quitarlo lo vuelve FACTIBLE  ⇐ CRÍTICO" if fr else "sigue infactible"
            print(f"  Sin {cod}: {marca}")

    # Detalle de los CLAS con disponibilidad y sus dominios
    print(f"\n── Dominios CLAS (semestre {SEM}) ──")
    vistos = set()
    for s in sorted(clas, key=lambda s: s.codigo_curso):
        if s.codigo_curso in vistos:
            continue
        vistos.add(s.codigo_curso)
        curso = datos.cursos.get(s.codigo_curso)
        d = dom(datos, s)
        print(f"  {s.codigo_curso} {curso.titulo if curso else ''} "
              f"({s.cantidad_bloques_necesarios} bloque/s, {len(d)} disponibles): "
              f"{[bs(b) for b in d][:14]}{' …' if len(d) > 14 else ''}")


if __name__ == "__main__":
    main()
