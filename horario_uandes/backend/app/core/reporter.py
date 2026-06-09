"""
reporter.py — Genera el reporte detallado de violaciones de restricciones.

La función principal generar_reporte_detallado() analiza una solución (asignaciones)
y retorna un dict estructurado con:
  resumen             → conteos y penalización por tipo
  violaciones_duras   → RD1 (topes), RD3 (profesor), RD4 (sala)
  violaciones_blandas → RB1–RB5 (calidad del horario)

Cada violación es un dict con:
  tipo        → "RD1", "RB2", etc.
  descripcion → label corto legible
  mensaje     → descripción completa en español (la que ve Francisca)
  secciones   → lista de {id, codigo, titulo, seccion, tipo}
  bloques     → lista de strings "Martes 10:30-12:20"
  contexto    → carrera/semestre, nombre del profesor, o sala
  penalizacion → float para blandas, None para duras
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .blocks import MATRIZ_SOLAPAMIENTO, TODOS_BLOQUES
from .models import DatosProblema, TipoProfesor, TipoReunion

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIA_LABEL = {
    "L": "Lunes", "M": "Martes", "X": "Miércoles",
    "J": "Jueves", "V": "Viernes",
}
_HORAS_EXTREMAS = {"8:30", "17:30"}
_CURSO_PROG = "ING1103"

PESOS_RB: dict[str, float] = {
    "RB1": 100, "RB2": 80, "RB3": 50, "RB4": 50, "RB5": 60,
}


def _bloque_str(idx: int) -> str:
    b = TODOS_BLOQUES[idx]
    return f"{_DIA_LABEL.get(b.dia.value, b.dia.value)} {b.hora_inicio}-{b.hora_fin}"


def _bloque_dia(idx: int) -> str:
    return TODOS_BLOQUES[idx].dia.value


def _hora_a_min(hora: str) -> int:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def _sec_info(s, datos: DatosProblema) -> dict:
    curso = datos.cursos.get(s.codigo_curso)
    return {
        "id":      s.id,
        "codigo":  s.codigo_curso,
        "titulo":  curso.titulo if curso else "",
        "seccion": s.seccion,
        "tipo":    s.componente.value,
    }


def _sec_label(info: dict) -> str:
    return f"{info['codigo']} {info['titulo']} {info['seccion']} {info['tipo']}"


def _viol(
    tipo: str,
    descripcion: str,
    mensaje: str,
    secciones: list[dict],
    bloques: list[str],
    contexto: str,
    penalizacion: Optional[float] = None,
) -> dict:
    return {
        "tipo":        tipo,
        "descripcion": descripcion,
        "mensaje":     mensaje,
        "secciones":   secciones,
        "bloques":     bloques,
        "contexto":    contexto,
        "penalizacion": penalizacion,
    }


# ---------------------------------------------------------------------------
# Restricciones duras
# ---------------------------------------------------------------------------

def _rd1(datos: DatosProblema, asig: dict[str, list[int]]) -> list[dict]:
    """Topes de malla: cursos distintos del mismo semestre/carrera con bloques solapados."""
    sec_by_id = {s.id: s for s in datos.secciones}
    violaciones: list[dict] = []

    carreras: set[str] = set()
    for curso in datos.cursos.values():
        carreras.update(curso.semestres_por_carrera.keys())

    for carrera in sorted(carreras):
        grupos: dict[str, list[str]] = defaultdict(list)
        for sec_id in asig:
            s = sec_by_id.get(sec_id)
            if not s:
                continue
            curso = datos.cursos.get(s.codigo_curso)
            if not curso:
                continue
            for sem in curso.semestres_por_carrera.get(carrera, set()):
                grupos[sem].append(sec_id)

        for sem, ids in grupos.items():
            vistos: set[frozenset] = set()
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    id1, id2 = ids[i], ids[j]
                    s1, s2 = sec_by_id.get(id1), sec_by_id.get(id2)
                    if not s1 or not s2:
                        continue
                    if s1.codigo_curso == s2.codigo_curso:
                        continue
                    par = frozenset((id1, id2))
                    if par in vistos:
                        continue
                    comunes = [
                        b1 for b1 in asig[id1]
                        for b2 in asig[id2]
                        if MATRIZ_SOLAPAMIENTO[b1][b2]
                    ]
                    if not comunes:
                        continue
                    vistos.add(par)
                    info1, info2 = _sec_info(s1, datos), _sec_info(s2, datos)
                    bloques_str = sorted({_bloque_str(b) for b in comunes})
                    msg = (
                        f"{info1['codigo']} {info1['titulo']} ({info1['tipo']}) "
                        f"y {info2['codigo']} {info2['titulo']} ({info2['tipo']}) "
                        f"comparten {', '.join(bloques_str)} "
                        f"— ambos son {carrera} semestre {sem}"
                    )
                    violaciones.append(_viol(
                        "RD1", "Tope de malla", msg,
                        [info1, info2], bloques_str,
                        f"{carrera} · semestre {sem}",
                    ))
    return violaciones


def _rd3(datos: DatosProblema, asig: dict[str, list[int]]) -> list[dict]:
    """Conflicto de profesor: mismo prof en dos secciones de cursos distintos a la vez."""
    sec_by_id = {s.id: s for s in datos.secciones}
    por_prof: dict[str, list[str]] = defaultdict(list)
    for sec_id in asig:
        s = sec_by_id.get(sec_id)
        if s and s.afecta_disponibilidad and s.rut_profesor:
            por_prof[s.rut_profesor].append(sec_id)

    violaciones: list[dict] = []
    for rut, ids in por_prof.items():
        prof = datos.profesores.get(rut)
        nombre = prof.nombre if prof else rut
        vistos: set[frozenset] = set()
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id1, id2 = ids[i], ids[j]
                s1, s2 = sec_by_id.get(id1), sec_by_id.get(id2)
                if not s1 or not s2 or s1.codigo_curso == s2.codigo_curso:
                    continue
                par = frozenset((id1, id2))
                if par in vistos:
                    continue
                comunes = [
                    b1 for b1 in asig[id1]
                    for b2 in asig[id2]
                    if MATRIZ_SOLAPAMIENTO[b1][b2]
                ]
                if not comunes:
                    continue
                vistos.add(par)
                info1, info2 = _sec_info(s1, datos), _sec_info(s2, datos)
                bloques_str = sorted({_bloque_str(b) for b in comunes})
                msg = (
                    f"Prof. {nombre} asignado simultáneamente a "
                    f"{_sec_label(info1)} y {_sec_label(info2)} "
                    f"en {', '.join(bloques_str)}"
                )
                violaciones.append(_viol(
                    "RD3", "Conflicto de profesor", msg,
                    [info1, info2], bloques_str,
                    f"Prof. {nombre}",
                ))
    return violaciones


def _rd4(datos: DatosProblema, asig: dict[str, list[int]]) -> list[dict]:
    """
    Sala especial: se supera la cantidad de salas físicas disponibles en algún bloque.

    Para capacidad = 1: cualquier solapamiento entre dos secciones (mismo o distinto curso).
    Para capacidad > 1: más de (capacidad) secciones en el mismo bloque.
    """
    sec_by_id = {s.id: s for s in datos.secciones}
    por_sala: dict[str, list[str]] = defaultdict(list)
    for sec_id in asig:
        s = sec_by_id.get(sec_id)
        if not s or s.componente == TipoReunion.AYUD:
            continue
        curso = datos.cursos.get(s.codigo_curso)
        if curso and curso.sala_especial:
            por_sala[curso.sala_especial].append(sec_id)

    cap = datos.capacidad_por_sala
    violaciones: list[dict] = []

    for sala, ids in por_sala.items():
        capacidad = cap.get(sala, None)  # None = sin datos de capacidad física

        if capacidad is None:
            # Sin datos: solo reportar conflictos entre cursos distintos
            vistos: set[frozenset] = set()
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    id1, id2 = ids[i], ids[j]
                    s1 = sec_by_id.get(id1)
                    s2 = sec_by_id.get(id2)
                    if not s1 or not s2 or s1.codigo_curso == s2.codigo_curso:
                        continue
                    par = frozenset((id1, id2))
                    if par in vistos:
                        continue
                    comunes = [b1 for b1 in asig[id1] for b2 in asig[id2]
                               if MATRIZ_SOLAPAMIENTO[b1][b2]]
                    if not comunes:
                        continue
                    vistos.add(par)
                    info1, info2 = _sec_info(s1, datos), _sec_info(s2, datos)
                    bloques_str = sorted({_bloque_str(b) for b in comunes})
                    msg = (f"Sala {sala}: {_sec_label(info1)} y {_sec_label(info2)} "
                           f"coinciden en {', '.join(bloques_str)}")
                    violaciones.append(_viol("RD4", "Conflicto de sala especial", msg,
                                            [info1, info2], bloques_str,
                                            f"Sala: {sala} — capacidad: desconocida"))
        elif capacidad == 1:
            # 1 sala física: cualquier solapamiento entre dos secciones es violación
            vistos: set[frozenset] = set()
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    id1, id2 = ids[i], ids[j]
                    par = frozenset((id1, id2))
                    if par in vistos:
                        continue
                    s1 = sec_by_id.get(id1)
                    s2 = sec_by_id.get(id2)
                    if not s1 or not s2:
                        continue
                    comunes = [
                        b1 for b1 in asig[id1]
                        for b2 in asig[id2]
                        if MATRIZ_SOLAPAMIENTO[b1][b2]
                    ]
                    if not comunes:
                        continue
                    vistos.add(par)
                    info1, info2 = _sec_info(s1, datos), _sec_info(s2, datos)
                    bloques_str = sorted({_bloque_str(b) for b in comunes})
                    msg = (
                        f"Sala {sala} (1 sala física): "
                        f"{_sec_label(info1)} y {_sec_label(info2)} "
                        f"coinciden en {', '.join(bloques_str)}"
                    )
                    violaciones.append(_viol(
                        "RD4", "Conflicto de sala especial", msg,
                        [info1, info2], bloques_str, f"Sala: {sala} — capacidad: 1",
                    ))
        else:
            # Violación cuando más de (capacidad) secciones comparten el mismo bloque
            from collections import Counter as _Counter
            bloque_secs: dict[int, list[str]] = defaultdict(list)
            for sec_id in ids:
                for b in asig[sec_id]:
                    bloque_secs[b].append(sec_id)

            for bloque, secs_en_bloque in bloque_secs.items():
                if len(secs_en_bloque) <= capacidad:
                    continue
                infos = [_sec_info(sec_by_id[sid], datos) for sid in secs_en_bloque
                         if sec_by_id.get(sid)]
                bloque_label = _bloque_str(bloque)
                msg = (
                    f"Sala {sala} ({capacidad} salas físicas): "
                    f"{len(secs_en_bloque)} secciones en {bloque_label} "
                    f"({', '.join(i['codigo'] + '-' + i['seccion'] for i in infos)})"
                )
                violaciones.append(_viol(
                    "RD4", "Sala especial sobre capacidad", msg,
                    infos, [bloque_label],
                    f"Sala: {sala} — capacidad: {capacidad}, asignadas: {len(secs_en_bloque)}",
                ))

    return violaciones


# ---------------------------------------------------------------------------
# Restricciones blandas
# ---------------------------------------------------------------------------

def _rb1(datos: DatosProblema, asig: dict[str, list[int]]) -> list[dict]:
    """Labs de Programación (ING1103-LABT) no consecutivos o en días distintos."""
    sec_by_id = {s.id: s for s in datos.secciones}
    violaciones: list[dict] = []
    for sec_id, bloques in asig.items():
        s = sec_by_id.get(sec_id)
        if not s or s.codigo_curso != _CURSO_PROG or s.componente != TipoReunion.LABT:
            continue
        if len(bloques) < 2:
            continue
        info = _sec_info(s, datos)
        for k1 in range(len(bloques)):
            for k2 in range(k1 + 1, len(bloques)):
                b1, b2 = bloques[k1], bloques[k2]
                tb1, tb2 = TODOS_BLOQUES[b1], TODOS_BLOQUES[b2]
                if tb1.dia == tb2.dia:
                    fin1  = _hora_a_min(tb1.hora_fin)
                    ini2  = _hora_a_min(tb2.hora_inicio)
                    fin2  = _hora_a_min(tb2.hora_fin)
                    ini1  = _hora_a_min(tb1.hora_inicio)
                    if fin1 == ini2 or fin2 == ini1:
                        continue  # adyacentes → OK
                    msg = (
                        f"ING1103 LABT secc. {s.seccion}: bloques del mismo día "
                        f"no son consecutivos ({_bloque_str(b1)} / {_bloque_str(b2)})"
                    )
                else:
                    msg = (
                        f"ING1103 LABT secc. {s.seccion}: bloques en días distintos "
                        f"({_bloque_str(b1)} / {_bloque_str(b2)})"
                    )
                violaciones.append(_viol(
                    "RB1", "Lab Programación no consecutivo", msg,
                    [info], [_bloque_str(b1), _bloque_str(b2)],
                    "Labs de Programación deben estar en el mismo día y ser consecutivos",
                    penalizacion=PESOS_RB["RB1"],
                ))
    return violaciones


def _rb2(datos: DatosProblema, asig: dict[str, list[int]]) -> list[dict]:
    """Profesor de jornada asignado en horario extremo (8:30 o 17:30)."""
    sec_by_id = {s.id: s for s in datos.secciones}
    violaciones: list[dict] = []
    # Una penalización por sección que tenga al menos un bloque extremo
    for sec_id, bloques in asig.items():
        s = sec_by_id.get(sec_id)
        if not s:
            continue
        prof = datos.profesores.get(s.rut_profesor)
        if not prof or prof.tipo != TipoProfesor.JORNADA:
            continue
        extremos = [b for b in bloques if TODOS_BLOQUES[b].hora_inicio in _HORAS_EXTREMAS]
        if not extremos:
            continue
        info = _sec_info(s, datos)
        bloques_str = [_bloque_str(b) for b in extremos]
        msg = (
            f"Prof. {prof.nombre} (JORNADA) en horario extremo "
            f"{', '.join(bloques_str)} "
            f"para {info['codigo']}-{info['seccion']} {info['tipo']}"
        )
        violaciones.append(_viol(
            "RB2", "Prof. jornada en horario extremo", msg,
            [info], bloques_str,
            f"Prof. {prof.nombre} (JORNADA)",
            penalizacion=PESOS_RB["RB2"],
        ))
    return violaciones


def _rb3(datos: DatosProblema, asig: dict[str, list[int]]) -> list[dict]:
    """Componentes distintos del mismo curso en el mismo día."""
    sec_by_id = {s.id: s for s in datos.secciones}

    # Un representante por (codigo, componente): el primero en asig
    rep: dict[tuple[str, TipoReunion], str] = {}
    for sec_id in asig:
        s = sec_by_id.get(sec_id)
        if s:
            key = (s.codigo_curso, s.componente)
            if key not in rep:
                rep[key] = sec_id

    # Agrupar representantes por codigo
    por_codigo: dict[str, dict[TipoReunion, str]] = defaultdict(dict)
    for (codigo, comp), sec_id in rep.items():
        por_codigo[codigo][comp] = sec_id

    violaciones: list[dict] = []
    for codigo, comp_map in por_codigo.items():
        comps = list(comp_map.keys())
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                c1, c2 = comps[i], comps[j]
                id1, id2 = comp_map[c1], comp_map[c2]
                dias1 = {_bloque_dia(b) for b in asig[id1]}
                dias2 = {_bloque_dia(b) for b in asig[id2]}
                comunes = dias1 & dias2
                if not comunes:
                    continue
                s1, s2 = sec_by_id[id1], sec_by_id[id2]
                info1, info2 = _sec_info(s1, datos), _sec_info(s2, datos)
                curso = datos.cursos.get(codigo)
                titulo = curso.titulo if curso else ""
                dias_label = sorted([_DIA_LABEL.get(d, d) for d in comunes])
                msg = (
                    f"{codigo} {titulo}: {c1.value} y {c2.value} "
                    f"en el mismo día ({', '.join(dias_label)})"
                )
                violaciones.append(_viol(
                    "RB3", "Componentes del curso en el mismo día", msg,
                    [info1, info2], dias_label,
                    f"{codigo} — {c1.value} y {c2.value}",
                    penalizacion=len(comunes) * PESOS_RB["RB3"],
                ))
    return violaciones


def _rb4(datos: DatosProblema, asig: dict[str, list[int]]) -> list[dict]:
    """Sección con más de un bloque del mismo componente en el mismo día."""
    sec_by_id = {s.id: s for s in datos.secciones}
    violaciones: list[dict] = []
    for sec_id, bloques in asig.items():
        if len(bloques) < 2:
            continue
        s = sec_by_id.get(sec_id)
        if not s:
            continue
        dia_cnt: dict[str, int] = {}
        for b in bloques:
            d = _bloque_dia(b)
            dia_cnt[d] = dia_cnt.get(d, 0) + 1
        for dia, cnt in dia_cnt.items():
            if cnt <= 1:
                continue
            info = _sec_info(s, datos)
            bloques_en_dia = [_bloque_str(b) for b in bloques if _bloque_dia(b) == dia]
            msg = (
                f"{info['codigo']}-{info['seccion']} {info['tipo']}: "
                f"{cnt} bloques el {_DIA_LABEL.get(dia, dia)} "
                f"({', '.join(bloques_en_dia)})"
            )
            violaciones.append(_viol(
                "RB4", "Múltiples bloques del componente en un día", msg,
                [info], bloques_en_dia,
                f"{_DIA_LABEL.get(dia, dia)}: {cnt} bloques",
                penalizacion=(cnt - 1) * PESOS_RB["RB4"],
            ))
    return violaciones


def _rb5(
    datos: DatosProblema,
    asig: dict[str, list[int]],
    historico: dict[str, dict[str, set[int]]],
) -> list[dict]:
    """Bloques asignados que difieren del histórico de semestres anteriores."""
    sec_by_id = {s.id: s for s in datos.secciones}
    violaciones: list[dict] = []
    for sec_id, bloques in asig.items():
        s = sec_by_id.get(sec_id)
        if not s:
            continue
        hist = historico.get(s.codigo_curso, {}).get(s.componente.value, set())
        if not hist:
            continue
        no_hist = [b for b in bloques if b not in hist]
        if not no_hist:
            continue
        info = _sec_info(s, datos)
        bloques_str = [_bloque_str(b) for b in no_hist]
        hist_str = [_bloque_str(b) for b in sorted(hist)[:3]]
        msg = (
            f"{info['codigo']}-{info['seccion']} {info['tipo']}: "
            f"{len(no_hist)} bloque(s) distintos al histórico "
            f"({', '.join(bloques_str)}) — "
            f"histórico preferido: {', '.join(hist_str)}"
        )
        violaciones.append(_viol(
            "RB5", "Cambio respecto al histórico", msg,
            [info], bloques_str,
            f"Histórico: {', '.join(hist_str)}",
            penalizacion=len(no_hist) * PESOS_RB["RB5"],
        ))
    return violaciones


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def generar_reporte_detallado(
    datos: DatosProblema,
    asignaciones: dict[str, list[int]],
    historico: dict[str, dict[str, set[int]]] | None = None,
) -> dict:
    """
    Genera el reporte completo de violaciones de restricciones.

    Args:
        datos:        DatosProblema (cursos, secciones, profesores)
        asignaciones: solución GA final (sec_id → [bloque_idx, ...])
        historico:    Datos históricos para RB5 (opcional)

    Returns:
        {
          resumen: {total_duras, total_blandas, por_tipo_dura, por_tipo_blanda,
                   penalizacion_total, penalizacion_por_rb},
          violaciones_duras:   [ViolacionDict, ...],
          violaciones_blandas: [ViolacionDict, ...],
        }
    """
    duras: list[dict] = []
    duras.extend(_rd1(datos, asignaciones))
    duras.extend(_rd3(datos, asignaciones))
    duras.extend(_rd4(datos, asignaciones))

    blandas: list[dict] = []
    blandas.extend(_rb1(datos, asignaciones))
    blandas.extend(_rb2(datos, asignaciones))
    blandas.extend(_rb3(datos, asignaciones))
    blandas.extend(_rb4(datos, asignaciones))
    if historico:
        blandas.extend(_rb5(datos, asignaciones, historico))

    por_tipo_dura: dict[str, int] = {}
    for v in duras:
        por_tipo_dura[v["tipo"]] = por_tipo_dura.get(v["tipo"], 0) + 1

    por_tipo_blanda: dict[str, int] = {}
    pen_por_rb: dict[str, float] = {}
    for v in blandas:
        por_tipo_blanda[v["tipo"]] = por_tipo_blanda.get(v["tipo"], 0) + 1
        pen_por_rb[v["tipo"]] = pen_por_rb.get(v["tipo"], 0.0) + (v["penalizacion"] or 0)

    return {
        "resumen": {
            "total_duras":         len(duras),
            "total_blandas":       len(blandas),
            "por_tipo_dura":       por_tipo_dura,
            "por_tipo_blanda":     por_tipo_blanda,
            "penalizacion_total":  sum(v["penalizacion"] or 0 for v in blandas),
            "penalizacion_por_rb": pen_por_rb,
        },
        "violaciones_duras":   duras,
        "violaciones_blandas": blandas,
    }
