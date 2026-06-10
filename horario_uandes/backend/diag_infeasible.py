"""
diag_infeasible.py — Aísla qué restricción dura causa el INFEASIBLE en Plan Común.

Ejecutar desde backend/:
    python diag_infeasible.py

Estrategia:
  1. Resuelve con distintas combinaciones de RD2/RD3/RD4 desactivadas.
  2. Identifica la primera combinación factible → la restricción que falta es la culpable.
  3. Si RD2 es la culpa, lista los profesores cuya disponibilidad es insuficiente
     para los bloques que necesitan sus secciones.
"""
import sys
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from app.core.parser import cargar_datos
from app.core.solver_cpsat import resolver
from app.core.blocks import TODOS_BLOQUES, N_BLOQUES
from app.core.models import TipoReunion

INPUTS_DIR = Path(__file__).parent / "inputs"
CARRERAS = ["Plan Común"]

print("Cargando datos…")
datos = cargar_datos(INPUTS_DIR)

# ── 1. Probar combinaciones de restricciones ──────────────────────────────────
print("\n" + "=" * 60)
print("PRUEBA DE COMBINACIONES (carrera = Plan Común)")
print("=" * 60)

combos = [
    ("Todas activas",            dict(usar_rd2=True,  usar_rd3=True,  usar_rd4=True)),
    ("Sin RD2 (disponibilidad)", dict(usar_rd2=False, usar_rd3=True,  usar_rd4=True)),
    ("Sin RD3 (prof único)",     dict(usar_rd2=True,  usar_rd3=False, usar_rd4=True)),
    ("Sin RD4 (salas)",          dict(usar_rd2=True,  usar_rd3=True,  usar_rd4=False)),
    ("Sin RD2 ni RD3",           dict(usar_rd2=False, usar_rd3=False, usar_rd4=True)),
    ("Solo RD1+RC (base)",       dict(usar_rd2=False, usar_rd3=False, usar_rd4=False)),
]

resultados = {}
for nombre, kwargs in combos:
    r = resolver(datos, carreras=CARRERAS, tiempo_limite_s=30.0, **kwargs)
    resultados[nombre] = r.estado
    marca = "✓ FACTIBLE" if r.estado in ("OPTIMAL", "FEASIBLE") else "✗ " + r.estado
    print(f"  {nombre:28} → {marca}")

# ── 2. Conclusión ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("DIAGNÓSTICO")
print("=" * 60)

base_ok = resultados["Solo RD1+RC (base)"] in ("OPTIMAL", "FEASIBLE")
if not base_ok:
    print("  El modelo base (solo RD1 + RC) ya es INFEASIBLE.")
    print("  → El problema NO es RD2/RD3/RD4. Está en RD1, RC o los datos de malla.")
else:
    culpables = []
    if resultados["Sin RD2 (disponibilidad)"] in ("OPTIMAL", "FEASIBLE") and \
       resultados["Todas activas"] not in ("OPTIMAL", "FEASIBLE"):
        culpables.append("RD2 (disponibilidad de profesor)")
    if resultados["Sin RD3 (prof único)"] in ("OPTIMAL", "FEASIBLE") and \
       resultados["Todas activas"] not in ("OPTIMAL", "FEASIBLE"):
        culpables.append("RD3 (profesor en dos secciones a la vez)")
    if resultados["Sin RD4 (salas)"] in ("OPTIMAL", "FEASIBLE") and \
       resultados["Todas activas"] not in ("OPTIMAL", "FEASIBLE"):
        culpables.append("RD4 (capacidad de salas)")

    if culpables:
        print("  La(s) restricción(es) que causan INFEASIBLE:")
        for c in culpables:
            print(f"    → {c}")
    else:
        print("  Quitar una sola restricción no basta: es una combinación.")
        print(f"  Estados: {resultados}")

# ── 3. Si RD2 es sospechoso, analizar disponibilidad por sección ──────────────
print("\n" + "=" * 60)
print("ANÁLISIS RD2: secciones cuya disponibilidad de profesor es insuficiente")
print("=" * 60)

codigos_pc = {c.codigo for c in datos.cursos.values() if "Plan Común" in c.semestres_por_carrera}
secs_pc = [s for s in datos.secciones if s.codigo_curso in codigos_pc]

problemas = []
for s in secs_pc:
    if not s.afecta_disponibilidad or not s.rut_profesor:
        continue
    prof = datos.profesores.get(s.rut_profesor)
    if not prof or not prof.disponibilidad:
        continue
    n_disp = len(prof.disponibilidad)
    n_nec  = s.cantidad_bloques_necesarios
    # Una sección necesita n_nec bloques en DÍAS DISTINTOS dentro de su disponibilidad.
    dias_disp = {TODOS_BLOQUES[b].dia.value for b in prof.disponibilidad}
    if n_disp < n_nec or len(dias_disp) < n_nec:
        problemas.append((s, prof, n_disp, len(dias_disp), n_nec))

if problemas:
    print(f"\n  {len(problemas)} sección(es) con disponibilidad insuficiente:\n")
    for s, prof, n_disp, n_dias, n_nec in sorted(problemas, key=lambda t: t[4] - t[2], reverse=True):
        print(f"  {s.id}")
        print(f"    Profesor: {prof.nombre or prof.rut}")
        print(f"    Necesita {n_nec} bloque(s) en días distintos")
        print(f"    Disponible en {n_disp} bloque(s) sobre {n_dias} día(s) distintos")
        bloques_disp = sorted(prof.disponibilidad)
        nombres = [f"{TODOS_BLOQUES[b].dia.value} {TODOS_BLOQUES[b].hora_inicio}" for b in bloques_disp]
        print(f"    Bloques: {nombres}")
        print()
else:
    print("\n  Ninguna sección de Plan Común tiene disponibilidad insuficiente por sí sola.")
    print("  → Si RD2 causa INFEASIBLE, es por interacción (varios profes compitiendo")
    print("    por los mismos pocos bloques), no por una sección imposible aislada.")

# ── 4. Profesores con muy poca disponibilidad (global) ────────────────────────
print("=" * 60)
print("PROFESORES CON DISPONIBILIDAD MUY BAJA (global)")
print("=" * 60)
bajos = [(p, len(p.disponibilidad)) for p in datos.profesores.values()
         if p.disponibilidad and len(p.disponibilidad) < 6]
if bajos:
    for p, n in sorted(bajos, key=lambda t: t[1]):
        dias = {TODOS_BLOQUES[b].dia.value for b in p.disponibilidad}
        print(f"  {p.nombre or p.rut}: {n} bloque(s) en días {sorted(dias)}")
else:
    print("  Ningún profesor con <6 bloques disponibles.")

print("\n" + "=" * 60)
print("FIN DEL DIAGNÓSTICO")
print("=" * 60)
