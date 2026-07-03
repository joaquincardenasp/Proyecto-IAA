"""
test_solver_step7.py — Paso 7: GA con restricciones blandas (RB1-RB4).

Verifica:
  - El GA mejora (o iguala) el fitness de la solución CP-SAT
  - Las asignaciones del GA siguen siendo factibles (todas las restricciones duras)
  - Imprime fitness por restricción blanda para diagnóstico

Ejecutar desde backend/:
    python tests/test_solver_step7.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.parser import cargar_datos
from app.core.solver_cpsat import (
    resolver_por_partes,
    verificar_topes, verificar_intra,
    verificar_rd3, verificar_rd4, verificar_rd7,
)
from app.core.solver_ga import (
    construir_contexto, ejecutar_ga,
    calcular_fitness, encode,
    imprimir_resultado_ga, ResultadoGA, PESOS,
)
from app.core.blocks import TODOS_BLOQUES

INPUTS_DIR = Path(__file__).parent.parent / "inputs"
CARRERAS = ["Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA", "ICQ"]


def check(condicion: bool, mensaje: str) -> None:
    estado = "✓" if condicion else "✗ FALLO"
    print(f"  [{estado}] {mensaje}")
    if not condicion:
        raise AssertionError(f"FALLO: {mensaje}")


def verificar_duras(datos, asignaciones, label: str = "") -> None:
    """Verifica que el horario no viola ninguna restricción dura."""
    tag = f"[{label}] " if label else ""

    intra = verificar_intra(asignaciones)
    check(len(intra) == 0, f"{tag}0 solapamientos intra-sección (hay {len(intra)})")

    for carrera in CARRERAS:
        topes = verificar_topes(datos, asignaciones, carrera)
        check(len(topes) == 0, f"{tag}0 topes en {carrera} (hay {len(topes)})")

    # Modelo a nivel de sección: secciones independientes (RC sync ya no aplica).
    check(len(verificar_intra(asignaciones)) == 0, f"{tag}0 solapamientos intra-sección")

    conflictos_rd3 = verificar_rd3(datos, asignaciones)
    check(len(conflictos_rd3) == 0,
          f"{tag}RD3: 0 conflictos de profesor (hay {len(conflictos_rd3)})")

    conflictos_rd4 = verificar_rd4(datos, asignaciones)
    check(len(conflictos_rd4) == 0,
          f"{tag}RD4: 0 conflictos de sala especial (hay {len(conflictos_rd4)})")

    viol_rd7 = verificar_rd7(datos, asignaciones)
    check(len(viol_rd7) == 0,
          f"{tag}RD7: 0 AYUD antes de las 12:30 (hay {len(viol_rd7)})")


def desglosar_fitness(individuo, ctx) -> None:
    """Imprime la contribución de cada RB al fitness."""
    from collections import Counter

    _dia = lambda b: TODOS_BLOQUES[b].dia.value
    _ini = lambda b: TODOS_BLOQUES[b].hora_inicio
    _fin_min = lambda b: int(TODOS_BLOQUES[b].hora_fin.split(":")[0]) * 60 + int(TODOS_BLOQUES[b].hora_fin.split(":")[1])
    _ini_min = lambda b: int(TODOS_BLOQUES[b].hora_inicio.split(":")[0]) * 60 + int(TODOS_BLOQUES[b].hora_inicio.split(":")[1])
    EXTREMOS = {"8:30", "17:30"}

    rb1 = rb2 = rb3 = rb4 = 0.0

    for i in range(len(ctx.reps)):
        bloques = individuo[i]

        # RB1
        if ctx.rep_es_prog_labt[i] and len(bloques) >= 2:
            for k1 in range(len(bloques)):
                for k2 in range(k1 + 1, len(bloques)):
                    b1, b2 = bloques[k1], bloques[k2]
                    if _dia(b1) != _dia(b2):
                        rb1 += PESOS["RB1"]
                    else:
                        adj = (_fin_min(b1) == _ini_min(b2) or _fin_min(b2) == _ini_min(b1))
                        if not adj:
                            rb1 += PESOS["RB1"]

        # RB2
        if ctx.rep_es_jornada[i]:
            for b in bloques:
                if _ini(b) in EXTREMOS:
                    rb2 += PESOS["RB2"]
                    break

        # RB4
        if len(bloques) >= 2:
            cnt = Counter(_dia(b) for b in bloques)
            for count in cnt.values():
                if count > 1:
                    rb4 += (count - 1) * PESOS["RB4"]

    # RB3 — comp_map = {comp_str: [rep_idx, ...]} (cada sección es un rep)
    for comp_map in ctx.reps_por_curso.values():
        comps = list(comp_map.keys())
        for a in range(len(comps)):
            for b_idx in range(a + 1, len(comps)):
                for ri in comp_map[comps[a]]:
                    for rj in comp_map[comps[b_idx]]:
                        dias_a = {_dia(bk) for bk in individuo[ri]}
                        dias_b = {_dia(bk) for bk in individuo[rj]}
                        rb3 += len(dias_a & dias_b) * PESOS["RB3"]

    total = rb1 + rb2 + rb3 + rb4
    print(f"    RB1 (labs prog consecutivos): {rb1:.0f}")
    print(f"    RB2 (prof jornada extremos):  {rb2:.0f}")
    print(f"    RB3 (espaciado semanal):       {rb3:.0f}")
    print(f"    RB4 (concentración diaria):    {rb4:.0f}")
    print(f"    TOTAL:                         {total:.0f}")


def test_step7(datos):
    print("\n--- test_step7 (GA restricciones blandas) ---")

    # 1. Resolver con CP-SAT
    print("\n  Ejecutando CP-SAT...")
    resultado_cpsat = resolver_por_partes(datos, carreras=CARRERAS)
    check(
        resultado_cpsat.estado in ("FACTIBLE", "PARCIAL"),
        f"El sistema entregó un horario (estado: {resultado_cpsat.estado})",
    )
    print(f"  CP-SAT: {len(resultado_cpsat.asignaciones)} secciones colocadas "
          f"({len(resultado_cpsat.bloqueadas)} unidades bloqueadas)")

    # 2. Verificar restricciones duras del CP-SAT
    print("\n  Verificando restricciones duras CP-SAT...")
    verificar_duras(datos, resultado_cpsat.asignaciones, label="CP-SAT")

    # 3. Construir contexto del GA y calcular fitness inicial
    ctx = construir_contexto(datos, resultado_cpsat.asignaciones)
    individuo_cpsat = encode(resultado_cpsat.asignaciones, ctx)
    fitness_cpsat = calcular_fitness(individuo_cpsat, ctx)[0]

    print(f"\n  Fitness CP-SAT: {fitness_cpsat:.1f}")
    print("  Desglose fitness CP-SAT:")
    desglosar_fitness(individuo_cpsat, ctx)

    # 4. Ejecutar GA
    print("\n  Ejecutando GA (200 generaciones)...")
    resultado_ga = ejecutar_ga(
        datos,
        resultado_cpsat.asignaciones,
        n_generaciones=200,
        pop_size=40,
        seed=42,
    )

    imprimir_resultado_ga(resultado_ga)

    # 5. GA no empeora el fitness
    check(
        resultado_ga.fitness_final <= fitness_cpsat + 1e-6,
        f"GA no empeora el fitness (CP-SAT: {fitness_cpsat:.1f}, GA: {resultado_ga.fitness_final:.1f})",
    )

    # 6. Asignaciones del GA conservan todas las restricciones duras
    print("\n  Verificando restricciones duras GA...")
    verificar_duras(datos, resultado_ga.asignaciones, label="GA")

    # 7. Todas las secciones siguen asignadas
    check(
        len(resultado_ga.asignaciones) == len(resultado_cpsat.asignaciones),
        f"GA mantiene todas las secciones asignadas "
        f"({len(resultado_ga.asignaciones)}/{len(resultado_cpsat.asignaciones)})",
    )

    print("\n  Desglose fitness GA:")
    individuo_ga = encode(resultado_ga.asignaciones, ctx)
    desglosar_fitness(individuo_ga, ctx)

    mejora = fitness_cpsat - resultado_ga.fitness_final
    pct = (mejora / fitness_cpsat * 100) if fitness_cpsat > 0 else 0
    print(f"\n  Mejora total: {mejora:.1f} ({pct:.1f}%)")
    print("\n  → step7 OK")
    return resultado_ga


def main():
    print("Cargando datos desde", INPUTS_DIR)
    datos = cargar_datos(INPUTS_DIR)

    fallidos = []
    try:
        test_step7(datos)
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
        print("RESULTADO: PASO 7 VALIDADO ✓")


if __name__ == "__main__":
    main()
