"""
Parser — lee los 5 archivos Excel de input y construye DatosProblema.

Orden de lectura:
1. Catálogos (3 archivos) → union de cursos con semestres por plan
2. Salas especiales → mapeadas a cursos
3. Profesores (hoja "profesores")
4. Asignaciones (hoja "asignaciones") → crea Secciones
5. Disponibilidad (hoja "disponibilidad") — OPCIONAL v1
"""
from __future__ import annotations

import math
import re
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

ARCHIVO_PROFESORES    = "profesores_completo.xlsx"
ARCHIVO_SALAS         = "SALAS_ESPECIALES_ING.xlsx"

CARRERAS_ESPECIALIDAD = ["ICI", "IOC", "ICE", "ICC", "ICA", "ICQ"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_semestre(val) -> Optional[int]:
    """Convierte un valor de semestre (int, float o str como '9a', '10f') a int."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    if isinstance(val, (int, float)):
        v = int(val)
        return v if v > 0 else None
    # string: extraer el primer número
    m = re.match(r"(\d+)", str(val).strip())
    if m:
        return int(m.group(1))
    return None


def _parse_horas(val) -> int:
    """Convierte un valor de horas (puede ser NaN, str vacío o float) a int."""
    if val is None:
        return 0
    if isinstance(val, str):
        val = val.strip()
        if not val or val == "\xa0":
            return 0
        m = re.match(r"(\d+)", val)
        return int(m.group(1)) if m else 0
    if isinstance(val, float):
        if math.isnan(val):
            return 0
        return int(val)
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
    """Lee un archivo de catálogo y actualiza el dict de cursos."""
    df = pd.read_excel(path, header=1)

    # PE2026 tiene una columna extra 'Unnamed: 0' al inicio
    if "Unnamed: 0" in df.columns:
        df = df.drop(columns=["Unnamed: 0"])

    for _, row in df.iterrows():
        codigo = str(row.get("CODIGO", "")).strip()
        if not codigo or codigo == "nan":
            continue

        titulo = str(row.get("TITULO", "")).strip()
        clases_h = _parse_horas(row.get("Clases"))
        ayud_h   = _parse_horas(row.get("Ayudantías"))
        lab_h    = _parse_horas(row.get("Laboratorios o Talleres"))

        # Semestre: Plan Común tiene prioridad (ver CONTEXT.md §5)
        pc = _parse_semestre(row.get("Plan Común"))

        if pc is not None and pc > 0:
            semestres = {"Plan Común": pc}
        else:
            semestres = {}
            for carrera in CARRERAS_ESPECIALIDAD:
                sem = _parse_semestre(row.get(carrera))
                if sem is not None and sem > 0:
                    semestres[carrera] = sem

        # Incluir el curso aunque no tenga semestre asignado (cursos electivos, etc.)
        # Solo omitir si el semestre ya existe para que no sobrescriba datos buenos

        if codigo not in cursos:
            cursos[codigo] = Curso(
                codigo=codigo,
                titulo=titulo,
                semestres_por_plan={},
                clases_horas=clases_h,
                ayudantias_horas=ayud_h,
                laboratorios_horas=lab_h,
            )
        else:
            # Actualizar horas solo si el curso ya existe y las horas son 0
            curso = cursos[codigo]
            if curso.clases_horas == 0 and clases_h > 0:
                curso.clases_horas = clases_h
            if curso.ayudantias_horas == 0 and ayud_h > 0:
                curso.ayudantias_horas = ayud_h
            if curso.laboratorios_horas == 0 and lab_h > 0:
                curso.laboratorios_horas = lab_h

        cursos[codigo].semestres_por_plan[plan] = semestres


def leer_catalogos(inputs_dir: Path) -> dict[str, Curso]:
    """Lee los 3 catálogos y retorna el dict unificado de cursos."""
    cursos: dict[str, Curso] = {}
    for plan, fname in CATALOGOS:
        path = inputs_dir / fname
        _leer_un_catalogo(path, plan, cursos)
    return cursos


# ---------------------------------------------------------------------------
# 2. Salas especiales
# ---------------------------------------------------------------------------

def leer_salas_especiales(inputs_dir: Path) -> dict[str, str]:
    """Retorna {codigo_curso: nombre_sala}."""
    path = inputs_dir / ARCHIVO_SALAS
    df = pd.read_excel(path)
    salas: dict[str, str] = {}
    for _, row in df.iterrows():
        codigo = str(row.get("CODIGO", "")).strip()
        sala   = str(row.get("SALA ESPECIAL", "")).strip()
        if codigo and sala and codigo != "nan":
            salas[codigo] = sala
    return salas


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
            continue  # componente desconocido, ignorar

        # Calcular cuántos bloques necesita esta sección
        curso = cursos.get(codigo)
        if curso is None:
            horas = 2  # fallback: 1 bloque de 2h
        else:
            if componente == TipoReunion.CLAS:
                horas = curso.clases_horas
            elif componente == TipoReunion.AYUD:
                horas = curso.ayudantias_horas
            else:  # LABT
                horas = curso.laboratorios_horas

        n_bloques = _calcular_bloques_necesarios(horas)

        sec_id = f"{codigo}-{seccion_id}-{comp_s}"
        secciones.append(Seccion(
            id=sec_id,
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
                "dia":          str(row["dia"]).strip(),
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
    """
    Lee los 5 archivos Excel y construye DatosProblema.

    Imprime un resumen al final.
    """
    inputs_dir = Path(inputs_dir)

    # 1. Catálogos
    cursos = leer_catalogos(inputs_dir)

    # 2. Salas especiales → asignar a cursos
    salas = leer_salas_especiales(inputs_dir)
    for codigo, sala in salas.items():
        if codigo in cursos:
            cursos[codigo].sala_especial = sala

    # 3 & 4. Profesores + asignaciones
    xl = pd.ExcelFile(inputs_dir / ARCHIVO_PROFESORES)
    profesores = leer_profesores(xl)
    secciones  = leer_asignaciones(xl, cursos)

    # 5. Disponibilidad (opcional)
    leer_disponibilidad(xl)  # cargada pero no usada en v1

    datos = DatosProblema(
        cursos=cursos,
        secciones=secciones,
        profesores=profesores,
    )

    _imprimir_resumen(datos)
    return datos


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def _imprimir_resumen(datos: DatosProblema) -> None:
    cursos = datos.cursos
    secciones = datos.secciones
    profesores = datos.profesores

    print("=" * 60)
    print("RESUMEN DEL PROBLEMA")
    print("=" * 60)

    # Total cursos por plan
    conteo_por_plan: dict[str, int] = {}
    for curso in cursos.values():
        for plan in curso.semestres_por_plan:
            conteo_por_plan[plan] = conteo_por_plan.get(plan, 0) + 1
    print(f"\nCursos únicos totales: {len(cursos)}")
    for plan, n in sorted(conteo_por_plan.items()):
        print(f"  {plan}: {n} cursos")

    # Total secciones por componente
    por_componente: dict[str, int] = {}
    for sec in secciones:
        key = sec.componente.value
        por_componente[key] = por_componente.get(key, 0) + 1
    print(f"\nSecciones totales: {len(secciones)}")
    for comp, n in sorted(por_componente.items()):
        print(f"  {comp}: {n}")

    # Total profesores por tipo
    por_tipo: dict[str, int] = {}
    for prof in profesores.values():
        key = prof.tipo.value
        por_tipo[key] = por_tipo.get(key, 0) + 1
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

    # AYUD con afecta_disponibilidad=False
    ayud_no_afecta = [s for s in secciones
                      if s.componente == TipoReunion.AYUD and not s.afecta_disponibilidad]
    print(f"\nAYUD con afecta_disponibilidad=False: {len(ayud_no_afecta)}")

    print("=" * 60)
