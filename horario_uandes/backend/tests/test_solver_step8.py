"""
test_solver_step8.py — Paso 8: Exportador Excel.

Verifica:
  - El archivo se genera sin errores y no está vacío
  - Contiene las hojas esperadas (Horario + 7 carreras + Métricas)
  - La hoja "Horario" tiene exactamente tantas filas de datos como secciones asignadas
  - Los bloques 13:30-15:20 aparecen en el Excel (validación del fix de bloques)
  - El archivo es abrirable por openpyxl (estructura válida)
  - Guarda el resultado en outputs/horario_generado.xlsx para inspección manual

Ejecutar desde backend/:
    python tests/test_solver_step8.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

import openpyxl

from app.core.parser import cargar_datos
from app.core.solver_cpsat import resolver_por_partes
from app.core.solver_ga import ejecutar_ga, calcular_fitness, encode, construir_contexto, PESOS
from app.core.exporter import exportar_horario, _CARRERAS
from app.core.blocks import TODOS_BLOQUES

INPUTS_DIR  = Path(__file__).parent.parent / "inputs"
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"
OUTPUT_FILE = OUTPUTS_DIR / "horario_generado.xlsx"

CARRERAS = ["Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA", "ICQ"]


def check(condicion: bool, mensaje: str) -> None:
    estado = "✓" if condicion else "✗ FALLO"
    print(f"  [{estado}] {mensaje}")
    if not condicion:
        raise AssertionError(f"FALLO: {mensaje}")


def test_step8(datos):
    print("\n--- test_step8 (Exportador Excel) ---")

    # 1. Resolver (CP-SAT + GA rápido)
    print("\n  Ejecutando CP-SAT…")
    resultado_cpsat = resolver_por_partes(datos, carreras=CARRERAS)
    check(resultado_cpsat.estado in ("FACTIBLE", "PARCIAL"),
          f"El sistema entregó un horario ({resultado_cpsat.estado})")

    print("  Ejecutando GA (50 generaciones para test rápido)…")
    resultado_ga = ejecutar_ga(
        datos, resultado_cpsat.asignaciones,
        n_generaciones=50, pop_size=20, seed=42,
    )

    asignaciones = resultado_ga.asignaciones
    n_secciones  = len(asignaciones)

    # 2. Construir dict de métricas
    ctx = construir_contexto(datos, resultado_cpsat.asignaciones)
    fitness_cpsat = calcular_fitness(encode(resultado_cpsat.asignaciones, ctx), ctx)[0]
    fitness_ga    = resultado_ga.fitness_final
    mejora_pct    = (fitness_cpsat - fitness_ga) / fitness_cpsat * 100 if fitness_cpsat > 0 else 0

    metricas = {
        "fitness_cpsat": fitness_cpsat,
        "fitness_ga":    fitness_ga,
        "mejora_pct":    mejora_pct,
        "rb_detalle": {
            f"RB{k+1} (peso {v})": "—"
            for k, v in enumerate(PESOS.values())
        },
    }

    # 3. Exportar
    print(f"\n  Exportando a {OUTPUT_FILE}…")
    excel_bytes = exportar_horario(datos, asignaciones, OUTPUT_FILE, metricas)

    # 4. Verificaciones básicas
    check(len(excel_bytes) > 0, "El archivo Excel no está vacío")
    check(OUTPUT_FILE.exists(), f"El archivo fue guardado en {OUTPUT_FILE}")
    check(OUTPUT_FILE.stat().st_size > 1000, "El archivo tiene tamaño razonable (>1 KB)")

    # 5. Abrir con openpyxl y verificar estructura
    wb = openpyxl.load_workbook(OUTPUT_FILE)
    sheet_names = wb.sheetnames
    print(f"\n  Hojas generadas: {sheet_names}")

    expected_sheets = ["Horario"] + _CARRERAS + ["Métricas"]
    for sh in expected_sheets:
        check(sh in sheet_names, f"Hoja '{sh}' presente en el Excel")

    # 6. Sheet "Horario": filas de datos = secciones asignadas
    ws_horario = wb["Horario"]
    data_rows = ws_horario.max_row - 1    # -1 porque la fila 1 es header
    check(
        data_rows == n_secciones,
        f"Hoja 'Horario': {data_rows} filas de datos == {n_secciones} secciones asignadas",
    )

    # 7. El bloque 13:30-15:20 aparece en el Excel (validación de bloque fix)
    valores_celdas = set()
    for row in ws_horario.iter_rows(min_row=2, values_only=True):
        for cell in row:
            if isinstance(cell, str):
                valores_celdas.add(cell)

    bloques_13_30 = [b for b in TODOS_BLOQUES if b.hora_inicio == "13:30"]
    check(len(bloques_13_30) > 0, "Existen bloques 13:30 en el catálogo")
    tiene_13_30 = any("13:30" in v for v in valores_celdas)
    check(tiene_13_30, "El bloque 13:30 aparece en la hoja 'Horario'")

    # 8. Los bloques helper (ej. 12:30-14:20) ahora SON válidos: rellenan los huecos del
    #    catálogo cuando la disponibilidad del profesor lo exige. Ya no se prohíben.

    # 9. Sheet por carrera: existe siempre; tiene contenido solo si hay cursos de esa carrera
    for carrera in _CARRERAS:
        check(carrera in sheet_names, f"Hoja '{carrera}' presente en el Excel")
        tiene_cursos = any(
            carrera in c.semestres_por_carrera
            for c in datos.cursos.values()
        )
        ws_c = wb[carrera]
        n_rows = ws_c.max_row
        if tiene_cursos:
            check(n_rows >= 3, f"Hoja '{carrera}': tiene contenido (≥3 filas)")
        else:
            print(f"    [INFO] Hoja '{carrera}': sin cursos en datos actuales — hoja vacía OK")

    # 10. Sheet "Métricas": tiene datos
    ws_m = wb["Métricas"]
    check(ws_m.max_row >= 5, "Hoja 'Métricas': tiene contenido (≥5 filas)")

    print(f"\n  Archivo guardado en: {OUTPUT_FILE}")
    print(f"  Tamaño: {OUTPUT_FILE.stat().st_size:,} bytes")
    print(f"  Secciones exportadas: {n_secciones}")
    print(f"  Fitness CP-SAT: {fitness_cpsat:.0f}  →  GA: {fitness_ga:.0f}  ({mejora_pct:.1f}% mejora)")
    print("\n  → step8 OK")


def main():
    print("Cargando datos desde", INPUTS_DIR)
    datos = cargar_datos(INPUTS_DIR)

    fallidos = []
    try:
        test_step8(datos)
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
        print("RESULTADO: PASO 8 VALIDADO ✓")


if __name__ == "__main__":
    main()
