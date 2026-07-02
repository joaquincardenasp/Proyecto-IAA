"""
test_parser.py — Valida que el parser del Maestro produce un DatosProblema correcto.

Ejecutar desde backend/:
    python -m pytest tests/test_parser.py -v
    python tests/test_parser.py

Hay dos tipos de checks:
  1. INVARIANTES: siempre deben cumplirse independientemente de los datos.
  2. CONTEOS ESPERADOS: dependen del semestre/maestro real. Marcados con
     "# AJUSTAR" para que el usuario los complete tras la primera ejecución.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.blocks import MATRIZ_SOLAPAMIENTO, N_BLOQUES, TODOS_BLOQUES, bloques_se_solapan
from app.core.models import TipoReunion
from app.core.parser import cargar_datos

INPUTS_DIR = Path(__file__).parent.parent / "inputs"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def check(cond: bool, msg: str) -> None:
    estado = "✓" if cond else "✗ FALLO"
    print(f"  [{estado}] {msg}")
    if not cond:
        raise AssertionError(f"FALLO: {msg}")


# ---------------------------------------------------------------------------
# Test: bloques horarios (invariante, no depende del maestro)
# ---------------------------------------------------------------------------

def test_blocks() -> None:
    print("\n--- test_blocks ---")

    # Catálogo: 29 tipos (2h/3h estándar + helper + 1h para 2+1) × 5 días = 145
    check(N_BLOQUES == 145, f"145 bloques totales (hay {N_BLOQUES})")

    # Estándar: 5 (2h) + 2 (3h) + 10 (1h) = 17 tipos × 5 días = 85
    estandar = [b for b in TODOS_BLOQUES if b.es_estandar]
    check(len(estandar) == 85, f"85 bloques estándar (17 tipos × 5 días) (hay {len(estandar)})")

    # Los bloques 3h ESTÁNDAR inician en 10:30 o 12:30; los helper rellenan otros inicios
    b3h_std = [b for b in TODOS_BLOQUES if b.tipo == "3h" and b.es_estandar]
    check(len(b3h_std) == 10, f"10 bloques 3h estándar (hay {len(b3h_std)})")
    for b in b3h_std:
        check(
            b.hora_inicio in ("10:30", "12:30"),
            f"bloque 3h estándar inicia en 10:30 o 12:30 (es {b.hora_inicio})",
        )

    lunes = [b for b in TODOS_BLOQUES if b.dia.value == "L"]

    # Bloques 2h existentes: 8:30, 10:30, 13:30, 15:30, 17:30 — ningún par de 2h se solapa.
    # Para solapamiento necesitamos un bloque 3h que comparte sub-bloques con un 2h.

    # 10:30-13:20 (3h) y 10:30-12:20 (2h) se solapan (comparten sub-bloques 10:30, 11:30)
    b1 = next(b for b in lunes if b.hora_inicio == "10:30" and b.tipo == "3h")
    b2 = next(b for b in lunes if b.hora_inicio == "10:30" and b.tipo == "2h")
    check(bloques_se_solapan(b1, b2), "10:30-13:20 (3h) y 10:30-12:20 (2h) se solapan")

    # 10:30-13:20 y 12:30-15:20 se solapan (sub-bloque 12:30)
    b3 = next(b for b in lunes if b.hora_inicio == "10:30" and b.tipo == "3h")
    b4 = next(b for b in lunes if b.hora_inicio == "12:30" and b.tipo == "3h")
    check(bloques_se_solapan(b3, b4), "10:30-13:20 y 12:30-15:20 (L) se solapan")

    # 12:30-15:20 (3h) y 13:30-15:20 (2h) se solapan (sub-bloques 13:30, 14:30)
    b5 = next(b for b in lunes if b.hora_inicio == "12:30" and b.tipo == "3h")
    b6 = next(b for b in lunes if b.hora_inicio == "13:30" and b.tipo == "2h")
    check(bloques_se_solapan(b5, b6), "12:30-15:20 (3h) y 13:30-15:20 (2h) se solapan")

    # 8:30-10:20 y 10:30-12:20 NO se solapan (consecutivos, no comparten sub-bloques)
    b7 = next(b for b in lunes if b.hora_inicio == "8:30")
    b8 = next(b for b in lunes if b.hora_inicio == "10:30" and b.tipo == "2h")
    check(not bloques_se_solapan(b7, b8), "8:30-10:20 y 10:30-12:20 NO se solapan")

    # 13:30-15:20 y 15:30-17:20 NO se solapan (consecutivos)
    b9  = next(b for b in lunes if b.hora_inicio == "13:30" and b.tipo == "2h")
    b10 = next(b for b in lunes if b.hora_inicio == "15:30" and b.tipo == "2h")
    check(not bloques_se_solapan(b9, b10), "13:30-15:20 y 15:30-17:20 NO se solapan")

    # Días distintos nunca se solapan
    l830 = next(b for b in TODOS_BLOQUES if b.dia.value == "L" and b.hora_inicio == "8:30")
    m830 = next(b for b in TODOS_BLOQUES if b.dia.value == "M" and b.hora_inicio == "8:30")
    check(not bloques_se_solapan(l830, m830), "8:30 Lunes y 8:30 Martes NO se solapan")

    check(
        all(
            MATRIZ_SOLAPAMIENTO[i][j] == MATRIZ_SOLAPAMIENTO[j][i]
            for i in range(N_BLOQUES)
            for j in range(N_BLOQUES)
        ),
        "MATRIZ_SOLAPAMIENTO es simétrica",
    )

    print("  → blocks OK")


# ---------------------------------------------------------------------------
# Test: carga básica (invariantes estructurales)
# ---------------------------------------------------------------------------

def test_carga_basica(datos) -> None:
    print("\n--- test_carga_basica ---")

    check(len(datos.cursos) > 0, "Hay al menos un curso")
    check(len(datos.secciones) > 0, "Hay al menos una sección")
    check(len(datos.profesores) > 0, "Hay al menos un profesor")

    # Contar secciones esperadas — AJUSTAR con los valores reales del maestro:
    # check(len(datos.cursos)    == ???, f"??? cursos únicos (hay {len(datos.cursos)})")
    # check(len(datos.secciones) == ???, f"??? secciones totales (hay {len(datos.secciones)})")
    # check(len(datos.profesores) == ???, f"??? profesores (hay {len(datos.profesores)})")

    por_comp: dict[str, int] = {}
    for s in datos.secciones:
        por_comp[s.componente.value] = por_comp.get(s.componente.value, 0) + 1

    print(f"  Cursos: {len(datos.cursos)}")
    print(f"  Secciones: {len(datos.secciones)} "
          f"(CLAS={por_comp.get('CLAS',0)}, "
          f"AYUD={por_comp.get('AYUD',0)}, "
          f"LABT={por_comp.get('LABT',0)})")
    print(f"  Profesores: {len(datos.profesores)}")

    # Descomentar con los valores observados en la primera ejecución:
    # check(por_comp.get("CLAS", 0) == ???, f"??? CLAS (hay {por_comp.get('CLAS', 0)})")
    # check(por_comp.get("AYUD", 0) == ???, f"??? AYUD (hay {por_comp.get('AYUD', 0)})")
    # check(por_comp.get("LABT", 0) == ???, f"??? LABT (hay {por_comp.get('LABT', 0)})")

    print("  → carga_basica OK")


# ---------------------------------------------------------------------------
# Test: invariantes de secciones
# ---------------------------------------------------------------------------

def test_invariantes_secciones(datos) -> None:
    print("\n--- test_invariantes_secciones ---")

    secciones = datos.secciones

    # IDs únicos
    ids = [s.id for s in secciones]
    check(len(ids) == len(set(ids)), "Todos los IDs de sección son únicos")

    # AYUD siempre afecta_disponibilidad=False
    ayud_mal = [s for s in secciones
                if s.componente == TipoReunion.AYUD and s.afecta_disponibilidad]
    check(
        len(ayud_mal) == 0,
        f"Todas las AYUD tienen afecta_disponibilidad=False "
        f"(hay {len(ayud_mal)} en True)",
    )

    # CLAS con profesor → afecta_disponibilidad=True (la cátedra la dicta el profesor)
    clas_con_prof = [
        s for s in secciones
        if s.componente == TipoReunion.CLAS and s.rut_profesor
    ]
    clas_mal = [s for s in clas_con_prof if not s.afecta_disponibilidad]
    check(
        len(clas_mal) == 0,
        f"Todas las CLAS con profesor tienen afecta_disponibilidad=True "
        f"(hay {len(clas_mal)} en False)",
    )

    # LABT: afecta_disponibilidad=True solo si hay profesor de laboratorio dedicado.
    # Las LABT dictadas por un TA (sin RUT PROFESOR LABT) tienen afecta=False aunque
    # rut_profesor conserve el profesor de cátedra como referencia de display.
    # Invariante verificable: afecta=True ⇒ existe un rut_profesor.
    afecta_sin_prof = [s for s in secciones if s.afecta_disponibilidad and not s.rut_profesor]
    check(
        len(afecta_sin_prof) == 0,
        f"Toda sección con afecta_disponibilidad=True tiene profesor asignado "
        f"(hay {len(afecta_sin_prof)} sin profesor)",
    )

    # Informativo: cuántas LABT son dictadas por TA (afecta=False)
    labt_ta = [s for s in secciones
               if s.componente == TipoReunion.LABT and not s.afecta_disponibilidad]
    print(f"  LABT dictadas por TA (afecta_disponibilidad=False): {len(labt_ta)}")

    # Todas las secciones tienen >= 1 bloque
    check(
        all(s.cantidad_bloques_necesarios >= 1 for s in secciones),
        "Todas las secciones tienen cantidad_bloques_necesarios >= 1",
    )

    # id en formato "{codigo}-{seccion}-{componente}"
    for s in secciones:
        partes = s.id.split("-")
        check(
            len(partes) >= 3,
            f"ID '{s.id}' tiene al menos 3 segmentos separados por '-'",
        )
        check(
            s.id.endswith(("-CLAS", "-AYUD", "-LABT")),
            f"ID '{s.id}' termina en -CLAS, -AYUD o -LABT",
        )

    # Todos los cursos referenciados existen
    codigos_cursos = set(datos.cursos.keys())
    for s in secciones:
        check(
            s.codigo_curso in codigos_cursos,
            f"Curso '{s.codigo_curso}' (sección {s.id}) existe en datos.cursos",
        )

    # Todos los profesores referenciados existen (si rut no está vacío)
    ruts_prof = set(datos.profesores.keys())
    for s in secciones:
        if s.rut_profesor:
            check(
                s.rut_profesor in ruts_prof,
                f"Profesor '{s.rut_profesor}' de sección '{s.id}' existe en datos.profesores",
            )

    print("  → invariantes_secciones OK")


# ---------------------------------------------------------------------------
# Test: invariantes de cursos (semestres)
# ---------------------------------------------------------------------------

def test_invariantes_cursos(datos) -> None:
    print("\n--- test_invariantes_cursos ---")

    # Todos los semestres son strings
    for codigo, curso in datos.cursos.items():
        for carrera, sems in curso.semestres_por_carrera.items():
            for sem in sems:
                check(
                    isinstance(sem, str),
                    f"{codigo} ({carrera}): semestre '{sem}' debe ser string",
                )

    # Cursos Plan Común NO tienen columnas de especialidad
    for codigo, curso in datos.cursos.items():
        if "Plan Común" in curso.semestres_por_carrera:
            especialidades = [
                c for c in curso.semestres_por_carrera
                if c != "Plan Común"
            ]
            check(
                len(especialidades) == 0,
                f"{codigo}: curso Plan Común no debe tener carreras de especialidad {especialidades}",
            )

    # Sufijos de mención se preservan: si existen "9a" o "9f", no deben colapsar a "9"
    for codigo, curso in datos.cursos.items():
        for carrera, sems in curso.semestres_por_carrera.items():
            if any(s.startswith("9") and len(s) > 1 for s in sems):
                check(
                    "9" not in sems,
                    f"{codigo} ({carrera}): tiene semestres con mención pero también '9' genérico: {sems}",
                )

    # Semestres son strings con primer carácter dígito (o vacíos, lo que no debe pasar)
    for codigo, curso in datos.cursos.items():
        for carrera, sems in curso.semestres_por_carrera.items():
            for sem in sems:
                check(
                    sem and sem[0].isdigit(),
                    f"{codigo} ({carrera}): semestre '{sem}' debe empezar con dígito",
                )

    print("  → invariantes_cursos OK")


# ---------------------------------------------------------------------------
# Test: horas → bloques
# ---------------------------------------------------------------------------

def test_horas_a_bloques(datos) -> None:
    print("\n--- test_horas_a_bloques ---")

    secciones = datos.secciones
    cursos    = datos.cursos

    # 2h → 1 bloque
    for s in secciones:
        curso = cursos.get(s.codigo_curso)
        if not curso:
            continue
        # Las secciones 2+1 (tipos_bloques_necesarios=["2h","1h"]) llevan 2 bloques
        # legítimamente (uno de 2h + uno de 1h), aunque el curso tenga clases_horas == 2.
        if (s.componente == TipoReunion.CLAS and curso.clases_horas == 2
                and not s.tipos_bloques_necesarios):
            check(
                s.cantidad_bloques_necesarios == 1,
                f"{s.codigo_curso} (2h CLAS) → 1 bloque (es {s.cantidad_bloques_necesarios})",
            )
        if s.componente == TipoReunion.AYUD and curso.ayudantias_horas == 2:
            check(
                s.cantidad_bloques_necesarios == 1,
                f"{s.codigo_curso} (2h AYUD) → 1 bloque (es {s.cantidad_bloques_necesarios})",
            )

    # 4h → 2 bloques (comprobado para CLAS con distribución "2")
    for s in secciones:
        curso = cursos.get(s.codigo_curso)
        if not curso:
            continue
        if s.componente == TipoReunion.CLAS and curso.clases_horas == 4:
            check(
                s.cantidad_bloques_necesarios in (1, 2),
                f"{s.codigo_curso} (4h CLAS) → 1 o 2 bloques (es {s.cantidad_bloques_necesarios})",
            )

    # Ninguna sección puede tener 0 bloques
    check(
        all(s.cantidad_bloques_necesarios >= 1 for s in secciones),
        "Ninguna sección tiene cantidad_bloques_necesarios < 1",
    )

    # Hay secciones con más de 1 bloque (multi-bloque)
    multi = [s for s in secciones if s.cantidad_bloques_necesarios > 1]
    check(len(multi) > 0, "Hay secciones con más de 1 bloque necesario")
    print(f"  Secciones multi-bloque: {len(multi)}")

    print("  → horas_a_bloques OK")


# ---------------------------------------------------------------------------
# Test: profesores
# ---------------------------------------------------------------------------

def test_profesores(datos) -> None:
    print("\n--- test_profesores ---")

    profesores = datos.profesores
    from app.core.models import TipoProfesor

    # Tipos válidos
    tipos_validos = {TipoProfesor.JORNADA, TipoProfesor.HONORARIO, TipoProfesor.PENDIENTE}
    for rut, prof in profesores.items():
        check(
            prof.tipo in tipos_validos,
            f"Profesor {rut} tiene tipo válido (es {prof.tipo})",
        )

    # Hay profesores de jornada
    jornada = [p for p in profesores.values() if p.tipo == TipoProfesor.JORNADA]
    check(len(jornada) > 0, f"Hay profesores de tipo JORNADA (hay {len(jornada)})")
    print(f"  JORNADA: {len(jornada)}")

    # Descomentar con valores reales:
    # check(len(jornada) == ???, f"??? profesores JORNADA (hay {len(jornada)})")

    print("  → profesores OK")


# ---------------------------------------------------------------------------
# Test: salas especiales
# ---------------------------------------------------------------------------

def test_salas_especiales(datos) -> None:
    print("\n--- test_salas_especiales ---")

    cursos_con_sala = [c for c in datos.cursos.values() if c.sala_especial]
    check(len(cursos_con_sala) > 0, "Hay cursos con sala especial")
    print(f"  Cursos con sala especial: {len(cursos_con_sala)}")

    # Los nombres de sala no deben contener " EN HORARIO DE " (ya parseado)
    for c in cursos_con_sala:
        check(
            " EN HORARIO DE " not in (c.sala_especial or "").upper(),
            f"{c.codigo}: sala_especial ya no contiene ' EN HORARIO DE ' (es '{c.sala_especial}')",
        )

    print("  → salas_especiales OK")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("Cargando datos desde", INPUTS_DIR)
    datos = cargar_datos(INPUTS_DIR)

    tests = [
        ("blocks",               lambda: test_blocks()),
        ("carga_basica",         lambda: test_carga_basica(datos)),
        ("invariantes_secciones",lambda: test_invariantes_secciones(datos)),
        ("invariantes_cursos",   lambda: test_invariantes_cursos(datos)),
        ("horas_a_bloques",      lambda: test_horas_a_bloques(datos)),
        ("profesores",           lambda: test_profesores(datos)),
        ("salas_especiales",     lambda: test_salas_especiales(datos)),
    ]

    fallidos: list[tuple[str, str]] = []
    for nombre, fn in tests:
        try:
            fn()
        except AssertionError as e:
            fallidos.append((nombre, str(e)))
        except Exception as e:
            import traceback
            fallidos.append((nombre, f"ERROR inesperado: {e}\n{traceback.format_exc()}"))

    print()
    if fallidos:
        print(f"RESULTADO: {len(fallidos)} test(s) FALLARON:")
        for nombre, msg in fallidos:
            print(f"  ✗ {nombre}: {msg}")
        sys.exit(1)
    else:
        print("RESULTADO: TODOS LOS TESTS PASARON ✓")
        print()
        print("Próximo paso: ejecutar los solvers y verificar 0 topes.")
        print("  Descomentar y ajustar los 'check' con conteos esperados en este archivo.")


if __name__ == "__main__":
    main()
