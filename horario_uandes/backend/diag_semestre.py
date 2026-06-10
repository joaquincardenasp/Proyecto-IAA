"""
diag_semestre.py — Encuentra QUÉ datos hacen INFEASIBLE el modelo con RD2.

Premisa: estos datos produjeron un horario manual real, así que DEBE existir
una solución que respeta la disponibilidad. Si el modelo dice INFEASIBLE, hay
un error de interpretación. Este script lo localiza.

PARTE A — Auditoría del parseo de disponibilidad:
    Muestra, para varias filas, el texto CRUDO de las celdas LUNES-VIERNES
    y los bloques que el parser interpretó. Revela si el formato real coincide
    con lo que el parser asume (sub-bloques de 50 min).

PARTE B — Aislamiento por semestre:
    Resuelve cada semestre de Plan Común por separado (RD1 + RC + RD2 + RD7).
    Para el/los semestre(s) infactibles, lista cada curso, su profesor y los
    bloques en que el profesor está disponible — para ver el conflicto a ojo.

Ejecutar desde backend/:
    python diag_semestre.py
"""
import sys
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from ortools.sat.python import cp_model

from app.core.parser import (
    cargar_datos, _mapear_columnas, _DISP_CAMPOS,
    _parse_subblocks_disp, _subblocks_a_bloques, _get, _str, _normalizar_rut,
)
from app.core.blocks import TODOS_BLOQUES, N_BLOQUES, MATRIZ_SOLAPAMIENTO, SET_ESTANDAR
from app.core.models import TipoReunion

INPUTS_DIR = Path(__file__).parent / "inputs"


def bloque_str(b: int) -> str:
    bl = TODOS_BLOQUES[b]
    marca = "" if bl.es_estandar else "*"
    return f"{bl.dia.value} {bl.hora_inicio}-{bl.hora_fin}{marca}"


# ═══════════════════════════════════════════════════════════════════════════
# PARTE A — Auditoría del parseo de disponibilidad
# ═══════════════════════════════════════════════════════════════════════════

def auditar_parseo():
    print("=" * 70)
    print("PARTE A — DISPONIBILIDAD: texto crudo vs bloques interpretados")
    print("=" * 70)

    candidatos = sorted(INPUTS_DIR.glob("[Mm]aestro*.xlsx"))
    xl = pd.ExcelFile(candidatos[0])
    df = xl.parse("MAESTRO", header=0)
    cols = _mapear_columnas(df)

    mostradas = 0
    for _, row in df.iterrows():
        if _str(_get(row, cols["MANDANTE"])).upper() != "SI":
            continue
        rut1 = _normalizar_rut(_get(row, cols["RUT_PROF1"]))
        if not rut1:
            continue

        # Texto crudo por día
        crudos = {}
        disp_por_dia = {}
        for campo, dia in _DISP_CAMPOS:
            raw = _str(_get(row, cols.get(campo)))
            if raw:
                crudos[dia] = raw
                mins = _parse_subblocks_disp(raw)
                if mins:
                    disp_por_dia[dia] = mins
        if not crudos:
            continue

        bloques = _subblocks_a_bloques(disp_por_dia)
        codigo = _str(_get(row, cols["CODIGO"]))
        print(f"\n  {codigo} — prof {rut1}")
        for dia, raw in crudos.items():
            print(f"    {dia} crudo: {raw!r}")
        print(f"    → bloques interpretados ({len(bloques)}): "
              f"{[bloque_str(b) for b in sorted(bloques)]}")

        mostradas += 1
        if mostradas >= 10:
            break

    print("\n  (* = bloque helper, fuera de la grilla estándar)")
    print("  Revisa: ¿el texto crudo son sub-bloques de 50 min separados por coma?")
    print("  Si una celda dice '8:30-10:20' (bloque de 2h), el parser solo lee 8:30")
    print("  y NO acreditaría el bloque completo → disponibilidad subestimada.\n")


# ═══════════════════════════════════════════════════════════════════════════
# PARTE B — Aislamiento por semestre
# ═══════════════════════════════════════════════════════════════════════════

_PARES_SOLAPAN = [(i, j) for i in range(N_BLOQUES) for j in range(N_BLOQUES)
                  if MATRIZ_SOLAPAMIENTO[i][j]]
_MIN_12_30 = 12 * 60 + 30
_PROHIBIDOS_AYUD = [i for i, b in enumerate(TODOS_BLOQUES)
                    if int(b.hora_inicio.split(":")[0]) * 60 + int(b.hora_inicio.split(":")[1]) < _MIN_12_30]


def _disp_de(datos, s):
    """Bloques disponibles para una sección (igual lógica que el solver)."""
    es_ayud = s.componente == TipoReunion.AYUD
    base = [b for b in range(N_BLOQUES)
            if not es_ayud or b not in _PROHIBIDOS_AYUD]
    prof = datos.profesores.get(s.rut_profesor) if s.rut_profesor else None
    tiene = s.afecta_disponibilidad and prof is not None and bool(prof.disponibilidad)
    if tiene:
        return [b for b in base if b in prof.disponibilidad]
    return [b for b in base if b in SET_ESTANDAR]


def resolver_semestre(datos, secs):
    """Mini-modelo: intra + RC(CLAS/AYUD sync) + RD1(todos los pares) + RD2 + RD7."""
    model = cp_model.CpModel()
    x = {}
    for s in secs:
        dom = _disp_de(datos, s)
        if not dom:
            return "INFEASIBLE", s.id  # sección sin ningún bloque → culpable directo
        x[s.id] = [model.NewIntVarFromDomain(cp_model.Domain.FromValues(dom), f"{s.id}_{k}")
                   for k in range(s.cantidad_bloques_necesarios)]

    # intra
    for s in secs:
        v = x[s.id]
        for k1 in range(len(v)):
            for k2 in range(k1 + 1, len(v)):
                model.AddForbiddenAssignments([v[k1], v[k2]], _PARES_SOLAPAN)

    # RC: sincronizar CLAS y AYUD del mismo curso; LABT independiente
    porcc = defaultdict(list)
    for s in secs:
        porcc[(s.codigo_curso, s.componente)].append(s)
    for (cod, comp), grupo in porcc.items():
        if comp in (TipoReunion.CLAS, TipoReunion.AYUD) and len(grupo) > 1:
            base = x[grupo[0].id]
            for s in grupo[1:]:
                for k, var in enumerate(base):
                    model.Add(var == x[s.id][k])

    # RD1: cursos distintos no se solapan (todos en el mismo semestre)
    ids = [s.id for s in secs]
    sec_by_id = {s.id: s for s in secs}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if sec_by_id[ids[i]].codigo_curso == sec_by_id[ids[j]].codigo_curso:
                continue
            for v1 in x[ids[i]]:
                for v2 in x[ids[j]]:
                    model.AddForbiddenAssignments([v1, v2], _PARES_SOLAPAN)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0
    st = solver.Solve(model)
    return ("FACTIBLE" if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else "INFEASIBLE"), None


def aislar_por_semestre():
    print("=" * 70)
    print("PARTE B — FACTIBILIDAD POR SEMESTRE (Plan Común, RD1+RC+RD2+RD7)")
    print("=" * 70)

    datos = cargar_datos(INPUTS_DIR)

    # Agrupar secciones por semestre de Plan Común
    por_sem = defaultdict(list)
    for s in datos.secciones:
        curso = datos.cursos.get(s.codigo_curso)
        if not curso:
            continue
        for sem in curso.semestres_por_carrera.get("Plan Común", set()):
            por_sem[sem].append(s)

    infactibles = []
    for sem in sorted(por_sem.keys()):
        secs = por_sem[sem]
        estado, culpable = resolver_semestre(datos, secs)
        cursos_distintos = len({s.codigo_curso for s in secs})
        print(f"\n  Semestre {sem}: {cursos_distintos} cursos, {len(secs)} secciones → {estado}")
        if culpable:
            print(f"    *** Sección {culpable} no tiene NINGÚN bloque disponible ***")
        if estado == "INFEASIBLE":
            infactibles.append(sem)

    # Detalle de los semestres infactibles
    for sem in infactibles:
        print("\n" + "=" * 70)
        print(f"DETALLE SEMESTRE {sem} (INFEASIBLE) — cursos, profesor y disponibilidad")
        print("=" * 70)
        secs = por_sem[sem]
        # Un representante CLAS por curso
        vistos = set()
        for s in sorted(secs, key=lambda s: (s.codigo_curso, s.componente.value)):
            if s.componente != TipoReunion.CLAS:
                continue
            if s.codigo_curso in vistos:
                continue
            vistos.add(s.codigo_curso)
            curso = datos.cursos.get(s.codigo_curso)
            prof = datos.profesores.get(s.rut_profesor)
            dom = _disp_de(datos, s)
            nombre = prof.nombre if prof else (s.rut_profesor or "(sin prof)")
            print(f"\n  {s.codigo_curso} {curso.titulo if curso else ''} "
                  f"({s.cantidad_bloques_necesarios} bloque/s)")
            print(f"    Profesor: {nombre}")
            print(f"    Disponible en {len(dom)} bloque(s): {[bloque_str(b) for b in dom]}")


if __name__ == "__main__":
    auditar_parseo()
    print("\n")
    aislar_por_semestre()
