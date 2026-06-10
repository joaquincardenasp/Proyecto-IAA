"""
Parser — lee Maestro_XXXXXX.xlsx y SALAS_ESPECIALES_ING.xlsx y construye DatosProblema.

Fuentes:
  Maestro_XXXXXX.xlsx
    Hoja MAESTRO   → secciones a programar (filas con CURSO MANDANTE = "SI")
    Hoja PROFESORES → RUTs de profesores de jornada completa

  SALAS_ESPECIALES_ING.xlsx
    Hoja BBDD           → mapeo curso → sala especial
    Hoja SALAS ESPECIALES → inventario físico (tipo → cantidad de salas)

Columnas del MAESTRO buscadas por nombre (no por posición):
  CURSO MANDANTE      → filtro principal
  PLAN DE ESTUDIO     → plan al que pertenece la fila
  CODIGO              → código del curso
  TITULO              → nombre del curso
  SECCIONES           → número/letra de sección
  Plan Común          → semestre en plan común (prioridad sobre carreras)
  ICI / IOC / ICE / ICC / ICA → semestre por carrera (si Plan Común vacío)
  Clases A PROGRAMAR  → horas semanales de cátedra a programar
  Ayudantías PROGRAMAR / Ayudantías A PROGRAMAR → horas de ayudantía
  Laboratorios o Talleres PROGRAMAR              → horas de lab
  RUT PROFESOR 1 / NOMBRE PROFESOR 1             → profesor de cátedra
  RUT PROFESOR 2 / NOMBRE PROFESOR 2             → segundo profesor (~6 casos)
  RUT PROFESOR LABT / PROFESOR LABT              → profesor de laboratorio
  2+1 o 3?            → distribución de bloques de CLAS
  LUNES / MARTES / MIERCOLES / JUEVES / VIERNES  → disponibilidad (versión MAYÚSCULAS)
    Las columnas en minúsculas/título (horario ya asignado) se ignoran.

Diseño:
  - Un mismo CODIGO puede aparecer en múltiples filas (distintos PLAN DE ESTUDIO).
    → Los semestres de cada plan se ACUMULAN (unión de sets).
    → Las secciones se crean solo una vez por (CODIGO, SECCIONES, componente).
  - afecta_disponibilidad: True solo si hay RUT de profesor; False para AYUD siempre.
  - "2+1" se trata como 2h en v1 (simplificación documentada).
"""
from __future__ import annotations

import math
import re
import unicodedata
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd

from .blocks import TODOS_BLOQUES
from .models import Curso, DatosProblema, Profesor, Seccion, TipoProfesor, TipoReunion

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Constantes de archivos
# ---------------------------------------------------------------------------

ARCHIVO_SALAS = "SALAS_ESPECIALES_ING.xlsx"

# ---------------------------------------------------------------------------
# Normalización y búsqueda de columnas por nombre
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """
    Normaliza un nombre de columna para comparación insensible a:
    acentos, mayúsculas/minúsculas y espacios extra.

    Ejemplos:
      "Plan Común" → "plan comun"
      "AYUDANTÍAS PROGRAMAR" → "ayudantias programar"
      "  CODIGO  " → "codigo"
    """
    s = str(s).strip().lower()
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _canon_sala(nombre: str) -> str:
    """
    Forma canónica de un nombre de sala, para conciliar la hoja BBDD (curso → sala)
    con la hoja SALAS ESPECIALES (tipo → capacidad), que usan nombres distintos.

    Ej: 'LABORATORIO DE COMPUTACION' y 'LABT COMPUTACION' → ambos 'LABT COMPUTACION'.
    """
    s = unicodedata.normalize("NFKD", str(nombre).upper()).encode("ascii", "ignore").decode()
    s = s.replace("LABORATORIO", "LABT")
    tokens = [t for t in s.split() if t not in ("DE", "DEL")]
    return " ".join(tokens).strip()


def _mapear_columnas(df: pd.DataFrame) -> dict[str, Optional[str]]:
    """
    Construye {campo_logico: nombre_real_columna_en_df} buscando por nombre normalizado.

    Estrategia de búsqueda por campo:
      1. Coincidencia exacta (normalizada) con alguno de los patrones del campo.
      2. Coincidencia parcial (patrón contenido en el nombre normalizado).
      El primer patrón en la lista tiene mayor prioridad.

    Para columnas de días de disponibilidad se prefiere la versión en MAYÚSCULAS
    (disponibilidad a programar) sobre Título Case o minúsculas (horario ya asignado).

    Si un campo requerido no se encuentra, el valor es None; el llamador decide si
    lanzar un error o continuar con fallback.
    """
    col_norm: dict[str, str] = {col: _norm(str(col)) for col in df.columns}

    def buscar(*patrones: str) -> Optional[str]:
        pats = [_norm(p) for p in patrones]
        # Fase 1: coincidencia exacta
        for pat in pats:
            for col, cn in col_norm.items():
                if cn == pat:
                    return col
        # Fase 2: coincidencia parcial (el patrón está contenido)
        for pat in pats:
            for col, cn in col_norm.items():
                if pat in cn:
                    return col
        return None

    def buscar_mayuscula(*patrones: str) -> Optional[str]:
        """
        Como buscar(), pero prioriza columnas cuyos nombre original sea todo MAYÚSCULAS.
        Esto distingue "LUNES" (disponibilidad a programar) de "Lunes" (ya asignado).
        """
        pats = [_norm(p) for p in patrones]
        # Fase 1: exacta + todo-mayúsculas
        for pat in pats:
            for col, cn in col_norm.items():
                if cn == pat and str(col).strip().isupper():
                    return col
        # Fase 2: exacta (cualquier capitalización)
        for pat in pats:
            for col, cn in col_norm.items():
                if cn == pat:
                    return col
        # Fase 3: parcial + todo-mayúsculas
        for pat in pats:
            for col, cn in col_norm.items():
                if pat in cn and str(col).strip().isupper():
                    return col
        # Fase 4: parcial (cualquier capitalización)
        for pat in pats:
            for col, cn in col_norm.items():
                if pat in cn:
                    return col
        return None

    return {
        # Filtro y metadata
        "MANDANTE":     buscar("curso mandante"),
        "PLAN":         buscar("plan de estudio"),
        "CODIGO":       buscar("codigo"),
        "TITULO":       buscar("titulo"),
        "SECCIONES":    buscar("secciones"),
        # Malla curricular
        "PC":           buscar("plan comun"),
        "ICI":          buscar("ici"),
        "IOC":          buscar("ioc"),
        "ICE":          buscar("ice"),
        "ICC":          buscar("icc"),
        "ICA":          buscar("ica"),
        # Horas a programar (usar estas, NO las regulares)
        "CLAS_PROG":    buscar("clases a programar"),
        "AYUD_PROG":    buscar("ayudantias a programar", "ayudantias programar",
                               "ayudantia programar"),
        "LAB_PROG":     buscar("laboratorios o talleres programar",
                               "labs o talleres programar",
                               "laboratorios programar", "talleres programar"),
        # Profesores
        "RUT_PROF1":    buscar("rut profesor 1"),
        "NOMBRE_PROF1": buscar("nombre profesor 1"),
        "RUT_PROF2":    buscar("rut profesor 2"),
        "NOMBRE_PROF2": buscar("nombre profesor 2"),
        "RUT_LABT":     buscar("rut profesor labt"),
        "NOMBRE_LABT":  buscar("nombre profesor labt", "profesor labt"),
        # Distribución de bloques
        "DISTRIBUCION": buscar("2+1 o 3?", "2+1 o 3"),
        # Disponibilidad (versión MAYÚSCULAS = a programar; minúsculas = ya asignado → ignorar)
        "LUNES_DISP":   buscar_mayuscula("lunes"),
        "MARTES_DISP":  buscar_mayuscula("martes"),
        "MIERC_DISP":   buscar_mayuscula("miercoles"),
        "JUEVES_DISP":  buscar_mayuscula("jueves"),
        "VIERNES_DISP": buscar_mayuscula("viernes"),
    }


def _validar_columnas(cols: dict[str, Optional[str]]) -> None:
    """Imprime el estado de cada campo y lanza ValueError si falta alguno requerido."""
    requeridos = {"MANDANTE", "CODIGO", "SECCIONES"}
    faltantes = []

    print("  Columnas encontradas en el MAESTRO:")
    for campo, col_real in cols.items():
        if col_real:
            print(f"    {campo:15} → '{col_real}'")
        else:
            marker = " ← REQUERIDA, NO ENCONTRADA" if campo in requeridos else " (opcional, sin datos)"
            print(f"    {campo:15} → None{marker}")
            if campo in requeridos:
                faltantes.append(campo)

    if faltantes:
        raise ValueError(
            f"Columnas requeridas no encontradas en la hoja MAESTRO: {faltantes}\n"
            "Verifica los nombres de columna en el archivo Excel."
        )


# ---------------------------------------------------------------------------
# Helpers de acceso a filas
# ---------------------------------------------------------------------------

def _get(row: pd.Series, col_name: Optional[str]):
    """Accede a la fila por nombre de columna. Retorna None si col_name es None."""
    if col_name is None:
        return None
    return row.get(col_name)


def _str(val) -> str:
    """Valor a string limpio; NaN/None → ''."""
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "\xa0") else s


def _parse_semestre(val) -> Optional[str]:
    """
    Convierte un valor de semestre a string canónico preservando sufijos de mención.
    - float/int positivo → str(int)   ej. 5.0 → "5"
    - string que empieza por dígito → tal cual   ej. "9a" → "9a"
    - 0, NaN, None, '*' → None
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
    s = str(val).strip()
    if not s or s in ("\xa0", "nan", "*"):
        return None
    return s if s[0].isdigit() else None


def _parse_horas(val) -> int:
    """Valor de horas (puede ser NaN, str, float) → int ≥ 0."""
    if val is None:
        return 0
    if isinstance(val, str):
        s = val.strip()
        if not s or s in ("\xa0", "nan"):
            return 0
        m = re.match(r"(\d+)", s)
        return int(m.group(1)) if m else 0
    if isinstance(val, float):
        return 0 if math.isnan(val) else int(val)
    if isinstance(val, int):
        return val
    return 0


def _normalizar_rut(val) -> str:
    """
    RUT limpio: sin puntos ni espacios. Retorna '' si está vacío o es NaN.
    Maneja RUTs numéricos (int/float, ej. de la hoja RESPUESTAS) y con dígito K.
    """
    if val is None:
        return ""
    if isinstance(val, float):
        if math.isnan(val):
            return ""
        if val.is_integer():
            return str(int(val))
    if isinstance(val, int):
        return str(val)
    s = _str(val)
    return "" if not s else s.replace(".", "").replace(" ", "")


def _normalizar_seccion_id(val) -> str:
    """
    Normaliza el número de sección:
      float/int → str(int)   (1.0 → "1")
      string    → stripped   ("A" → "A")
    """
    if val is None:
        return "1"
    if isinstance(val, float) and not math.isnan(val):
        return str(int(val))
    if isinstance(val, int):
        return str(val)
    s = _str(val)
    if not s:
        return "1"
    try:
        return str(int(float(s)))
    except (ValueError, TypeError):
        return s


# ---------------------------------------------------------------------------
# Disponibilidad de profesores
# ---------------------------------------------------------------------------

# Mapeo campo lógico → día normalizado (valor de Dia enum)
_DISP_CAMPOS: list[tuple[str, str]] = [
    ("LUNES_DISP",   "L"),
    ("MARTES_DISP",  "M"),
    ("MIERC_DISP",   "X"),
    ("JUEVES_DISP",  "J"),
    ("VIERNES_DISP", "V"),
]


def _parse_subblocks_disp(val) -> set[int]:
    """
    Parsea '8:30-9:20,9:30-10:20,...' → set de minutos de inicio de sub-bloques.
    Solo usa el extremo izquierdo de cada rango (la hora de inicio del sub-bloque).
    """
    s = _str(val)
    if not s:
        return set()
    mins: set[int] = set()
    for parte in s.split(","):
        inicio = parte.strip().split("-")[0].strip()
        if ":" in inicio:
            try:
                h, m = inicio.split(":", 1)
                mins.add(int(h) * 60 + int(m))
            except ValueError:
                pass
    return mins


def _subblocks_a_bloques(disp_por_dia: dict[str, set[int]]) -> set[int]:
    """
    Convierte la disponibilidad por día (dia→{minutos de sub-bloques}) en
    el conjunto de índices de TODOS_BLOQUES que el profesor puede usar.

    Un bloque es disponible si TODOS sus sub-bloques (frozenset[int] en minutos)
    están dentro de los sub-bloques disponibles para ese día.

    Si no hay datos → set vacío (se interpreta como disponibilidad total).
    """
    if not any(disp_por_dia.values()):
        return set()

    disponibles: set[int] = set()
    for i, bloque in enumerate(TODOS_BLOQUES):
        dia = bloque.dia.value   # "L" | "M" | "X" | "J" | "V"
        mins_disp = disp_por_dia.get(dia, set())
        if not mins_disp:
            continue  # sin disponibilidad ese día → bloque no disponible
        if bloque.sub_bloques.issubset(mins_disp):
            disponibles.add(i)
    return disponibles


# ---------------------------------------------------------------------------
# Disponibilidad real: hojas RESPUESTAS y DisponibilidadesFueraForms
# ---------------------------------------------------------------------------

# Día en español (normalizado, sin acentos) → código de Dia
_DIA_NOMBRE: dict[str, str] = {
    "lunes": "L", "martes": "M", "miercoles": "X", "jueves": "J", "viernes": "V",
}


def _leer_respuestas(xl: pd.ExcelFile) -> dict[str, set[int]]:
    """
    Lee la hoja RESPUESTAS (formulario Google de disponibilidad de honorarios).
    Formato: columnas [timestamp, nombre, RUT, día, franja]; una fila por
    (profesor, día, franja de 50 min). La 1a fila ya es dato (sin encabezado).

    Retorna {rut: set[bloque_idx]}.
    """
    try:
        df = xl.parse("RESPUESTAS", header=None)
    except Exception as e:
        print(f"[AVISO] No se pudo leer hoja RESPUESTAS: {e}")
        return {}

    por_rut: dict[str, dict[str, set[int]]] = {}
    for _, row in df.iterrows():
        if len(row) < 5:
            continue
        rut = _normalizar_rut(row.iloc[2])
        dia = _DIA_NOMBRE.get(_norm(_str(row.iloc[3])))
        if not rut or not dia:
            continue
        mins = _parse_subblocks_disp(_str(row.iloc[4]))
        if mins:
            por_rut.setdefault(rut, {}).setdefault(dia, set()).update(mins)

    return {rut: _subblocks_a_bloques(dd) for rut, dd in por_rut.items()}


def _leer_disp_fuera(xl: pd.ExcelFile) -> dict[str, set[int]]:
    """
    Lee la hoja DisponibilidadesFueraForms (honorarios que no llenaron el formulario,
    cargados a mano). Formato irregular en 2 columnas:
        RUT        NOMBRE                       ← inicia un profesor
        DIA        franja1,franja2,...          ← un día de ese profesor
        ...
        (fila vacía separa profesores)

    Retorna {rut: set[bloque_idx]}.
    """
    try:
        df = xl.parse("DisponibilidadesFueraForms", header=None)
    except Exception as e:
        print(f"[AVISO] No se pudo leer hoja DisponibilidadesFueraForms: {e}")
        return {}

    por_rut: dict[str, dict[str, set[int]]] = {}
    actual: Optional[str] = None
    for _, row in df.iterrows():
        c0 = row.iloc[0] if len(row) > 0 else None
        c1 = row.iloc[1] if len(row) > 1 else None
        s0 = _str(c0)
        if not s0:
            continue
        dia = _DIA_NOMBRE.get(_norm(s0))
        if dia:
            if actual:
                mins = _parse_subblocks_disp(_str(c1))
                if mins:
                    por_rut.setdefault(actual, {}).setdefault(dia, set()).update(mins)
        else:
            # No es un día → es el RUT de un profesor nuevo
            actual = _normalizar_rut(c0)

    return {rut: _subblocks_a_bloques(dd) for rut, dd in por_rut.items() if rut}


def _calcular_bloques_clas(horas: int, distribucion: str) -> int:
    """
    Bloques necesarios para CLAS según horas y distribución:
      "3" o "3-juntas" → 1 bloque de 3h (independiente de las horas)
      horas == 3 sin distribución explícita → 1 bloque de 3h
      "2+1" → tratar como 2h en v1
      Resto → ceil(horas/2), mínimo 1
    """
    d = _norm(distribucion or "")
    if d in ("3", "3-juntas"):
        return 1
    if horas <= 0:
        return 1
    if horas == 3:
        return 1
    return max(1, math.ceil(horas / 2))


def _calcular_bloques(horas: int) -> int:
    """Bloques para AYUD y LABT: ceil(horas/2), mínimo 1."""
    if horas <= 0:
        return 1
    if horas == 3:
        return 1
    return max(1, math.ceil(horas / 2))


# ---------------------------------------------------------------------------
# Lectura de salas especiales
# ---------------------------------------------------------------------------

def _leer_salas_especiales(
    inputs_dir: Path,
) -> tuple[dict[str, str], dict[str, int]]:
    """
    Lee SALAS_ESPECIALES_ING.xlsx.

    Retorna:
      sala_por_curso:     {codigo_curso: nombre_sala}
                          Solo para LABORATORIO y CLASE (no PRUEBA ni AYUDANTIA).
                          Si el mismo curso tiene sala para LABT y para CLAS,
                          la de LABT tiene prioridad (más restrictiva).
      capacidad_por_tipo: {tipo_sala: n_salas_fisicas}
    """
    path = inputs_dir / ARCHIVO_SALAS
    if not path.exists():
        print(f"[AVISO] {ARCHIVO_SALAS} no encontrado — sin salas especiales")
        return {}, {}

    sala_por_curso: dict[str, str] = {}

    try:
        df_bbdd = pd.read_excel(path, sheet_name="BBDD")
        # Buscar columnas por nombre normalizado
        col_codigo = next(
            (c for c in df_bbdd.columns if _norm(c) == "codigo"), None
        )
        col_sala = next(
            (c for c in df_bbdd.columns if "sala" in _norm(c) and "especial" in _norm(c)), None
        )
        if col_codigo is None or col_sala is None:
            print(f"[AVISO] Hoja BBDD: no se encontraron columnas CODIGO o SALA ESPECIAL")
        else:
            for _, row in df_bbdd.iterrows():
                codigo   = _str(row.get(col_codigo))
                sala_raw = _str(row.get(col_sala))
                if not codigo or not sala_raw:
                    continue

                marker = " EN HORARIO DE "
                idx = sala_raw.upper().find(marker)
                if idx != -1:
                    nombre   = sala_raw[:idx].strip()
                    contexto = sala_raw[idx + len(marker):].strip().upper()
                else:
                    nombre   = sala_raw.strip()
                    contexto = ""

                if not nombre or contexto in ("PRUEBA", "AYUDANTIA"):
                    continue

                nombre = _canon_sala(nombre)
                # LABT tiene prioridad sobre CLASE
                if codigo not in sala_por_curso or contexto == "LABORATORIO":
                    sala_por_curso[codigo] = nombre

    except Exception as e:
        print(f"[AVISO] Error leyendo hoja BBDD de {ARCHIVO_SALAS}: {e}")

    capacidad_por_tipo: dict[str, int] = {}
    try:
        df_salas = pd.read_excel(path, sheet_name="SALAS ESPECIALES")
        tipo_col = next(
            (c for c in df_salas.columns if "tipo" in _norm(c)), None
        )
        if tipo_col:
            for val in df_salas[tipo_col]:
                tipo = _canon_sala(_str(val))
                if tipo:
                    capacidad_por_tipo[tipo] = capacidad_por_tipo.get(tipo, 0) + 1
    except Exception as e:
        print(f"[AVISO] Error leyendo hoja SALAS ESPECIALES de {ARCHIVO_SALAS}: {e}")

    return sala_por_curso, capacidad_por_tipo


# ---------------------------------------------------------------------------
# Lectura de profesores de jornada (hoja PROFESORES del maestro)
# ---------------------------------------------------------------------------

def _leer_ruts_jornada(xl: pd.ExcelFile) -> set[str]:
    """
    Lee la hoja PROFESORES y retorna el set de RUTs de jornada completa.
    Busca la columna de RUT por nombre normalizado; si no la encuentra, usa la 2a columna.
    """
    try:
        df = xl.parse("PROFESORES", header=0)
        # Intentar encontrar columna de RUT por nombre
        col_rut = next(
            (c for c in df.columns if "rut" in _norm(c)), None
        )
        ruts: set[str] = set()
        for _, row in df.iterrows():
            val = row.get(col_rut) if col_rut else (row.iloc[1] if len(row) > 1 else None)
            rut = _normalizar_rut(val)
            if rut:
                ruts.add(rut)
        return ruts
    except Exception as e:
        print(f"[AVISO] No se pudo leer hoja PROFESORES del maestro: {e}")
        return set()


# ---------------------------------------------------------------------------
# Procesamiento de la hoja MAESTRO
# ---------------------------------------------------------------------------

def _leer_maestro(
    df: pd.DataFrame,
    cols: dict[str, Optional[str]],
    cursos: dict[str, Curso],
    secciones: list[Seccion],
    profesores: dict[str, Profesor],
    ruts_jornada: set[str],
) -> None:
    """
    Itera sobre las filas del MAESTRO donde CURSO MANDANTE == "SI".
    Actualiza cursos, secciones y profesores in-place.

    Para el mismo (CODIGO, SECCIONES, componente) solo se crea una sección;
    si el mismo ID aparece en otra fila (otro plan de estudio), solo se acumulan
    los semestres en el Curso correspondiente.
    """
    sec_ids_creados: set[str] = set()
    advertencias: list[str] = []

    # Mapeo carrera → clave en cols
    carreras_cols = {
        "Plan Común": "PC",
        "ICI": "ICI",
        "IOC": "IOC",
        "ICE": "ICE",
        "ICC": "ICC",
        "ICA": "ICA",
    }

    for _, row in df.iterrows():
        mandante = _str(_get(row, cols["MANDANTE"])).upper()
        if mandante != "SI":
            continue

        # ── Identificación ────────────────────────────────────────────────
        codigo = _str(_get(row, cols["CODIGO"]))
        if not codigo:
            continue

        titulo       = _str(_get(row, cols["TITULO"]))
        seccion_id   = _normalizar_seccion_id(_get(row, cols["SECCIONES"]))
        plan_estudio = _str(_get(row, cols["PLAN"])) or "desconocido"

        # ── Semestres (regla Plan Común vs especialidad) ───────────────────
        pc = _parse_semestre(_get(row, cols["PC"]))
        if pc is not None:
            # Curso de plan común: usar SOLO Plan Común (ver CONTEXT.md §5)
            semestres_fila: dict[str, str] = {"Plan Común": pc}
        else:
            semestres_fila = {}
            for carrera, clave in carreras_cols.items():
                if carrera == "Plan Común":
                    continue
                sem = _parse_semestre(_get(row, cols[clave]))
                if sem is not None:
                    semestres_fila[carrera] = sem

        # ── Horas a programar ─────────────────────────────────────────────
        clas_h       = _parse_horas(_get(row, cols["CLAS_PROG"]))
        ayud_h       = _parse_horas(_get(row, cols["AYUD_PROG"]))
        lab_h        = _parse_horas(_get(row, cols["LAB_PROG"]))
        distribucion = _str(_get(row, cols["DISTRIBUCION"]))

        if clas_h == 0 and ayud_h == 0 and lab_h == 0:
            advertencias.append(
                f"[WARN] {codigo}-{seccion_id} ({plan_estudio}): "
                "horas A PROGRAMAR = 0 en todos los componentes"
            )

        # ── Profesores ────────────────────────────────────────────────────
        rut1        = _normalizar_rut(_get(row, cols["RUT_PROF1"]))
        nombre1     = _str(_get(row, cols["NOMBRE_PROF1"]))
        rut2        = _normalizar_rut(_get(row, cols["RUT_PROF2"]))
        nombre2     = _str(_get(row, cols["NOMBRE_PROF2"]))
        rut_labt    = _normalizar_rut(_get(row, cols["RUT_LABT"]))
        nombre_labt = _str(_get(row, cols["NOMBRE_LABT"]))

        if clas_h > 0 and not rut1:
            advertencias.append(f"[WARN] {codigo}-{seccion_id}: CLAS sin profesor asignado")
        if lab_h > 0 and not rut_labt and not rut1:
            advertencias.append(f"[WARN] {codigo}-{seccion_id}: LABT sin profesor asignado")
        if rut2:
            advertencias.append(
                f"[INFO] {codigo}-{seccion_id}: PROFESOR 2 presente ({nombre2}) — "
                "solo se usa PROF 1 para restricciones en v1"
            )

        # Registrar todos los profesores de esta fila
        for rut, nombre in [(rut1, nombre1), (rut2, nombre2), (rut_labt, nombre_labt)]:
            if rut and rut not in profesores:
                tipo = (
                    TipoProfesor.JORNADA if rut in ruts_jornada
                    else TipoProfesor.HONORARIO
                )
                profesores[rut] = Profesor(rut=rut, nombre=nombre, tipo=tipo)

        # NOTA: la disponibilidad NO se lee de las columnas LUNES-VIERNES del Maestro
        # (no son confiables: no coinciden con el formulario real). Se asigna después,
        # en cargar_datos, desde las hojas RESPUESTAS / DisponibilidadesFueraForms
        # (honorarios) y asumiendo disponibilidad total para los JORNADA.

        # ── Crear / actualizar Curso ──────────────────────────────────────
        if codigo not in cursos:
            cursos[codigo] = Curso(
                codigo=codigo,
                titulo=titulo,
                clases_horas=clas_h,
                ayudantias_horas=ayud_h,
                laboratorios_horas=lab_h,
            )
        else:
            # Si ya existe, conservar la hora más alta observada
            c = cursos[codigo]
            c.clases_horas       = max(c.clases_horas, clas_h)
            c.ayudantias_horas   = max(c.ayudantias_horas, ayud_h)
            c.laboratorios_horas = max(c.laboratorios_horas, lab_h)

        cursos[codigo].planes.add(plan_estudio)
        for carrera, sem in semestres_fila.items():
            cursos[codigo].semestres_por_carrera.setdefault(carrera, set()).add(sem)

        # ── Crear secciones (una sola vez por id único) ───────────────────
        sec_base = f"{codigo}-{seccion_id}"

        if clas_h > 0:
            sec_id = f"{sec_base}-CLAS"
            if sec_id not in sec_ids_creados:
                sec_ids_creados.add(sec_id)
                secciones.append(Seccion(
                    id=sec_id,
                    codigo_curso=codigo,
                    seccion=seccion_id,
                    componente=TipoReunion.CLAS,
                    rut_profesor=rut1,
                    afecta_disponibilidad=bool(rut1),
                    cantidad_bloques_necesarios=_calcular_bloques_clas(clas_h, distribucion),
                ))

        if ayud_h > 0:
            sec_id = f"{sec_base}-AYUD"
            if sec_id not in sec_ids_creados:
                sec_ids_creados.add(sec_id)
                secciones.append(Seccion(
                    id=sec_id,
                    codigo_curso=codigo,
                    seccion=seccion_id,
                    componente=TipoReunion.AYUD,
                    rut_profesor=rut1,           # nominal; la dicta un TA
                    afecta_disponibilidad=False,  # AYUD nunca afecta disponibilidad
                    cantidad_bloques_necesarios=_calcular_bloques(ayud_h),
                ))

        if lab_h > 0:
            sec_id = f"{sec_base}-LABT"
            if sec_id not in sec_ids_creados:
                sec_ids_creados.add(sec_id)
                if rut_labt:
                    # Hay profesor de laboratorio explícito → afecta su disponibilidad
                    prof_lab       = rut_labt
                    afecta_lab     = True
                else:
                    # Sin profesor de lab → lo dicta un TA (igual que AYUD)
                    # Guardamos rut1 solo como referencia/display, no como restricción
                    prof_lab       = rut1
                    afecta_lab     = False
                secciones.append(Seccion(
                    id=sec_id,
                    codigo_curso=codigo,
                    seccion=seccion_id,
                    componente=TipoReunion.LABT,
                    rut_profesor=prof_lab,
                    afecta_disponibilidad=afecta_lab,
                    cantidad_bloques_necesarios=_calcular_bloques(lab_h),
                ))

    for w in advertencias:
        print(w)


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def cargar_datos(inputs_dir: str | Path) -> DatosProblema:
    """
    Lee Maestro_XXXXXX.xlsx + SALAS_ESPECIALES_ING.xlsx y construye DatosProblema.
    Imprime un resumen al final.
    """
    inputs_dir = Path(inputs_dir)

    # Encontrar el archivo Maestro (acepta cualquier capitalización)
    candidatos = sorted(inputs_dir.glob("[Mm]aestro*.xlsx"))
    if not candidatos:
        raise FileNotFoundError(
            f"No se encontró ningún archivo Maestro*.xlsx en {inputs_dir}\n"
            "Coloca el maestro en inputs/ con nombre que empiece por 'Maestro'."
        )
    maestro_path = candidatos[0]
    if len(candidatos) > 1:
        print(f"[AVISO] Múltiples archivos maestro. Usando: {maestro_path.name}")
    print(f"Maestro: {maestro_path.name}")

    # Salas especiales
    sala_por_curso, capacidad_por_tipo = _leer_salas_especiales(inputs_dir)

    # Abrir el maestro
    xl = pd.ExcelFile(maestro_path)

    # Profesores de jornada
    ruts_jornada = _leer_ruts_jornada(xl)
    print(f"Profesores de jornada en hoja PROFESORES: {len(ruts_jornada)}")

    # Hoja MAESTRO
    df_maestro = xl.parse("MAESTRO", header=0)
    print(f"Hoja MAESTRO: {len(df_maestro)} filas totales, {len(df_maestro.columns)} columnas")

    # Mapeo de columnas por nombre
    cols = _mapear_columnas(df_maestro)
    _validar_columnas(cols)

    n_mandantes = (
        df_maestro[cols["MANDANTE"]].astype(str).str.strip().str.upper() == "SI"
    ).sum()
    print(f"Filas con CURSO MANDANTE = 'SI': {n_mandantes}")

    cursos: dict[str, Curso]        = {}
    secciones: list[Seccion]        = []
    profesores: dict[str, Profesor] = {}

    _leer_maestro(df_maestro, cols, cursos, secciones, profesores, ruts_jornada)

    # ── Disponibilidad de profesores (fuente confiable) ───────────────────────
    #   JORNADA  → disponibilidad TOTAL (set vacío = sin restricción RD2)
    #   HONORARIO → desde el formulario (RESPUESTAS) o carga manual (FueraForms)
    # Las columnas LUNES-VIERNES del Maestro NO se usan (no son confiables).
    disp_respuestas = _leer_respuestas(xl)
    disp_fuera      = _leer_disp_fuera(xl)
    print(f"Disponibilidad: RESPUESTAS={len(disp_respuestas)} profes, "
          f"FueraForms={len(disp_fuera)} profes")

    honorarios_sin_disp: list[str] = []
    for rut, prof in profesores.items():
        if prof.tipo == TipoProfesor.JORNADA:
            prof.disponibilidad = set()        # total
            continue
        bloques = disp_respuestas.get(rut) or disp_fuera.get(rut)
        if bloques:
            prof.disponibilidad = set(bloques)
        else:
            prof.disponibilidad = set()        # sin datos → asumir total (no sobre-restringir)
            honorarios_sin_disp.append(rut)
    if honorarios_sin_disp:
        print(f"[AVISO] {len(honorarios_sin_disp)} honorario(s) sin disponibilidad "
              f"en RESPUESTAS/FueraForms → se asume disponibilidad total")

    # Aplicar salas especiales
    for codigo, sala in sala_por_curso.items():
        if codigo in cursos:
            cursos[codigo].sala_especial = sala

    datos = DatosProblema(
        cursos=cursos,
        secciones=secciones,
        profesores=profesores,
        # sala_name = NOMBRE en BBDD (parte antes de " EN HORARIO DE ")
        # se asume igual al TIPO en hoja SALAS ESPECIALES → cuenta de salas físicas
        capacidad_por_sala=capacidad_por_tipo,
    )
    _imprimir_resumen(datos, capacidad_por_tipo)
    return datos


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

def _imprimir_resumen(
    datos: DatosProblema,
    capacidad_por_tipo: dict[str, int] | None = None,
) -> None:
    cursos     = datos.cursos
    secciones  = datos.secciones
    profesores = datos.profesores

    print("=" * 60)
    print("RESUMEN DEL PROBLEMA")
    print("=" * 60)

    print(f"\nCursos únicos: {len(cursos)}")
    conteo_por_plan: dict[str, int] = {}
    for c in cursos.values():
        for plan in c.planes:
            conteo_por_plan[plan] = conteo_por_plan.get(plan, 0) + 1
    for plan, n in sorted(conteo_por_plan.items()):
        print(f"  {plan}: {n} cursos")

    por_comp: dict[str, int] = {}
    for s in secciones:
        por_comp[s.componente.value] = por_comp.get(s.componente.value, 0) + 1
    print(f"\nSecciones totales: {len(secciones)}")
    for comp, n in sorted(por_comp.items()):
        print(f"  {comp}: {n}")

    por_tipo: dict[str, int] = {}
    for p in profesores.values():
        por_tipo[p.tipo.value] = por_tipo.get(p.tipo.value, 0) + 1
    print(f"\nProfesores únicos: {len(profesores)}")
    for tipo, n in sorted(por_tipo.items()):
        print(f"  {tipo}: {n}")

    # Disponibilidad (RD2): cuántos profesores tienen datos y cobertura promedio
    con_disp = [p for p in profesores.values() if p.disponibilidad]
    print(f"\nProfesores con disponibilidad declarada (RD2): {len(con_disp)}/{len(profesores)}")
    if con_disp:
        from .blocks import N_BLOQUES
        prom = sum(len(p.disponibilidad) for p in con_disp) / len(con_disp)
        print(f"  Bloques disponibles en promedio: {prom:.1f} de {N_BLOQUES}")
        # Profesores con muy poca disponibilidad (posible causa de INFEASIBLE)
        criticos = [p for p in con_disp if len(p.disponibilidad) < 4]
        if criticos:
            print(f"  [AVISO] {len(criticos)} profesor(es) con <4 bloques disponibles:")
            for p in criticos[:8]:
                print(f"    {p.nombre or p.rut}: {len(p.disponibilidad)} bloque(s)")

    multi = [s for s in secciones if s.cantidad_bloques_necesarios > 1]
    print(f"\nSecciones con múltiples bloques: {len(multi)}")
    if multi:
        resumen_multi: dict[int, int] = {}
        for s in multi:
            resumen_multi[s.cantidad_bloques_necesarios] = (
                resumen_multi.get(s.cantidad_bloques_necesarios, 0) + 1
            )
        for n_b, cnt in sorted(resumen_multi.items()):
            print(f"  {n_b} bloques: {cnt} secciones")

    multi_sem = [
        (c.codigo, carrera, sems)
        for c in cursos.values()
        for carrera, sems in c.semestres_por_carrera.items()
        if len(sems) > 1
    ]
    if multi_sem:
        print(f"\nCursos con semestre distinto según plan: {len(multi_sem)}")
        for codigo, carrera, sems in sorted(multi_sem)[:10]:
            print(f"  {codigo} ({carrera}): {sorted(sems)}")
        if len(multi_sem) > 10:
            print(f"  ... y {len(multi_sem) - 10} más")

    if capacidad_por_tipo:
        print(f"\nSalas especiales — tipo → salas físicas:")
        for tipo, n in sorted(capacidad_por_tipo.items()):
            print(f"  {tipo}: {n}")

    sin_sem = [c.codigo for c in cursos.values() if not c.semestres_por_carrera]
    if sin_sem:
        print(f"\nCursos sin semestre en malla: {len(sin_sem)}")

    ayud_mal = [s for s in secciones
                if s.componente == TipoReunion.AYUD and s.afecta_disponibilidad]
    if ayud_mal:
        print(f"\n[ERROR] {len(ayud_mal)} sección(es) AYUD con afecta_disponibilidad=True")

    print("=" * 60)
