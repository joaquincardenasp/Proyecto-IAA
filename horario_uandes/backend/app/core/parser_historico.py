"""
parser_historico.py — Lee archivos de horarios de semestres anteriores.

Construye un mapa {codigo_curso: {componente: set[bloque_idx]}} con los bloques
que cada curso usó históricamente. Usado por RB5 en el GA.

Formato de los archivos (inputs/historico/*.xlsx):
  - Header en fila 14 (índice 13)
  - Columnas clave: MATERIA, CURSO, SECC., TIPO DE REUNIÓN (o TIPO DE REUNION),
    LUNES/Lunes, MARTES/Martes, MIERCOLES/Miercoles, JUEVES/Jueves, VIERNES/Viernes
  - Cada fila = un día de clase; una sesión puede ocupar múltiples filas si ocurre varios días

Normalización:
  - "LAB/TALLER" → "LABT"
  - Días en mayúscula o Title Case → L/M/X/J/V
  - Franjas como "13:30-15:20" que no coinciden con ningún bloque → se omiten silenciosamente
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from .blocks import TODOS_BLOQUES

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Constantes de normalización
# ---------------------------------------------------------------------------

_DIAS_COL = {
    "lunes":     "L",
    "martes":    "M",
    "miercoles": "X",
    "jueves":    "J",
    "viernes":   "V",
}

_TIPOS_NORM = {
    "CLAS":       "CLAS",
    "OLIN":       "CLAS",   # clases online → CLAS
    "AYUD":       "AYUD",
    "AYON":       "AYUD",   # ayudantía online → AYUD
    "LABT":       "LABT",
    "LAB/TALLER": "LABT",
}

# Índices de bloques agrupados por (dia, hora_inicio) para búsqueda rápida
_IDX_POR_DIA_HORA: dict[tuple[str, str], list[int]] = {}
for _i, _b in enumerate(TODOS_BLOQUES):
    _key = (_b.dia.value, _b.hora_inicio)
    _IDX_POR_DIA_HORA.setdefault(_key, []).append(_i)


# ---------------------------------------------------------------------------
# Helper: franja horaria → índices de bloques
# ---------------------------------------------------------------------------

def _franja_a_bloques(dia_norm: str, franja: str) -> list[int]:
    """
    Dado un día normalizado (L/M/X/J/V) y una franja "HH:MM-HH:MM",
    retorna los índices de bloques de TODOS_BLOQUES cuyo hora_inicio
    coincide exactamente con el inicio de la franja.

    La coincidencia exacta evita mapeos erróneos cuando la franja
    corresponde a un bloque que ya no existe en el catálogo actual.
    Franjas con hora_inicio desconocida se omiten silenciosamente.
    """
    try:
        partes = franja.strip().split("-")
        if len(partes) != 2:
            return []
        inicio_str = partes[0].strip()
    except Exception:
        return []

    return [
        i for i, b in enumerate(TODOS_BLOQUES)
        if b.dia.value == dia_norm and b.hora_inicio == inicio_str
    ]


# ---------------------------------------------------------------------------
# Parser de un archivo
# ---------------------------------------------------------------------------

def _leer_un_archivo(path: Path) -> dict[str, dict[str, set[int]]]:
    """
    Lee un Excel de horario histórico y retorna:
      {codigo_curso: {componente: set[bloque_idx]}}
    """
    df = pd.read_excel(path, header=13)

    # Normalizar nombres de columnas: strip + lowercase para comparación
    col_map: dict[str, str] = {c: c for c in df.columns}

    # Encontrar columna de tipo de reunión (puede tener o no tilde)
    tipo_col = None
    for c in df.columns:
        if "tipo" in c.lower() and "reuni" in c.lower():
            tipo_col = c
            break
    if tipo_col is None:
        return {}

    # Encontrar columnas de días (mayúsculas o Title Case)
    dias_cols: dict[str, str] = {}  # col_name → dia_norm
    for c in df.columns:
        key = c.strip().lower()
        if key in _DIAS_COL:
            dias_cols[c] = _DIAS_COL[key]

    resultado: dict[str, dict[str, set[int]]] = {}

    for _, row in df.iterrows():
        tipo_raw = str(row.get(tipo_col, "")).strip().upper()
        tipo = _TIPOS_NORM.get(tipo_raw)
        if tipo is None:
            continue  # PRBA, EXAM, etc.

        materia = str(row.get("MATERIA", "")).strip()
        curso_raw = row.get("CURSO")
        if not materia or str(materia) == "nan":
            continue
        try:
            codigo = materia + str(int(float(str(curso_raw))))
        except (ValueError, TypeError):
            continue

        # Recopilar bloques de cada día
        bloques: set[int] = set()
        for col_name, dia_norm in dias_cols.items():
            val = row.get(col_name)
            if val is None or str(val).strip() in ("", "nan"):
                continue
            bloques.update(_franja_a_bloques(dia_norm, str(val).strip()))

        if not bloques:
            continue

        resultado.setdefault(codigo, {})
        resultado[codigo].setdefault(tipo, set()).update(bloques)

    return resultado


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def leer_historico(inputs_dir: str | Path) -> dict[str, dict[str, set[int]]]:
    """
    Lee todos los archivos Excel de inputs/historico/ y combina los bloques
    históricos por (codigo_curso, componente).

    Retorna {codigo_curso: {componente: set[bloque_idx]}}.
    Si no hay archivos o la carpeta no existe, retorna dict vacío.
    """
    historico_dir = Path(inputs_dir) / "historico"
    if not historico_dir.exists():
        return {}

    combinado: dict[str, dict[str, set[int]]] = {}
    archivos = list(historico_dir.glob("*.xlsx"))

    for path in archivos:
        datos = _leer_un_archivo(path)
        for codigo, comps in datos.items():
            combinado.setdefault(codigo, {})
            for comp, bloques in comps.items():
                combinado[codigo].setdefault(comp, set()).update(bloques)

    return combinado


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------

def imprimir_resumen_historico(historico: dict[str, dict[str, set[int]]]) -> None:
    print("=" * 60)
    print("HISTÓRICO")
    print("=" * 60)
    print(f"Cursos con datos históricos: {len(historico)}")
    total_bloques = sum(len(bl) for comps in historico.values() for bl in comps.values())
    print(f"Total de preferencias (curso, comp, bloque): {total_bloques}")
    print()

    # Muestra algunos ejemplos representativos
    for codigo in sorted(historico)[:8]:
        for comp, bloques in sorted(historico[codigo].items()):
            nombres = [
                f"{TODOS_BLOQUES[b].dia.value} {TODOS_BLOQUES[b].hora_inicio}"
                for b in sorted(bloques)
            ]
            print(f"  {codigo} [{comp}]: {nombres}")
