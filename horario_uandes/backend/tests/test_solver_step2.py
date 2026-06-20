"""
test_solver_step2.py — Paso 2: CP-SAT solo Plan Común.

Valida que la solución tiene 0 topes entre cursos de un mismo semestre
de Plan Común.

Ejecutar desde backend/:
    python tests/test_solver_step2.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.parser import cargar_datos
from app.core.solver_cpsat import (
    imprimir_resultado,
    resolver,
    verificar_topes,
    verificar_rd3,
    verificar_rd4,
)
from app.core.blocks import TODOS_BLOQUES, MATRIZ_SOLAPAMIENTO
from app.core.models import TipoReunion

INPUTS_DIR = Path(__file__).parent.parent / "inputs"


def check(condicion: bool, mensaje: str) -> None:
    estado = "✓" if condicion else "✗ FALLO"
    print(f"  [{estado}] {mensaje}")
    if not condicion:
        raise AssertionError(f"FALLO: {mensaje}")


# ---------------------------------------------------------------------------
# Test principal
# ---------------------------------------------------------------------------

def test_step2_plan_comun(datos):
    print("\n--- test_step2_plan_comun ---")

    resultado = resolver(datos, carreras=["Plan Común"])
    imprimir_resultado(datos, resultado)

    # 1. El solver debe encontrar solución
    check(
        resultado.estado in ("OPTIMAL", "FEASIBLE"),
        f"Solver encontró solución (estado: {resultado.estado})",
    )

    # 2. Todas las secciones de cursos Plan Común deben estar asignadas
    codigos_pc = {
        c.codigo for c in datos.cursos.values()
        if "Plan Común" in c.semestres_por_carrera
    }
    secciones_pc = [s for s in datos.secciones if s.codigo_curso in codigos_pc]
    check(
        len(resultado.asignaciones) == len(secciones_pc),
        f"Todas las secciones Plan Común asignadas "
        f"({len(resultado.asignaciones)}/{len(secciones_pc)})",
    )

    # 3. Los índices de bloque deben estar en rango válido
    n = len(TODOS_BLOQUES)
    check(
        all(0 <= idx < n for idxs in resultado.asignaciones.values() for idx in idxs),
        f"Todos los bloques asignados tienen índice válido [0, {n-1}]",
    )

    # 4. CERO topes en Plan Común
    topes = verificar_topes(datos, resultado.asignaciones, "Plan Común")
    check(len(topes) == 0, f"0 topes en Plan Común (hay {len(topes)})")

    if topes:
        print("\n  Topes encontrados (primeros 10):")
        for s1_id, s2_id, sem in topes[:10]:
            b1s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[s1_id]]
            b2s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[s2_id]]
            print(f"    SEM {sem}: {s1_id} {b1s} ↔ {s2_id} {b2s}")

    # 5. CLAS/AYUD del mismo curso PUEDEN solaparse (secciones paralelas).
    #    LABT del mismo curso NO necesariamente: son independientes y las limitan
    #    el profesor (RD3) y las salas (RD4). Distinguimos ambos casos.
    sec_by_id = {s.id: s for s in datos.secciones}
    clas_ayud_solapan: list[tuple[str, str]] = []
    labt_mismo_curso_solapan: list[tuple[str, str]] = []
    ids = list(resultado.asignaciones.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            s1 = sec_by_id.get(ids[i])
            s2 = sec_by_id.get(ids[j])
            if not s1 or not s2 or s1.codigo_curso != s2.codigo_curso:
                continue
            if s1.componente != s2.componente:
                continue
            bloques1 = resultado.asignaciones[ids[i]]
            bloques2 = resultado.asignaciones[ids[j]]
            if not any(MATRIZ_SOLAPAMIENTO[b1][b2] for b1 in bloques1 for b2 in bloques2):
                continue
            if s1.componente == TipoReunion.LABT:
                labt_mismo_curso_solapan.append((ids[i], ids[j]))
            else:
                clas_ayud_solapan.append((ids[i], ids[j]))

    print(f"\n  CLAS/AYUD mismo curso solapadas: {len(clas_ayud_solapan)} (permitido, paralelismo)")
    print(f"  LABT mismo curso solapadas: {len(labt_mismo_curso_solapan)} "
          f"(permitido solo si hay salas suficientes y profesores distintos)")

    # 6. RD3: ningún profesor (afecta_disponibilidad) dicta dos secciones a la vez.
    #    Cubre el caso de dos LABT del mismo curso con la misma profesora.
    conf_rd3 = verificar_rd3(datos, resultado.asignaciones)
    check(len(conf_rd3) == 0, f"0 conflictos de profesor RD3 (hay {len(conf_rd3)})")
    if conf_rd3:
        print("\n  Conflictos RD3 (primeros 5):")
        for id1, id2 in conf_rd3[:5]:
            print(f"    {id1} ↔ {id2}")

    # 7. RD4: ninguna sala especial excede su capacidad física.
    conf_rd4 = verificar_rd4(datos, resultado.asignaciones)
    check(len(conf_rd4) == 0, f"0 conflictos de sala RD4 (hay {len(conf_rd4)})")
    if conf_rd4:
        print("\n  Conflictos RD4 (primeros 5):")
        for id1, id2, sala in conf_rd4[:5]:
            print(f"    {id1} ↔ {id2} en '{sala}'")

    print("  → step2_plan_comun OK")


# ---------------------------------------------------------------------------
# Resumen de la solución
# ---------------------------------------------------------------------------

def imprimir_detalle_plan_comun(datos, resultado):
    """Imprime el horario asignado agrupado por semestre Plan Común."""
    if not resultado.asignaciones:
        return

    sec_by_id = {s.id: s for s in datos.secciones}

    # Agrupar por semestre
    from collections import defaultdict
    por_semestre: dict[str, list] = defaultdict(list)
    for sec_id, bloques_idx in resultado.asignaciones.items():
        s = sec_by_id.get(sec_id)
        if not s:
            continue
        curso = datos.cursos.get(s.codigo_curso)
        if not curso:
            continue
        for sem in curso.semestres_por_carrera.get("Plan Común", set()):
            bloques_str = ", ".join(
                f"{TODOS_BLOQUES[b].dia.value} {TODOS_BLOQUES[b].hora_inicio}-{TODOS_BLOQUES[b].hora_fin}"
                for b in bloques_idx
            )
            por_semestre[sem].append(
                (sem, s.codigo_curso, s.seccion, s.componente.value, bloques_str)
            )

    print("\n=== HORARIO PLAN COMÚN (por semestre) ===")
    for sem in sorted(por_semestre, key=lambda s: (len(s), s)):
        print(f"\nSemestre {sem}:")
        rows = sorted(por_semestre[sem], key=lambda r: (r[1], r[3], r[4]))
        for _, codigo, seccion, comp, bloque in rows:
            print(f"  {codigo}-{seccion} [{comp}]  →  {bloque}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    print("Cargando datos desde", INPUTS_DIR)
    datos = cargar_datos(INPUTS_DIR)

    fallidos = []
    try:
        test_step2_plan_comun(datos)
        imprimir_detalle_plan_comun(datos, resolver(datos, carreras=["Plan Común"]))
    except AssertionError as e:
        fallidos.append(str(e))
    except Exception as e:
        fallidos.append(f"ERROR inesperado: {e}")
        import traceback
        traceback.print_exc()

    print()
    if fallidos:
        print(f"RESULTADO: {len(fallidos)} test(s) FALLARON:")
        for msg in fallidos:
            print(f"  ✗ {msg}")
        sys.exit(1)
    else:
        print("RESULTADO: PASO 2 VALIDADO ✓")


if __name__ == "__main__":
    main()
