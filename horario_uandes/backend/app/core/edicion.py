"""
edicion.py — Edición manual del horario con revalidación (Fase 5).

El usuario mueve una sección a otro bloque. El sistema NO relaja restricciones: valida
el movimiento contra TODAS las restricciones duras y reporta los conflictos, para que el
usuario decida con información completa.

Funciones:
  conflictos_de_seccion(datos, asig, sec_id)  → conflictos DUROS que involucran a sec_id.
  bloques_validos(datos, asig, sec_id, indice) → para cada bloque candidato del hueco
       `indice` de la sección, si dejaría el horario válido (verde) o en conflicto (rojo).
  aplicar_movimiento(datos, asig, sec_id, indice, destino) → nueva asignación + conflictos.

El chequeo es FOCALIZADO en la sección movida: como el resto del horario no cambia, basta
revisar los conflictos que la involucran (más barato y suficiente para la interacción).
"""
from __future__ import annotations

from .blocks import (
    BLOQUES_1H,
    BLOQUES_2H_SET,
    BLOQUES_3H_SET,
    MATRIZ_SOLAPAMIENTO,
    TODOS_BLOQUES,
)
from .models import DatosProblema, TipoReunion
from .solver_cpsat import disponibilidad_seccion

_DIA_LABEL = {"L": "Lunes", "M": "Martes", "X": "Miércoles", "J": "Jueves", "V": "Viernes"}
_MIN_12_30 = 12 * 60 + 30


def _hora_min(hora: str) -> int:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def _bloque_str(idx: int) -> str:
    b = TODOS_BLOQUES[idx]
    return f"{_DIA_LABEL.get(b.dia.value, b.dia.value)} {b.hora_inicio}-{b.hora_fin}"


def _prof_nombre(datos: DatosProblema, rut: str) -> str:
    p = datos.profesores.get(rut)
    return (p.nombre if p and p.nombre else rut) or "(sin profesor)"


def _solapan(bloques_a, bloques_b) -> bool:
    return any(MATRIZ_SOLAPAMIENTO[a][b] for a in bloques_a for b in bloques_b)


def _comparten_malla(datos: DatosProblema, s1, s2) -> bool:
    """True si dos secciones de cursos distintos comparten alguna (carrera, semestre)."""
    c1 = datos.cursos.get(s1.codigo_curso)
    c2 = datos.cursos.get(s2.codigo_curso)
    if not c1 or not c2:
        return False
    for carrera, sems in c1.semestres_por_carrera.items():
        if sems & c2.semestres_por_carrera.get(carrera, set()):
            return True
    return False


def _tipo_esperado(s, indice: int) -> str | None:
    """Tipo de bloque que debe ocupar el hueco `indice` de la sección (o None si libre)."""
    tipos = s.tipos_bloques_necesarios
    if tipos:
        return tipos[indice] if indice < len(tipos) else None
    return s.duracion_bloque


# ---------------------------------------------------------------------------
# Conflictos que involucran a una sección
# ---------------------------------------------------------------------------

def conflictos_de_seccion(
    datos: DatosProblema,
    asig: dict[str, list[int]],
    sec_id: str,
) -> list[dict]:
    """Lista de conflictos DUROS (dict con tipo y motivo) que involucran a sec_id."""
    sec_by_id = {s.id: s for s in datos.secciones}
    s = sec_by_id.get(sec_id)
    if not s or sec_id not in asig:
        return []
    bloques = asig[sec_id]
    conf: list[dict] = []

    def _add(tipo, motivo):
        conf.append({"tipo": tipo, "motivo": motivo})

    # intra-sección: los bloques de la sección se solapan entre sí
    for i in range(len(bloques)):
        for j in range(i + 1, len(bloques)):
            if MATRIZ_SOLAPAMIENTO[bloques[i]][bloques[j]]:
                _add("intra", f"Los bloques {_bloque_str(bloques[i])} y "
                              f"{_bloque_str(bloques[j])} de la misma sección se solapan.")

    # RD2 — disponibilidad del profesor
    prof = datos.profesores.get(s.rut_profesor) if s.rut_profesor else None
    if s.afecta_disponibilidad and prof and prof.disponibilidad:
        fuera = [b for b in bloques if b not in prof.disponibilidad]
        if fuera:
            _add("RD2", f"El profesor {_prof_nombre(datos, s.rut_profesor)} no está "
                        f"disponible en {', '.join(_bloque_str(b) for b in fuera)}.")

    # RD6 — la duración del bloque debe calzar con lo que necesita la sección
    tipos_ok = set(s.tipos_bloques_necesarios) if s.tipos_bloques_necesarios else {s.duracion_bloque}
    malos = [b for b in bloques if TODOS_BLOQUES[b].tipo not in tipos_ok]
    if malos:
        _add("RD6", f"Duración incorrecta: {', '.join(_bloque_str(b) for b in malos)} "
                    f"no calza con la duración requerida ({'/'.join(sorted(tipos_ok))}).")

    # RD7 — ayudantías solo desde 12:30
    if s.componente == TipoReunion.AYUD:
        temprano = [b for b in bloques if _hora_min(TODOS_BLOQUES[b].hora_inicio) < _MIN_12_30]
        if temprano:
            _add("RD7", f"Ayudantía antes de las 12:30 en "
                        f"{', '.join(_bloque_str(b) for b in temprano)}.")

    # Conflictos por pares con el resto del horario
    salas_conteo: dict[int, list[str]] = {}  # para RD4 con capacidad > 1
    sala_s = None
    if s.componente != TipoReunion.AYUD:
        curso_s = datos.cursos.get(s.codigo_curso)
        sala_s = curso_s.sala_especial if curso_s else None

    for oid, obloques in asig.items():
        if oid == sec_id:
            continue
        os_ = sec_by_id.get(oid)
        if not os_ or not _solapan(bloques, obloques):
            continue

        mismo_curso_secc = (
            os_.codigo_curso == s.codigo_curso and str(os_.seccion) == str(s.seccion)
        )
        # NRC — componentes distintos de la MISMA sección no se solapan
        if mismo_curso_secc and os_.componente != s.componente:
            _add("NRC", f"Choca con {oid} (otro componente de la misma sección).")
            continue

        # RD1 — topes de malla (cursos distintos, misma carrera+semestre)
        if os_.codigo_curso != s.codigo_curso and _comparten_malla(datos, s, os_):
            _add("RD1", f"Tope de malla con {oid} (mismo semestre en la malla).")

        # RD3 — mismo profesor en dos secciones a la vez
        if (s.afecta_disponibilidad and os_.afecta_disponibilidad
                and s.rut_profesor and s.rut_profesor == os_.rut_profesor
                and os_.codigo_curso != s.codigo_curso):
            _add("RD3", f"El profesor {_prof_nombre(datos, s.rut_profesor)} ya está en "
                        f"{oid} a esa hora.")

        # RD4 — misma sala especial
        if sala_s and os_.componente != TipoReunion.AYUD:
            curso_o = datos.cursos.get(os_.codigo_curso)
            if curso_o and curso_o.sala_especial == sala_s:
                for b in bloques:
                    if _solapan([b], obloques):
                        salas_conteo.setdefault(b, []).append(oid)

    # RD4 — evaluar capacidad de la sala por bloque
    if sala_s and salas_conteo:
        cap = datos.capacidad_por_sala.get(sala_s)
        if cap is None:
            cap = 1
        for b, otros in salas_conteo.items():
            if 1 + len(otros) > cap:
                _add("RD4", f"Sala {sala_s} sobre capacidad ({cap}) en {_bloque_str(b)}: "
                            f"compite con {', '.join(otros)}.")

    return conf


# ---------------------------------------------------------------------------
# Bloques candidatos para mover una sección
# ---------------------------------------------------------------------------

def bloques_validos(
    datos: DatosProblema,
    asig: dict[str, list[int]],
    sec_id: str,
    indice: int,
) -> list[dict]:
    """
    Para el hueco `indice` de la sección, evalúa cada bloque candidato de su dominio:
      estado="valido"    → mover ahí no genera ningún conflicto duro.
      estado="conflicto" → genera conflicto(s); se detallan en `motivos`.
    El bloque actualmente ocupado se marca con actual=True.
    """
    sec_by_id = {s.id: s for s in datos.secciones}
    s = sec_by_id.get(sec_id)
    if not s or sec_id not in asig or indice >= len(asig[sec_id]):
        return []

    actual = asig[sec_id][indice]
    tipo_esperado = _tipo_esperado(s, indice)
    filtro = {"1h": BLOQUES_1H, "2h": BLOQUES_2H_SET, "3h": BLOQUES_3H_SET}.get(tipo_esperado)

    # Dominio base: disponibilidad de la sección, restringida al tipo del hueco.
    dominio = sorted(disponibilidad_seccion(datos, s))
    if filtro is not None:
        dominio = [b for b in dominio if b in filtro]
    elif not s.tipos_bloques_necesarios:
        dominio = [b for b in dominio if b not in BLOQUES_1H]

    resultado: list[dict] = []
    otros = asig[sec_id][:indice] + asig[sec_id][indice + 1:]
    for cand in dominio:
        # Simular el movimiento y evaluar conflictos de la sección.
        asig_tmp = dict(asig)
        asig_tmp[sec_id] = sorted(otros + [cand])
        motivos = [c["motivo"] for c in conflictos_de_seccion(datos, asig_tmp, sec_id)]
        b = TODOS_BLOQUES[cand]
        resultado.append({
            "bloque": cand,
            "dia": b.dia.value,
            "hora_inicio": b.hora_inicio,
            "hora_fin": b.hora_fin,
            "es_helper": not b.es_estandar,
            "actual": cand == actual,
            "estado": "valido" if not motivos else "conflicto",
            "motivos": motivos,
        })
    return resultado


# ---------------------------------------------------------------------------
# Aplicar un movimiento
# ---------------------------------------------------------------------------

def aplicar_movimiento(
    datos: DatosProblema,
    asig: dict[str, list[int]],
    sec_id: str,
    indice: int,
    destino: int,
) -> tuple[dict[str, list[int]], list[dict]]:
    """
    Devuelve (nueva_asignacion, conflictos_resultantes) tras mover el hueco `indice` de
    sec_id al bloque `destino`. No impide movimientos con conflicto: los reporta para que
    el usuario decida (el sistema informa, no bloquea silenciosamente).
    """
    if sec_id not in asig or indice >= len(asig[sec_id]):
        raise ValueError(f"Sección o índice inválido: {sec_id}[{indice}]")

    nueva = {k: list(v) for k, v in asig.items()}
    otros = nueva[sec_id][:indice] + nueva[sec_id][indice + 1:]
    nueva[sec_id] = sorted(otros + [destino])
    conflictos = conflictos_de_seccion(datos, nueva, sec_id)
    return nueva, conflictos
