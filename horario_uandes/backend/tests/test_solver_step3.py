"""
test_solver_step3.py — Paso 3: CP-SAT Plan Común + ICI.

Valida que la solución tiene 0 topes en Plan Común y en ICI.
Las menciones "9a", "9f" se tratan como semestres distintos
(no hay topes entre alumnos de distintas menciones).

Ejecutar desde backend/:
    python tests/test_solver_step3.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.parser import cargar_datos
from app.core.solver_cpsat import imprimir_resultado, resolver, verificar_topes

INPUTS_DIR = Path(__file__).parent.parent / "inputs"
CARRERAS = ["Plan Común", "ICI"]


def check(condicion: bool, mensaje: str) -> None:
    estado = "✓" if condicion else "✗ FALLO"
    print(f"  [{estado}] {mensaje}")
    if not condicion:
        raise AssertionError(f"FALLO: {mensaje}")


def test_step3_plan_comun_ici(datos):
    print("\n--- test_step3_plan_comun_ici ---")

    resultado = resolver(datos, carreras=CARRERAS)
    imprimir_resultado(datos, resultado)

    # 1. El solver debe encontrar solución
    check(
        resultado.estado in ("OPTIMAL", "FEASIBLE"),
        f"Solver encontró solución (estado: {resultado.estado})",
    )

    # 2. Todas las secciones de cursos restringidos deben estar asignadas
    codigos_restringidos = {
        c.codigo for c in datos.cursos.values()
        if any(car in c.semestres_por_carrera for car in CARRERAS)
    }
    # Se excluyen las de distribución indefinida (3h sin definir): no se programan.
    secciones_esperadas = [s for s in datos.secciones
                           if s.codigo_curso in codigos_restringidos and not s.distribucion_indefinida]
    check(
        len(resultado.asignaciones) == len(secciones_esperadas),
        f"Todas las secciones programables asignadas "
        f"({len(resultado.asignaciones)}/{len(secciones_esperadas)})",
    )

    # 3. Índices de bloque en rango válido
    from app.core.blocks import TODOS_BLOQUES
    n = len(TODOS_BLOQUES)
    check(
        all(0 <= idx < n for idxs in resultado.asignaciones.values() for idx in idxs),
        f"Todos los bloques tienen índice válido [0, {n-1}]",
    )

    # 4. CERO topes en cada carrera
    for carrera in CARRERAS:
        topes = verificar_topes(datos, resultado.asignaciones, carrera)
        check(len(topes) == 0, f"0 topes en {carrera} (hay {len(topes)})")

        if topes:
            print(f"\n  Topes en {carrera} (primeros 10):")
            from app.core.blocks import TODOS_BLOQUES
            for s1_id, s2_id, sem in topes[:10]:
                b1s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[s1_id]]
                b2s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[s2_id]]
                print(f"    SEM {sem}: {s1_id} {b1s} ↔ {s2_id} {b2s}")

    # 5. Modelo a nivel de sección: las secciones de un curso son independientes
    #    (paralelas o no, lo decide el solver). La antigua "sincronización RC" ya no
    #    aplica; lo relevante es la ausencia de topes RD1, verificada arriba.

    print("  → step3_plan_comun_ici OK")


def imprimir_detalle_ici(datos, resultado):
    """Imprime el horario ICI agrupado por semestre."""
    if not resultado.asignaciones:
        return

    from collections import defaultdict
    from app.core.blocks import TODOS_BLOQUES

    sec_by_id = {s.id: s for s in datos.secciones}
    por_semestre: dict[str, list] = defaultdict(list)

    for sec_id, bloques_idx in resultado.asignaciones.items():
        s = sec_by_id.get(sec_id)
        if not s:
            continue
        curso = datos.cursos.get(s.codigo_curso)
        if not curso:
            continue
        for sem in curso.semestres_por_carrera.get("ICI", set()):
            bloques_str = ", ".join(
                f"{TODOS_BLOQUES[b].dia.value} {TODOS_BLOQUES[b].hora_inicio}-{TODOS_BLOQUES[b].hora_fin}"
                for b in bloques_idx
            )
            por_semestre[sem].append(
                (sem, s.codigo_curso, s.seccion, s.componente.value, bloques_str)
            )

    print("\n=== HORARIO ICI (por semestre) ===")
    for sem in sorted(por_semestre, key=lambda s: (len(s), s)):
        print(f"\nSemestre {sem}:")
        rows = sorted(por_semestre[sem], key=lambda r: (r[1], r[3], r[4]))
        for _, codigo, seccion, comp, bloque in rows:
            print(f"  {codigo}-{seccion} [{comp}]  →  {bloque}")


def main():
    print("Cargando datos desde", INPUTS_DIR)
    datos = cargar_datos(INPUTS_DIR)

    fallidos = []
    try:
        resultado = resolver(datos, carreras=CARRERAS)
        test_step3_plan_comun_ici(datos)
        imprimir_detalle_ici(datos, resultado)
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
        print("RESULTADO: PASO 3 VALIDADO ✓")


if __name__ == "__main__":
    main()
