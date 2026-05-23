"""
test_parser.py — Verifica que el parser carga correctamente los 5 archivos reales.

Ejecutar desde backend/:
    python -m pytest tests/test_parser.py -v
o directamente:
    python tests/test_parser.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# Permitir imports desde backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.models import TipoReunion
from app.core.parser import cargar_datos
from app.core.blocks import (
    TODOS_BLOQUES,
    MATRIZ_SOLAPAMIENTO,
    bloques_se_solapan,
    N_BLOQUES,
)

INPUTS_DIR = Path(__file__).parent.parent / "inputs"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def check(condicion: bool, mensaje: str) -> None:
    estado = "✓" if condicion else "✗ FALLO"
    print(f"  [{estado}] {mensaje}")
    if not condicion:
        raise AssertionError(f"FALLO: {mensaje}")


# ---------------------------------------------------------------------------
# Tests de blocks.py
# ---------------------------------------------------------------------------

def test_blocks():
    print("\n--- test_blocks ---")

    check(N_BLOQUES == 45, f"45 bloques totales (hay {N_BLOQUES})")

    b3h = [b for b in TODOS_BLOQUES if b.tipo == "3h"]
    check(len(b3h) == 10, f"10 bloques de 3h (hay {len(b3h)})")
    for b in b3h:
        check(b.hora_inicio in ("10:30", "12:30"),
              f"bloque 3h inicia en 10:30 o 12:30 (es {b.hora_inicio})")

    lunes = [b for b in TODOS_BLOQUES if b.dia.value == "L"]

    # 14:30-16:20 y 15:30-17:20 → solapan (comparten 15:30)
    b1 = next(b for b in lunes if b.hora_inicio == "14:30" and b.tipo == "2h")
    b2 = next(b for b in lunes if b.hora_inicio == "15:30" and b.tipo == "2h")
    check(bloques_se_solapan(b1, b2), "14:30-16:20 y 15:30-17:20 (L) se solapan")

    # 10:30-13:20 y 12:30-15:20 → solapan (comparten 12:30)
    b3 = next(b for b in lunes if b.hora_inicio == "10:30" and b.tipo == "3h")
    b4 = next(b for b in lunes if b.hora_inicio == "12:30" and b.tipo == "3h")
    check(bloques_se_solapan(b3, b4), "10:30-13:20 y 12:30-15:20 (L) se solapan")

    # 8:30-10:20 y 10:30-12:20 → NO solapan
    b5 = next(b for b in lunes if b.hora_inicio == "8:30")
    b6 = next(b for b in lunes if b.hora_inicio == "10:30" and b.tipo == "2h")
    check(not bloques_se_solapan(b5, b6), "8:30-10:20 y 10:30-12:20 NO se solapan")

    # Mismo slot, días distintos → NO solapan
    l830 = next(b for b in TODOS_BLOQUES if b.dia.value == "L" and b.hora_inicio == "8:30")
    m830 = next(b for b in TODOS_BLOQUES if b.dia.value == "M" and b.hora_inicio == "8:30")
    check(not bloques_se_solapan(l830, m830), "8:30 L y 8:30 M NO se solapan (días distintos)")

    # Matriz simétrica
    check(all(MATRIZ_SOLAPAMIENTO[i][j] == MATRIZ_SOLAPAMIENTO[j][i]
              for i in range(N_BLOQUES) for j in range(N_BLOQUES)),
          "MATRIZ_SOLAPAMIENTO es simétrica")

    print("  → blocks OK")


# ---------------------------------------------------------------------------
# Tests del parser
# ---------------------------------------------------------------------------

def test_cursos(datos):
    print("\n--- test_cursos ---")

    check(len(datos.cursos) == 223, f"223 cursos únicos (hay {len(datos.cursos)})")

    # Conteo por plan usando el campo .planes
    conteo = {}
    for curso in datos.cursos.values():
        for plan in curso.planes:
            conteo[plan] = conteo.get(plan, 0) + 1

    check(conteo.get("PE2022", 0) == 141,
          f"PE2022: 141 cursos (hay {conteo.get('PE2022', 0)})")
    check(conteo.get("PE2022_2025", 0) == 144,
          f"PE2022_2025: 144 cursos (hay {conteo.get('PE2022_2025', 0)})")
    check(conteo.get("PE2026", 0) == 168,
          f"PE2026: 168 cursos (hay {conteo.get('PE2026', 0)})")

    # ING1100 es Plan Común sem 1 en PE2022 y PE2022_2025
    # (no está en PE2026: fue dividido en 2 cursos nuevos)
    ings = datos.cursos.get("ING1100")
    check(ings is not None, "ING1100 existe")
    check("Plan Común" in ings.semestres_por_carrera,
          "ING1100 tiene semestre Plan Común")
    check(ings.semestres_por_carrera["Plan Común"] == {"1"},
          f"ING1100 Plan Común = {{'1'}} (es {ings.semestres_por_carrera['Plan Común']})")
    check("PE2022" in ings.planes and "PE2022_2025" in ings.planes,
          "ING1100 aparece en PE2022 y PE2022_2025")
    check("PE2026" not in ings.planes,
          "ING1100 NO aparece en PE2026 (fue dividido)")

    # Los cursos Plan Común NO deben tener carreras de especialidad
    for codigo, curso in datos.cursos.items():
        if "Plan Común" in curso.semestres_por_carrera:
            esp = [c for c in curso.semestres_por_carrera if c != "Plan Común"]
            check(len(esp) == 0,
                  f"{codigo}: curso Plan Común no debe tener carreras especialidad {esp}")

    # Semestres son strings (no ints)
    for codigo, curso in datos.cursos.items():
        for carrera, sems in curso.semestres_por_carrera.items():
            for sem in sems:
                check(isinstance(sem, str),
                      f"{codigo} ({carrera}): semestre '{sem}' debe ser string")

    # Menciones de ICI: "9a" y "9f" son semestres DISTINTOS
    # (verificar que al menos existen en el catálogo como strings separados)
    cursos_ici_9a = [c for c in datos.cursos.values()
                     if "9a" in c.semestres_por_carrera.get("ICI", set())]
    cursos_ici_9f = [c for c in datos.cursos.values()
                     if "9f" in c.semestres_por_carrera.get("ICI", set())]
    check(len(cursos_ici_9a) > 0, "Hay cursos ICI mención '9a'")
    check(len(cursos_ici_9f) > 0, "Hay cursos ICI mención '9f'")
    # Ningún curso debería tener ICI → "9" genérico si existen menciones
    # (es válido que un mismo curso tenga "9a" Y "9f" si distintos planes lo ubican así,
    #  pero NO debería tener ICI → "9" sin mención mezclado con los de mención)
    for c in datos.cursos.values():
        sems_ici = c.semestres_por_carrera.get("ICI", set())
        if "9" in sems_ici and len(sems_ici) > 1:
            check(False,
                  f"{c.codigo} tiene ICI-'9' (sin mención) junto con otros semestres: {sems_ici}")

    print("  → cursos OK")


def test_secciones(datos):
    print("\n--- test_secciones ---")

    secciones = datos.secciones
    check(len(secciones) == 304, f"304 secciones totales (hay {len(secciones)})")

    por_comp = {}
    for s in secciones:
        por_comp[s.componente.value] = por_comp.get(s.componente.value, 0) + 1

    check(por_comp.get("CLAS", 0) == 165, f"165 CLAS (hay {por_comp.get('CLAS', 0)})")
    check(por_comp.get("AYUD", 0) == 80,  f"80 AYUD (hay {por_comp.get('AYUD', 0)})")
    check(por_comp.get("LABT", 0) == 59,  f"59 LABT (hay {por_comp.get('LABT', 0)})")

    ayud_mal = [s for s in secciones
                if s.componente == TipoReunion.AYUD and s.afecta_disponibilidad]
    check(len(ayud_mal) == 0,
          f"Todas las AYUD tienen afecta_disponibilidad=False (hay {len(ayud_mal)} en True)")

    no_ayud_mal = [s for s in secciones
                   if s.componente != TipoReunion.AYUD and not s.afecta_disponibilidad]
    check(len(no_ayud_mal) == 0,
          f"Todas las CLAS/LABT tienen afecta_disponibilidad=True (hay {len(no_ayud_mal)} en False)")

    ids = [s.id for s in secciones]
    check(len(ids) == len(set(ids)), "Todos los IDs de sección son únicos")

    print("  → secciones OK")


def test_horas_a_bloques(datos):
    print("\n--- test_horas_a_bloques ---")

    secciones = datos.secciones
    cursos    = datos.cursos

    # ING1100: 8h de clases → 4 bloques por sección CLAS
    ing1100_clas = [s for s in secciones
                    if s.codigo_curso == "ING1100" and s.componente == TipoReunion.CLAS]
    check(len(ing1100_clas) > 0, "Hay secciones CLAS de ING1100")
    for s in ing1100_clas:
        check(s.cantidad_bloques_necesarios == 4,
              f"ING1100 CLAS tiene 4 bloques (sección {s.seccion}: {s.cantidad_bloques_necesarios})")

    # Cursos con 3h de clases → 1 bloque de 3h
    cursos_3h = [c for c in cursos.values() if c.clases_horas == 3]
    check(len(cursos_3h) > 0, "Hay cursos con 3h de clases")
    for curso in cursos_3h:
        for s in secciones:
            if s.codigo_curso == curso.codigo and s.componente == TipoReunion.CLAS:
                check(s.cantidad_bloques_necesarios == 1,
                      f"{curso.codigo} (3h) CLAS → 1 bloque (es {s.cantidad_bloques_necesarios})")

    # Cursos con 2h → 1 bloque
    for s in secciones:
        curso = cursos.get(s.codigo_curso)
        if not curso:
            continue
        if s.componente == TipoReunion.CLAS and curso.clases_horas == 2:
            check(s.cantidad_bloques_necesarios == 1,
                  f"{s.codigo_curso} (2h) CLAS → 1 bloque (es {s.cantidad_bloques_necesarios})")

    check(all(s.cantidad_bloques_necesarios >= 1 for s in secciones),
          "Todas las secciones tienen >= 1 bloque necesario")

    print("  → horas_a_bloques OK")


def test_profesores(datos):
    print("\n--- test_profesores ---")

    profesores = datos.profesores
    check(len(profesores) == 130, f"130 profesores (hay {len(profesores)})")

    por_tipo = {}
    for p in profesores.values():
        por_tipo[p.tipo.value] = por_tipo.get(p.tipo.value, 0) + 1

    check(por_tipo.get("JORNADA", 0) == 37,
          f"37 JORNADA (hay {por_tipo.get('JORNADA', 0)})")
    check(por_tipo.get("HONORARIO", 0) == 91,
          f"91 HONORARIO (hay {por_tipo.get('HONORARIO', 0)})")
    check(por_tipo.get("PENDIENTE", 0) == 2,
          f"2 PENDIENTE (hay {por_tipo.get('PENDIENTE', 0)})")

    ruts_prof = set(datos.profesores.keys())
    for s in datos.secciones:
        check(s.rut_profesor in ruts_prof,
              f"Profesor {s.rut_profesor} de sección {s.id} existe en el listado")

    print("  → profesores OK")


def test_salas_especiales(datos):
    print("\n--- test_salas_especiales ---")

    cursos_con_sala = [c for c in datos.cursos.values() if c.sala_especial]
    check(len(cursos_con_sala) > 0, "Hay cursos con sala especial")

    ing1100 = datos.cursos.get("ING1100")
    check(ing1100 is not None and ing1100.sala_especial is None,
          "ING1100 no tiene sala especial")

    icc = datos.cursos.get("ICC4101")
    check(icc is not None and icc.sala_especial is not None,
          f"ICC4101 tiene sala especial ({icc.sala_especial if icc else 'N/A'})")

    print("  → salas_especiales OK")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    print("Cargando datos desde", INPUTS_DIR)
    datos = cargar_datos(INPUTS_DIR)

    fallidos = []
    for nombre, fn in [
        ("blocks",          lambda: test_blocks()),
        ("cursos",          lambda: test_cursos(datos)),
        ("secciones",       lambda: test_secciones(datos)),
        ("horas_a_bloques", lambda: test_horas_a_bloques(datos)),
        ("profesores",      lambda: test_profesores(datos)),
        ("salas_especiales",lambda: test_salas_especiales(datos)),
    ]:
        try:
            fn()
        except AssertionError as e:
            fallidos.append((nombre, str(e)))
        except Exception as e:
            fallidos.append((nombre, f"ERROR inesperado: {e}"))

    print()
    if fallidos:
        print(f"RESULTADO: {len(fallidos)} test(s) FALLARON:")
        for nombre, msg in fallidos:
            print(f"  ✗ {nombre}: {msg}")
        sys.exit(1)
    else:
        print("RESULTADO: TODOS LOS TESTS PASARON ✓")


if __name__ == "__main__":
    main()
