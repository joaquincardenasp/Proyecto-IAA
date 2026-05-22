"""
Parser — lee los 5 archivos Excel de input y construye DatosProblema.

Orden de lectura:
1. Catálogos (3 archivos) → unión de cursos con semestres por carrera
2. Salas especiales → mapeadas a cursos
3. Profesores (hoja "profesores")
4. Asignaciones (hoja "asignaciones") → crea Secciones
5. Disponibilidad (hoja "disponibilidad") — OPCIONAL v1

Diseño clave:
- Los 3 planes de estudio comparten las mismas secciones y bloques.
  Lo que cambia entre planes es en qué semestre cae un curso para RD1.
- semestres_por_carrera acumula la UNIÓN de semestres de todos los planes.
  Si PE2022 dice ICC-7 y PE2025 dice ICC-6, el curso queda con ICC-{"7","6"}.
- Los semestres se guardan como STRINGS preservando sufijos de mención:
  "9a", "9f", "10i" son semestres distintos (menciones distintas en ICI/IOC).
  Esto evita topes falsos entre alumnos de distintas menciones.
"""
from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd

from .models import Curso, DatosProblema, Profesor, Seccion, TipoProfesor, TipoReunion

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Nombres de los planes y sus archivos (relativo a inputs/)
# ---------------------------------------------------------------------------
CATALOGOS = [
    ("PE2022",      "Copia de Catálogo PE 2022.xlsx"),
    ("PE2022_2025", "Copia de Catálogo PE 2022 y PE 2025.xlsx"),
    ("PE2026",      "Copia de Catálogo PE 2026.xlsx"),
]

ARCHIVO_PROFESORES = "profesores_completo.xlsx"
ARCHIVO_SALAS      = "SALAS_ESPECIALES_ING.xlsx"

CARRERAS_ESPECIALIDAD = ["ICI", "IOC", "ICE", "ICC", "ICA", "ICQ"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_semestre(val) -> Optional[str]:
    """
    Convierte un valor de semestre a string canónico, preservando sufijos de mención.

    - int/float numérico positivo → str(int(val))  ej. 1.0 → "1"
    - string que empieza con dígito → se mantiene tal cual  ej. "9a" → "9a"
    - 0, NaN, None, '*', '\xa0', etc. → None (sin semestre)
    """
    if val is None:
        return None
    if isinstance(val, float):
        if math.isnan(val):
            return None
        v = int(val)
        return str(v) if v > 0 else None
    if isinstance(val, int):
        return str(val) if val > 0 else None
    # string
    s = str(val).strip()
    if not s or s == "\xa0":
        return None
    if s[0].isdigit():
        return s  # preservar "9a", "10f", "5hi", "9", etc.
    return None   # '*' u otros caracteres no numéricos


def _parse_horas(val) -> int:
    """Convierte un valor de horas (puede ser NaN, str vacío o float) a int."""
    if val is None:
        return 0
    if isinstance(val, str):
        val = val.strip()
        if not val or val == "\xa0":
            return 0
        # Puede haber "2+1" → tomamos solo el primer número para v1
        import re
        m = re.match(r"(\d+)", val)
        return int(m.group(1)) if m else 0
    if isinstance(val, float):
        return 0 if math.isnan(val) else int(val)
    return int(val)


def _calcular_bloques_necesarios(horas: int) -> int:
    """
    Número de bloques horarios que necesita una sección según sus horas semanales.

    - 3h → 1 bloque de 3h
    - otros → ceil(horas / 2) bloques de 2h; mínimo 1
    """
    if horas <= 0:
        return 1
    if horas == 3:
        return 1  # 1 bloque de 3h
    return max(1, math.ceil(horas / 2))


# ---------------------------------------------------------------------------
# 1. Lectura de catálogos
# ---------------------------------------------------------------------------

def _leer_un_catalogo(path: Path, plan: str, cursos: dict[str, Curso]) -> None:
    """
    Lee un archivo de catálogo y actualiza el dict de cursos.

    Para cada curso:
    - Agrega `plan` al set curso.planes
    - Hace UNIÓN de semestres en curso.semestres_por_carrera
    """
    df = pd.read_excel(path, header=1)
    if "Unnamed: 0" in df.columns:
        df = df.drop(columns=["Unnamed: 0"])

    for _, row in df.iterrows():
        codigo = str(row.get("CODIGO", "")).strip()
        if not codigo or codigo == "nan":
            continue

        titulo    = str(row.get("TITULO", "")).strip()
        clases_h  = _parse_horas(row.get("Clases"))
        ayud_h    = _parse_horas(row.get("Ayudantías"))
        lab_h     = _parse_horas(row.get("Laboratorios o Talleres"))

        # Semestre: Plan Común tiene prioridad (ver CONTEXT.md §5 y PRD §4)
        pc = _parse_semestre(row.get("Plan Común"))

        if pc is not None:
            # Curso de plan común: usar SOLO la columna "Plan Común"
            semestres_nuevos: dict[str, str] = {"Plan Común": pc}
        else:
            # Curso de especialidad: leer columnas de carrera
            semestres_nuevos = {}
            for carrera in CARRERAS_ESPECIALIDAD:
                sem = _parse_semestre(row.get(carrera))
                if sem is not None:
                    semestres_nuevos[carrera] = sem

        # Crear curso si no existe
        if codigo not in cursos:
            cursos[codigo] = Curso(
                codigo=codigo,
                titulo=titulo,
                clases_horas=clases_h,
                ayudantias_horas=ayud_h,
                laboratorios_horas=lab_h,
            )
        else:
            # Actualizar horas solo si el campo está vacío
            c = cursos[codigo]
            if c.clases_horas == 0 and clases_h > 0:
                c.clases_horas = clases_h
            if c.ayudantias_horas == 0 and ayud_h > 0:
                c.ayudantias_horas = ayud_h
            if c.laboratorios_horas == 0 and lab_h > 0:
                c.laboratorios_horas = lab_h

        curso = cursos[codigo]
        curso.planes.add(plan)

        # Unión de semestres por carrera (acumula a través de planes)
        for carrera, sem in semestres_nuevos.items():
            curso.semestres_por_carrera.setdefault(carrera, set()).add(sem)


def leer_catalogos(inputs_dir: Path) -> dict[str, Curso]:
    """Lee los 3 catálogos y retorna el dict unificado de cursos."""
    cursos: dict[str, Curso] = {}
    for plan, fname in CATALOGOS:
        _leer_un_catalogo(inputs_dir / fname, plan, cursos)
    return cursos


# ---------------------------------------------------------------------------
# 2. Salas especiales
# ---------------------------------------------------------------------------

def leer_salas_especiales(inputs_dir: Path) -> dict[str, str]:
    """Retorna {codigo_curso: nombre_sala}."""
    df = pd.read_excel(inputs_dir / ARCHIVO_SALAS)
    return {
        str(row["CODIGO"]).strip(): str(row["SALA ESPECIAL"]).strip()
        for _, row in df.iterrows()
        if str(row.get("CODIGO", "")).strip() not in ("", "nan")
    }


# ---------------------------------------------------------------------------
# 3 & 4. Profesores y asignaciones
# ---------------------------------------------------------------------------

def leer_profesores(xl: pd.ExcelFile) -> dict[str, Profesor]:
    """Lee hoja 'profesores' y retorna {rut: Profesor}."""
    df = xl.parse("profesores")
    profesores: dict[str, Profesor] = {}
    for _, row in df.iterrows():
        rut    = str(row["rut_profesor"]).strip()
        nombre = str(row["nombre_profesor"]).strip()
        tipo_s = str(row["tipo_profesor"]).strip().upper()
        try:
            tipo = TipoProfesor[tipo_s]
        except KeyError:
            tipo = TipoProfesor.PENDIENTE
        profesores[rut] = Profesor(rut=rut, nombre=nombre, tipo=tipo)
    return profesores


def leer_asignaciones(xl: pd.ExcelFile, cursos: dict[str, Curso]) -> list[Seccion]:
    """Lee hoja 'asignaciones' y retorna lista de Seccion."""
    df = xl.parse("asignaciones")
    secciones: list[Seccion] = []

    for _, row in df.iterrows():
        rut        = str(row["rut_profesor"]).strip()
        codigo     = str(row["codigo_curso"]).strip()
        seccion_id = str(row["seccion"]).strip()
        comp_s     = str(row["componente"]).strip().upper()
        afecta     = bool(row["afecta_disponibilidad"])

        try:
            componente = TipoReunion[comp_s]
        except KeyError:
            continue

        curso = cursos.get(codigo)
        if curso is None:
            horas = 2
        else:
            if componente == TipoReunion.CLAS:
                horas = curso.clases_horas
            elif componente == TipoReunion.AYUD:
                horas = curso.ayudantias_horas
            else:  # LABT
                horas = curso.laboratorios_horas

        n_bloques = _calcular_bloques_necesarios(horas)

        secciones.append(Seccion(
            id=f"{codigo}-{seccion_id}-{comp_s}",
            codigo_curso=codigo,
            seccion=seccion_id,
            componente=componente,
            rut_profesor=rut,
            afecta_disponibilidad=afecta,
            cantidad_bloques_necesarios=n_bloques,
        ))

    return secciones


# ---------------------------------------------------------------------------
# 5. Disponibilidad (opcional v1)
# ---------------------------------------------------------------------------

def leer_disponibilidad(xl: pd.ExcelFile) -> dict[str, list[dict]]:
    """
    Lee hoja 'disponibilidad'. Retorna {rut: [{dia, bloque_inicio, bloque_fin}]}.
    Opcional en v1 — si hay error, retorna dict vacío.
    """
    try:
        df = xl.parse("disponibilidad")
        disp: dict[str, list[dict]] = {}
        for _, row in df.iterrows():
            rut = str(row["rut_profesor"]).strip()
            disp.setdefault(rut, []).append({
                "dia":           str(row["dia"]).strip(),
                "bloque_inicio": str(row["bloque_inicio"]).strip(),
                "bloque_fin":    str(row["bloque_fin"]).strip(),
            })
        return disp
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def cargar_datos(inputs_dir: str | Path) -> DatosProblema:
    """Lee los 5 archivos Excel y construye DatosProblema. Imprime resumen."""
    inputs_dir = Path(inputs_dir)

    cursos = leer_catalogos(inputs_dir)

    salas = leer_salas_especiales(inputs_dir)
    for codigo, sala in salas.items():
        if codigo in cursos:
            cursos[codigo].sala_especial = sala

    xl = pd.ExcelFile(inputs_dir / ARCHIVO_PROFESORES)
    profesores = leer_profesores(xl)
    secciones  = leer_asignaciones(xl, cursos)
    leer_disponibilidad(xl)  # cargado pero no usado en v1

    datos = DatosProblema(cursos=cursos, secciones=secciones, profesores=profesores)
    _imprimir_resumen(datos)
    return datos


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def _imprimir_resumen(datos: DatosProblema) -> None:
    cursos    = datos.cursos
    secciones = datos.secciones
    profesores = datos.profesores

    print("=" * 60)
    print("RESUMEN DEL PROBLEMA")
    print("=" * 60)

    # Cursos por plan (usando campo planes)
    conteo_por_plan: dict[str, int] = {}
    for curso in cursos.values():
        for plan in curso.planes:
            conteo_por_plan[plan] = conteo_por_plan.get(plan, 0) + 1

    print(f"\nCursos únicos totales: {len(cursos)}")
    for plan, n in sorted(conteo_por_plan.items()):
        print(f"  {plan}: {n} cursos")

    # Cursos con múltiples semestres en alguna carrera (efecto de planes distintos)
    multi_sem = [
        (c.codigo, carrera, sems)
        for c in cursos.values()
        for carrera, sems in c.semestres_por_carrera.items()
        if len(sems) > 1
    ]
    if multi_sem:
        print(f"\nCursos con semestre distinto según plan: {len(multi_sem)}")
        for codigo, carrera, sems in sorted(multi_sem):
            print(f"  {codigo} ({carrera}): {sorted(sems)}")

    # Secciones por componente
    por_componente: dict[str, int] = {}
    for sec in secciones:
        por_componente[sec.componente.value] = por_componente.get(sec.componente.value, 0) + 1
    print(f"\nSecciones totales: {len(secciones)}")
    for comp, n in sorted(por_componente.items()):
        print(f"  {comp}: {n}")

    # Profesores por tipo
    por_tipo: dict[str, int] = {}
    for prof in profesores.values():
        por_tipo[prof.tipo.value] = por_tipo.get(prof.tipo.value, 0) + 1
    print(f"\nProfesores totales: {len(profesores)}")
    for tipo, n in sorted(por_tipo.items()):
        print(f"  {tipo}: {n}")

    # Secciones con múltiples bloques
    multi = [s for s in secciones if s.cantidad_bloques_necesarios > 1]
    print(f"\nSecciones con múltiples bloques: {len(multi)}")
    if multi:
        resumen_multi: dict[int, int] = {}
        for s in multi:
            n = s.cantidad_bloques_necesarios
            resumen_multi[n] = resumen_multi.get(n, 0) + 1
        for n_bloques, cnt in sorted(resumen_multi.items()):
            print(f"  {n_bloques} bloques: {cnt} secciones")

    ayud_no_afecta = [s for s in secciones
                      if s.componente == TipoReunion.AYUD and not s.afecta_disponibilidad]
    print(f"\nAYUD con afecta_disponibilidad=False: {len(ayud_no_afecta)}")
    print("=" * 60)
