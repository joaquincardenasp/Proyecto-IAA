#!/usr/bin/env python3
"""
benchmark_historico.py — Compara el horario real del semestre 202520
con el horario generado por el sistema usando la función de fitness del GA.

Uso:
    cd horario_uandes/backend
    python benchmark_historico.py

Requiere:
    - inputs/ con los archivos de datos limpios
    - inputs/historico/Horario_ING_202520.xlsx (o el archivo del semestre pasado)
    - Las mismas dependencias que el backend (requirements.txt instalado)

Salida:
    Tabla comparativa de penalizaciones RB1–RB5 para tres horarios:
      1. Salida directa de CP-SAT (línea de partida del GA)
      2. Horario real del semestre 202520
      3. Salida del GA (optimizado a partir de CP-SAT)
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# ── Ajustar PYTHONPATH para importar desde app/ ──────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from app.core.parser import cargar_datos
from app.core.parser_historico import _leer_un_archivo, leer_historico
from app.core.solver_cpsat import resolver
from app.core.solver_ga import (
    GAContexto,
    PESOS,
    _DIA_DEL_BLOQUE,
    _HORA_INICIO_DEL_BLOQUE,
    _HORAS_EXTREMAS,
    _MIN_FIN_BLOQUE,
    _MIN_INICIO_BLOQUE,
    calcular_fitness,
    construir_contexto,
    ejecutar_ga,
    encode,
)

INPUTS_DIR = Path(__file__).parent / "inputs"
HISTORICO_DIR = INPUTS_DIR / "historico"

# ── Descripción de cada restricción blanda ───────────────────────────────────

_RB_DESC = {
    "RB1": "Labs Programación consecutivos",
    "RB2": "Prof. jornada no en horario extremo",
    "RB3": "Componentes mismo curso en días distintos",
    "RB4": "Máx. 1 bloque por componente/día",
    "RB5": "Proximidad al histórico de semestres anteriores",
}


# ── Desglose de penalización por restricción ─────────────────────────────────

def desglose_fitness(individuo: list[list[int]], ctx: GAContexto) -> dict[str, float]:
    """
    Réplica de calcular_fitness() que retorna el desglose por RB.
    Mantiene exacta correspondencia con la lógica de solver_ga.py.
    """
    rb: dict[str, float] = {k: 0.0 for k in PESOS}

    # RB1: Labs de Programación (ING1103-LABT) deben ser en el mismo día y adyacentes
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
                    rb["RB1"] += PESOS["RB1"]
                else:
                    adj = (
                        _MIN_FIN_BLOQUE[b1] == _MIN_INICIO_BLOQUE[b2]
                        or _MIN_FIN_BLOQUE[b2] == _MIN_INICIO_BLOQUE[b1]
                    )
                    if not adj:
                        rb["RB1"] += PESOS["RB1"]

    # RB2: Profesor jornada no asignado a bloques extremos (8:30 ó 17:30)
    for i in range(len(ctx.reps)):
        if not ctx.rep_es_jornada[i]:
            continue
        for b in individuo[i]:
            if _HORA_INICIO_DEL_BLOQUE[b] in _HORAS_EXTREMAS:
                rb["RB2"] += PESOS["RB2"]
                break  # penalizar el rep solo una vez

    # RB3: Distintos componentes del mismo curso deben ir en días distintos
    for comp_map in ctx.reps_por_curso.values():
        comp_idxs = list(comp_map.values())
        for a in range(len(comp_idxs)):
            for b in range(a + 1, len(comp_idxs)):
                dias_a = {_DIA_DEL_BLOQUE[bk] for bk in individuo[comp_idxs[a]]}
                dias_b = {_DIA_DEL_BLOQUE[bk] for bk in individuo[comp_idxs[b]]}
                rb["RB3"] += len(dias_a & dias_b) * PESOS["RB3"]

    # RB4: Máximo 1 bloque del mismo componente por día
    for i in range(len(ctx.reps)):
        bloques = individuo[i]
        if len(bloques) < 2:
            continue
        cnt = Counter(_DIA_DEL_BLOQUE[b] for b in bloques)
        for count in cnt.values():
            if count > 1:
                rb["RB4"] += (count - 1) * PESOS["RB4"]

    # RB5: Proximidad al histórico
    for i in range(len(ctx.reps)):
        hist = ctx.historico_rep[i]
        if not hist:
            continue
        for b in individuo[i]:
            if b not in hist:
                rb["RB5"] += PESOS["RB5"]

    return rb


# ── Construcción del individuo desde datos históricos 202520 ─────────────────

def individuo_desde_historico(
    hist_202520: dict[str, dict[str, set[int]]],
    ctx: GAContexto,
    fallback: dict[str, list[int]],
) -> tuple[list[list[int]], int, int]:
    """
    Convierte el horario histórico 202520 al formato de cromosoma GA.

    Para cada representante en ctx.reps:
      - Si hay bloques históricos suficientes → se usan los primeros n_bloques.
      - Si hay datos parciales → se completan con el fallback (asignación CP-SAT).
      - Si no hay datos → se usa el fallback directamente.

    Retorna (individuo, n_con_datos, n_sin_datos).
    """
    individuo: list[list[int]] = []
    n_con_datos = 0
    n_sin_datos = 0

    for i, rep_id in enumerate(ctx.reps):
        s = ctx.sec_by_id[rep_id]
        codigo = s.codigo_curso
        comp = s.componente.value          # "CLAS", "AYUD" o "LABT"
        n_bloques = ctx.rep_n_blocks[i]

        bloques_hist = sorted(hist_202520.get(codigo, {}).get(comp, set()))

        if len(bloques_hist) >= n_bloques:
            # Datos completos: tomar los primeros n_bloques bloques del histórico
            individuo.append(bloques_hist[:n_bloques])
            n_con_datos += 1
        elif bloques_hist:
            # Datos parciales: completar con bloques del fallback que no se repitan
            fb = list(fallback.get(rep_id, []))
            extras = [b for b in fb if b not in set(bloques_hist)]
            combinado = (bloques_hist + extras)[:n_bloques]
            # Si aun faltan bloques, rellenar con el fallback completo
            if len(combinado) < n_bloques:
                combinado = (combinado + fb)[:n_bloques]
            individuo.append(combinado)
            n_sin_datos += 1
        else:
            # Sin datos: usar la asignación CP-SAT completa
            individuo.append(list(fallback.get(rep_id, [])))
            n_sin_datos += 1

    return individuo, n_con_datos, n_sin_datos


# ── Impresión ─────────────────────────────────────────────────────────────────

def _barra(valor: float, maximo: float, ancho: int = 20) -> str:
    if maximo <= 0:
        return "░" * ancho
    n = round(valor / maximo * ancho)
    return "█" * n + "░" * (ancho - n)


def imprimir_tabla(resultados: dict[str, tuple[dict[str, float], float]]) -> None:
    """
    Imprime tabla comparativa de penalizaciones por RB para cada horario.
    resultados = {label: (rb_dict, fitness_total)}
    """
    labels = list(resultados.keys())
    col_w = max(14, max(len(l) for l in labels) + 2)

    sep = "─" * (36 + col_w * len(labels))
    print()
    print("=" * len(sep))
    print(f"{'DESGLOSE DE RESTRICCIONES BLANDAS':^{len(sep)}}")
    print("=" * len(sep))

    # Encabezado
    header = f"  {'Restricción (peso)':<32}"
    for label in labels:
        header += f"  {label:>{col_w}}"
    print(header)
    print(sep)

    # Fila por RB
    max_val = max(
        (v for rb_dict, _ in resultados.values() for v in rb_dict.values()),
        default=1.0,
    ) or 1.0

    for rb, peso in PESOS.items():
        desc = _RB_DESC[rb]
        row = f"  {rb} {desc[:26]:<26} (w={peso:>3})"
        for label in labels:
            rb_dict, _ = resultados[label]
            v = rb_dict[rb]
            row += f"  {v:>{col_w}.0f}"
        print(row)

    print(sep)

    # Fila TOTAL
    row = f"  {'TOTAL PENALIZACIÓN':<32}"
    for label in labels:
        _, fitness = resultados[label]
        row += f"  {fitness:>{col_w}.0f}"
    print(row)
    print("=" * len(sep))


def imprimir_resumen(resultados: dict[str, tuple[dict[str, float], float]]) -> None:
    labels = list(resultados.keys())
    fitnesses = {l: f for l, (_, f) in resultados.items()}

    print()
    print("=" * 60)
    print("RESUMEN EJECUTIVO")
    print("=" * 60)

    base_label = "202520 Real"
    base_f = fitnesses.get(base_label)

    for label, fitness in fitnesses.items():
        marker = ""
        if base_f is not None and label != base_label and base_f > 0:
            diff = (fitness - base_f) / base_f * 100
            if diff < 0:
                marker = f"  ✓ {abs(diff):.1f}% mejor que el horario real"
            elif diff > 0:
                marker = f"  ✗ {abs(diff):.1f}% peor que el horario real"
            else:
                marker = "  = igual al horario real"
        print(f"  {label:<28}  {fitness:>8.0f} pts{marker}")

    print()
    print("  Notas:")
    print("  · Valores son penalizaciones — menor es mejor.")
    print("  · RB5 mide distancia al histórico que incluye 202520.")
    print("    → El horario real tendrá RB5 ≈ 0 por construcción.")
    print("  · Secciones sin datos en 202520 usan la asignación CP-SAT.")
    print("=" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("=" * 72)
    print("  BENCHMARK — Horario Real 202520 vs Generador UANDES")
    print("=" * 72)

    # ── 1. Buscar archivo 202520 ──────────────────────────────────────────────
    if not HISTORICO_DIR.exists():
        print(f"\n[ERROR] No existe el directorio {HISTORICO_DIR}")
        print("        Crea la carpeta y coloca el archivo Excel del semestre pasado.")
        sys.exit(1)

    archivos_hist = sorted(HISTORICO_DIR.glob("*.xlsx"))
    if not archivos_hist:
        print(f"\n[ERROR] No hay archivos .xlsx en {HISTORICO_DIR}")
        sys.exit(1)

    # Preferir el que tenga "202520" en el nombre
    archivo_202520 = next(
        (f for f in archivos_hist if "202520" in f.name), archivos_hist[0]
    )
    print(f"\n  Archivo a evaluar : {archivo_202520.name}")
    print(f"  Total en historico: {len(archivos_hist)} archivo(s)")

    # ── 2. Cargar datos del problema ──────────────────────────────────────────
    print("\n[1/5] Cargando datos del problema…")
    datos = cargar_datos(INPUTS_DIR)
    print(f"      {len(datos.cursos)} cursos | {len(datos.secciones)} secciones "
          f"| {len(datos.profesores)} profesores")

    # ── 3. Leer histórico completo (para RB5 en el contexto del GA) ───────────
    print("[2/5] Leyendo histórico completo (para RB5)…")
    historico_all = leer_historico(INPUTS_DIR)
    print(f"      {len(historico_all)} cursos con preferencias históricas")

    # ── 4. Leer solo el 202520 (individuo a evaluar) ──────────────────────────
    print("[3/5] Leyendo horario 202520 (a evaluar)…")
    hist_202520 = _leer_un_archivo(archivo_202520)
    n_comps = sum(len(comps) for comps in hist_202520.values())
    print(f"      {len(hist_202520)} cursos | {n_comps} pares (curso, componente)")

    # ── 5. Ejecutar CP-SAT ────────────────────────────────────────────────────
    print("[4/5] Ejecutando CP-SAT…")
    resultado_cpsat = resolver(datos)
    estado = resultado_cpsat.estado
    print(f"      Estado: {estado}")
    if estado not in ("OPTIMAL", "FEASIBLE"):
        print(f"\n[ERROR] CP-SAT no encontró solución factible ({estado}).")
        print("        Verifica que los archivos de input estén completos y sean válidos.")
        sys.exit(1)
    asig_cpsat = resultado_cpsat.asignaciones
    print(f"      {len(asig_cpsat)} secciones asignadas")

    # ── 6. Construir contexto GA ──────────────────────────────────────────────
    print("[5/5] Construyendo contexto GA…")
    ctx = construir_contexto(datos, asig_cpsat, historico_all)
    print(f"      {len(ctx.reps)} representantes (grupos de secciones paralelas)")

    # ── 7. Evaluar CP-SAT ─────────────────────────────────────────────────────
    print("\n─── Evaluando CP-SAT (sin GA) ───")
    ind_cpsat = encode(asig_cpsat, ctx)
    fit_cpsat = calcular_fitness(ind_cpsat, ctx)[0]
    rb_cpsat = desglose_fitness(ind_cpsat, ctx)
    print(f"    Fitness: {fit_cpsat:.0f}")

    # ── 8. Construir individuo del horario real 202520 ────────────────────────
    print("─── Construyendo individuo desde horario 202520 ───")
    ind_202520, n_con, n_sin = individuo_desde_historico(hist_202520, ctx, asig_cpsat)
    print(f"    {n_con}/{len(ctx.reps)} reps con datos de 202520 "
          f"({n_sin} usan fallback CP-SAT)")
    fit_202520 = calcular_fitness(ind_202520, ctx)[0]
    rb_202520 = desglose_fitness(ind_202520, ctx)
    print(f"    Fitness: {fit_202520:.0f}")

    # ── 9. Ejecutar GA ────────────────────────────────────────────────────────
    print("─── Ejecutando GA (200 generaciones, pop=40) ───")
    resultado_ga = ejecutar_ga(datos, asig_cpsat, historico_all)
    print(f"    Fitness inicial (CP-SAT) : {resultado_ga.fitness_inicial:.0f}")
    print(f"    Fitness final   (GA)     : {resultado_ga.fitness_final:.0f}")
    mejora_ga = (
        (resultado_ga.fitness_inicial - resultado_ga.fitness_final)
        / max(1.0, resultado_ga.fitness_inicial)
        * 100
    )
    print(f"    Mejora del GA sobre CP-SAT: {mejora_ga:.1f}%")

    # Calcular desglose del GA
    ctx_ga = construir_contexto(datos, asig_cpsat, historico_all)
    ind_ga = encode(resultado_ga.asignaciones, ctx_ga)
    fit_ga = calcular_fitness(ind_ga, ctx_ga)[0]
    rb_ga = desglose_fitness(ind_ga, ctx_ga)

    # ── 10. Tabla comparativa ─────────────────────────────────────────────────
    resultados = {
        "CP-SAT":      (rb_cpsat,   fit_cpsat),
        "202520 Real": (rb_202520,  fit_202520),
        "Sistema GA":  (rb_ga,      fit_ga),
    }
    imprimir_tabla(resultados)
    imprimir_resumen(resultados)


if __name__ == "__main__":
    main()
