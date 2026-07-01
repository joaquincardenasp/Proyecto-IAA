"""
test_solver_step6.py — Paso 6: RD3, RD4, RD7, todas las carreras.

Verifica:
  - 0 conflictos de profesor (RD3)
  - 0 conflictos de sala especial (RD4)
  - 0 AYUD asignadas antes de las 12:30 (RD7)
  - Todo lo validado en paso 5 sigue pasando

Ejecutar desde backend/:
    python tests/test_solver_step6.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.parser import cargar_datos
from app.core.solver_cpsat import (
    imprimir_resultado, resolver,
    verificar_topes, verificar_intra,
    verificar_rd3, verificar_rd4, verificar_rd7,
)
from app.core.blocks import TODOS_BLOQUES
from app.core.models import TipoReunion

INPUTS_DIR = Path(__file__).parent.parent / "inputs"
CARRERAS = ["Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA", "ICQ"]


def check(condicion: bool, mensaje: str) -> None:
    estado = "✓" if condicion else "✗ FALLO"
    print(f"  [{estado}] {mensaje}")
    if not condicion:
        raise AssertionError(f"FALLO: {mensaje}")


def test_step6(datos):
    print("\n--- test_step6 (RD3 + RD4 + RD7, todas las carreras) ---")

    resultado = resolver(datos, carreras=CARRERAS)
    imprimir_resultado(datos, resultado)

    # 1. Solver encuentra solución
    check(
        resultado.estado in ("OPTIMAL", "FEASIBLE"),
        f"Solver encontró solución (estado: {resultado.estado})",
    )

    # 2. Todas las secciones asignadas
    codigos_restringidos = {
        c.codigo for c in datos.cursos.values()
        if any(car in c.semestres_por_carrera for car in CARRERAS)
    }
    secciones_esperadas = [s for s in datos.secciones if s.codigo_curso in codigos_restringidos]
    check(
        len(resultado.asignaciones) == len(secciones_esperadas),
        f"Todas las secciones asignadas "
        f"({len(resultado.asignaciones)}/{len(secciones_esperadas)})",
    )

    # 3. Índices válidos
    n = len(TODOS_BLOQUES)
    check(
        all(0 <= idx < n for idxs in resultado.asignaciones.values() for idx in idxs),
        f"Todos los índices de bloque válidos [0, {n-1}]",
    )

    # 4. 0 solapamientos intra-sección
    intra = verificar_intra(resultado.asignaciones)
    check(len(intra) == 0, f"0 solapamientos intra-sección (hay {len(intra)})")

    # 5. 0 topes RD1 en cada carrera
    for carrera in CARRERAS:
        topes = verificar_topes(datos, resultado.asignaciones, carrera)
        check(len(topes) == 0, f"0 topes en {carrera} (hay {len(topes)})")

    # 6. Modelo a nivel de sección: secciones independientes (RC sync ya no aplica).
    check(len(verificar_intra(resultado.asignaciones)) == 0,
          "0 solapamientos intra-sección")

    # 7. RD3: 0 conflictos de profesor
    conflictos_rd3 = verificar_rd3(datos, resultado.asignaciones)
    check(len(conflictos_rd3) == 0,
          f"RD3: 0 conflictos de profesor (hay {len(conflictos_rd3)})")
    if conflictos_rd3:
        sec_by_id = {s.id: s for s in datos.secciones}
        for id1, id2 in conflictos_rd3[:5]:
            s1 = sec_by_id.get(id1)
            s2 = sec_by_id.get(id2)
            b1s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[id1]]
            b2s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[id2]]
            rut = s1.rut_profesor if s1 else "?"
            print(f"    Prof {rut}: {id1} {b1s} ↔ {id2} {b2s}")

    # 8. RD4: 0 conflictos de sala especial
    conflictos_rd4 = verificar_rd4(datos, resultado.asignaciones)
    check(len(conflictos_rd4) == 0,
          f"RD4: 0 conflictos de sala especial (hay {len(conflictos_rd4)})")
    if conflictos_rd4:
        for id1, id2, sala in conflictos_rd4[:5]:
            b1s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[id1]]
            b2s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[id2]]
            print(f"    Sala {sala}: {id1} {b1s} ↔ {id2} {b2s}")

    # 9. RD7: 0 AYUD antes de las 12:30
    viol_rd7 = verificar_rd7(datos, resultado.asignaciones)
    check(len(viol_rd7) == 0,
          f"RD7: 0 AYUD antes de las 12:30 (hay {len(viol_rd7)})")
    if viol_rd7:
        for sec_id, b in viol_rd7[:5]:
            print(f"    {sec_id} → {TODOS_BLOQUES[b]}")

    # 10. Informe: AYUD — distribución por hora de inicio
    print("\n  Distribución de bloques AYUD por hora inicio:")
    sec_by_id = {s.id: s for s in datos.secciones}
    from collections import defaultdict, Counter
    hora_counter: Counter = Counter()
    for sec_id, bloques in resultado.asignaciones.items():
        s = sec_by_id.get(sec_id)
        if s and s.componente == TipoReunion.AYUD:
            for b in bloques:
                hora_counter[TODOS_BLOQUES[b].hora_inicio] += 1
    for hora in sorted(hora_counter, key=lambda h: int(h.split(":")[0]) * 60 + int(h.split(":")[1])):
        print(f"    {hora}: {hora_counter[hora]} asignación(es)")

    print("\n  → step6 OK")
    return resultado


def main():
    print("Cargando datos desde", INPUTS_DIR)
    datos = cargar_datos(INPUTS_DIR)

    fallidos = []
    try:
        test_step6(datos)
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
        print("RESULTADO: PASO 6 VALIDADO ✓")


if __name__ == "__main__":
    main()
