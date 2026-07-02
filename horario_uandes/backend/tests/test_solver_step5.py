"""
test_solver_step5.py — Paso 5: múltiples bloques por sección, todas las carreras.

Verifica:
  - Cada sección recibe exactamente cantidad_bloques_necesarios bloques
  - 0 solapamientos intra-sección
  - 0 topes RD1 en todas las carreras
  - ING1100-CLAS tiene exactamente 4 bloques asignados

Ejecutar desde backend/:
    python tests/test_solver_step5.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.parser import cargar_datos
from app.core.solver_cpsat import (
    resolver_por_partes,
    verificar_topes, verificar_intra,
)
from app.core.blocks import TODOS_BLOQUES, MATRIZ_SOLAPAMIENTO
from app.core.models import TipoReunion

INPUTS_DIR = Path(__file__).parent.parent / "inputs"
CARRERAS = ["Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA", "ICQ"]


def check(condicion: bool, mensaje: str) -> None:
    estado = "✓" if condicion else "✗ FALLO"
    print(f"  [{estado}] {mensaje}")
    if not condicion:
        raise AssertionError(f"FALLO: {mensaje}")


def test_step5(datos):
    print("\n--- test_step5 (todas las carreras, múltiples bloques) ---")

    resultado = resolver_por_partes(datos, carreras=CARRERAS)
    print(f"  estado={resultado.estado}  colocadas={len(resultado.asignaciones)}  "
          f"bloqueadas={len(resultado.bloqueadas)}")

    # 1. El sistema entrega un horario (completo o parcial), sin relajar duras
    check(
        resultado.estado in ("FACTIBLE", "PARCIAL"),
        f"El sistema entregó un horario (estado: {resultado.estado})",
    )

    # 2. Las secciones colocadas están dentro del rango esperado
    codigos_restringidos = {
        c.codigo for c in datos.cursos.values()
        if any(car in c.semestres_por_carrera for car in CARRERAS)
    }
    secciones_esperadas = [s for s in datos.secciones if s.codigo_curso in codigos_restringidos]
    check(
        0 < len(resultado.asignaciones) <= len(secciones_esperadas),
        f"Secciones colocadas dentro del rango esperado "
        f"({len(resultado.asignaciones)}/{len(secciones_esperadas)})",
    )

    # 3. Cada sección tiene el número correcto de bloques
    sec_by_id = {s.id: s for s in datos.secciones}
    errores_n_bloques = []
    for sec_id, bloques in resultado.asignaciones.items():
        s = sec_by_id.get(sec_id)
        if s and len(bloques) != s.cantidad_bloques_necesarios:
            errores_n_bloques.append(
                f"{sec_id}: esperados {s.cantidad_bloques_necesarios}, asignados {len(bloques)}"
            )
    check(len(errores_n_bloques) == 0,
          f"Todas las secciones tienen el número correcto de bloques "
          f"({len(errores_n_bloques)} errores)")
    for e in errores_n_bloques[:5]:
        print(f"    {e}")

    # 4. Índices en rango válido
    n = len(TODOS_BLOQUES)
    check(
        all(0 <= idx < n for idxs in resultado.asignaciones.values() for idx in idxs),
        f"Todos los índices de bloque son válidos [0, {n-1}]",
    )

    # 5. 0 solapamientos intra-sección
    intra = verificar_intra(resultado.asignaciones)
    check(len(intra) == 0, f"0 solapamientos intra-sección (hay {len(intra)})")
    if intra:
        for sec_id, b1, b2 in intra[:5]:
            print(f"    {sec_id}: {TODOS_BLOQUES[b1]} ↔ {TODOS_BLOQUES[b2]}")

    # 6. 0 topes RD1 en cada carrera
    for carrera in CARRERAS:
        topes = verificar_topes(datos, resultado.asignaciones, carrera)
        check(len(topes) == 0, f"0 topes en {carrera} (hay {len(topes)})")
        if topes:
            for s1_id, s2_id, sem in topes[:3]:
                b1s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[s1_id]]
                b2s = [TODOS_BLOQUES[b] for b in resultado.asignaciones[s2_id]]
                print(f"    SEM {sem}: {s1_id} {b1s} ↔ {s2_id} {b2s}")

    # 7. Modelo a nivel de sección: secciones independientes (RC sync ya no aplica).
    #    Lo relevante es la ausencia de topes RD1 y de solapes intra-sección, abajo.
    check(len(verificar_intra(resultado.asignaciones)) == 0,
          "0 solapamientos intra-sección")

    # 8. ING1100-CLAS tiene 4 bloques
    ing_clas = [sec_id for sec_id in resultado.asignaciones
                if sec_id.startswith("ING1100") and "CLAS" in sec_id]
    check(len(ing_clas) > 0, "Hay secciones ING1100-CLAS asignadas")
    for sec_id in ing_clas:
        bloques = resultado.asignaciones[sec_id]
        check(len(bloques) == 4,
              f"{sec_id} tiene 4 bloques (tiene {len(bloques)})")
        print(f"\n  {sec_id}: {[str(TODOS_BLOQUES[b]) for b in bloques]}")

    print("\n  → step5 OK")
    return resultado


def imprimir_multi_bloque(datos, resultado):
    """Imprime solo las secciones con más de 1 bloque."""
    sec_by_id = {s.id: s for s in datos.secciones}
    print("\n=== SECCIONES CON MÚLTIPLES BLOQUES ===")
    multi = {sid: bl for sid, bl in resultado.asignaciones.items() if len(bl) > 1}
    for sec_id in sorted(multi):
        bloques = multi[sec_id]
        s = sec_by_id.get(sec_id)
        bloques_str = " | ".join(
            f"{TODOS_BLOQUES[b].dia.value} {TODOS_BLOQUES[b].hora_inicio}-{TODOS_BLOQUES[b].hora_fin}"
            for b in bloques
        )
        comp = s.componente.value if s else "?"
        print(f"  {sec_id} [{comp}]: {bloques_str}")


def main():
    print("Cargando datos desde", INPUTS_DIR)
    datos = cargar_datos(INPUTS_DIR)

    fallidos = []
    try:
        resultado = test_step5(datos)
        imprimir_multi_bloque(datos, resultado)
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
        print("RESULTADO: PASO 5 VALIDADO ✓")


if __name__ == "__main__":
    main()
