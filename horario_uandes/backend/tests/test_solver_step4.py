"""
test_solver_step4.py — Paso 4: CP-SAT Plan Común + ICI + IOC (+ más carreras progresivamente).

Ejecutar desde backend/:
    python tests/test_solver_step4.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.parser import cargar_datos
from app.core.solver_cpsat import resolver_por_partes, verificar_topes
from app.core.blocks import TODOS_BLOQUES

INPUTS_DIR = Path(__file__).parent.parent / "inputs"
CARRERAS = ["Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA", "ICQ"]


def check(condicion: bool, mensaje: str) -> None:
    estado = "✓" if condicion else "✗ FALLO"
    print(f"  [{estado}] {mensaje}")
    if not condicion:
        raise AssertionError(f"FALLO: {mensaje}")


def test_step4(datos, carreras: list[str]):
    print(f"\n--- test_step4 ({', '.join(carreras)}) ---")

    # Nuevo paradigma: el sistema entrega el mejor horario posible sin relajar duras.
    # El modelo completo puede no ser factible (→ PARCIAL); lo que importa es que TODO lo
    # colocado respete las restricciones duras (verificado más abajo).
    resultado = resolver_por_partes(datos, carreras=carreras)
    print(f"  estado={resultado.estado}  colocadas={len(resultado.asignaciones)}  "
          f"bloqueadas={len(resultado.bloqueadas)}")

    check(
        resultado.estado in ("FACTIBLE", "PARCIAL"),
        f"El sistema entregó un horario (estado: {resultado.estado})",
    )

    codigos_restringidos = {
        c.codigo for c in datos.cursos.values()
        if any(car in c.semestres_por_carrera for car in carreras)
    }
    secciones_esperadas = [s for s in datos.secciones if s.codigo_curso in codigos_restringidos]
    check(
        0 < len(resultado.asignaciones) <= len(secciones_esperadas),
        f"Secciones colocadas dentro del rango esperado "
        f"({len(resultado.asignaciones)}/{len(secciones_esperadas)})",
    )

    n = len(TODOS_BLOQUES)
    check(
        all(0 <= idx < n for idxs in resultado.asignaciones.values() for idx in idxs),
        f"Todos los bloques tienen índice válido [0, {n-1}]",
    )

    for carrera in carreras:
        topes = verificar_topes(datos, resultado.asignaciones, carrera)
        check(len(topes) == 0, f"0 topes en {carrera} (hay {len(topes)})")

        if topes:
            print(f"\n  Topes en {carrera} (primeros 10):")
            for s1_id, s2_id, sem in topes[:10]:
                b1s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[s1_id]]
                b2s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[s2_id]]
                print(f"    SEM {sem}: {s1_id} {b1s} ↔ {s2_id} {b2s}")

    # Modelo a nivel de sección: secciones independientes (la sincronización RC ya no
    # aplica). Lo relevante es la ausencia de topes RD1, verificada arriba.

    print(f"  → step4 ({', '.join(carreras)}) OK")
    return resultado


def imprimir_detalle_carrera(datos, resultado, carrera: str):
    """Imprime el horario de una carrera agrupado por semestre."""
    if not resultado.asignaciones:
        return

    from collections import defaultdict
    sec_by_id = {s.id: s for s in datos.secciones}
    por_semestre: dict[str, list] = defaultdict(list)

    for sec_id, bloques_idx in resultado.asignaciones.items():
        s = sec_by_id.get(sec_id)
        if not s:
            continue
        curso = datos.cursos.get(s.codigo_curso)
        if not curso:
            continue
        for sem in curso.semestres_por_carrera.get(carrera, set()):
            bloques_str = ", ".join(
                f"{TODOS_BLOQUES[b].dia.value} {TODOS_BLOQUES[b].hora_inicio}-{TODOS_BLOQUES[b].hora_fin}"
                for b in bloques_idx
            )
            por_semestre[sem].append(
                (sem, s.codigo_curso, s.seccion, s.componente.value, bloques_str)
            )

    print(f"\n=== HORARIO {carrera} (por semestre) ===")
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
        resultado = test_step4(datos, CARRERAS)
        imprimir_detalle_carrera(datos, resultado, "ICQ")
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
        print(f"RESULTADO: PASO 4 ({', '.join(CARRERAS)}) VALIDADO ✓")


if __name__ == "__main__":
    main()
