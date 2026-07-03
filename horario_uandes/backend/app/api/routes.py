"""
routes.py — Endpoints FastAPI del generador de horarios.

Flujo:
  1. POST /api/upload      → sube archivos Excel a inputs/
  2. POST /api/solve       → lanza CP-SAT + GA en background
  3. GET  /api/status      → consulta progreso
  4. GET  /api/results     → devuelve JSON con secciones, métricas y reporte
  5. GET  /api/report      → devuelve solo el reporte de violaciones
  6. GET  /api/export      → descarga el .xlsx generado
  7. GET  /api/health      → health check
"""
from __future__ import annotations

import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import Response

from ..core.blocks import TODOS_BLOQUES
from ..core.exporter import _CARRERAS, _sem_sort_key, exportar_horario
from ..core.models import DatosProblema
from ..core.parser import cargar_datos, _estructura_bloques
from ..core.diagnostico import diagnosticar
from ..core.edicion import aplicar_movimiento, bloques_validos, validar_asignacion
from ..core.reporter import generar_reporte_detallado
from ..core.solver_cpsat import resolver_por_partes
from ..core.solver_ga import (
    PESOS,
    calcular_fitness,
    construir_contexto,
    ejecutar_ga,
    encode,
)
from ..schemas.solve import (
    BloqueAsignado,
    BloquesValidosRequest,
    BloquesValidosResponse,
    BloqueValido,
    ConflictoActivo,
    ConflictoItem,
    DecisionRequest,
    DecisionSeccion,
    DiagnosticoResult,
    DiagnosticoUnidadItem,
    MetricasResult,
    MoverRequest,
    MoverResponse,
    ReporteDetallado,
    ResumenReporte,
    SeccionAsignada,
    SeccionRef,
    SolveRequest,
    SolveResult,
    StatusResponse,
    SugerenciaItem,
    ViolacionItem,
)

router = APIRouter()

INPUTS_DIR  = Path(__file__).parent.parent.parent / "inputs"
OUTPUTS_DIR = Path(__file__).parent.parent.parent / "outputs"

# ---------------------------------------------------------------------------
# Estado compartido del solver (una sola ejecución a la vez)
# ---------------------------------------------------------------------------

_state: dict = {
    "status":                  "idle",   # idle | running | ready | error
    "progress":                "",
    "error":                   "",
    "estado":                  "",       # FACTIBLE | PARCIAL | INFEASIBLE (resultado del solve)
    "asignaciones":            None,     # dict[str, list[int]]
    "metricas":                None,     # dict
    "reporte":                 None,     # dict (salida de generar_reporte_detallado)
    "diagnostico":             None,     # Diagnostico (dataclass) o None
    "excel_bytes":             None,     # bytes
    "datos":                   None,     # DatosProblema
    # Decisiones del usuario sobre estructura de bloques (persisten entre regeneraciones):
    "overrides":               {"distribucion": {}, "duracion": {}},
    "decisiones_cand":         [],       # candidatos a decisión (del parse fresco)
}
_lock     = asyncio.Lock()
_executor = ThreadPoolExecutor(max_workers=1)


# ---------------------------------------------------------------------------
# Lógica sincrónica del solver (corre en el executor)
# ---------------------------------------------------------------------------

def _set_progress(msg: str) -> None:
    _state["progress"] = msg


# ---------------------------------------------------------------------------
# Decisiones de estructura de bloques (distribución 3h / componente 1h)
# ---------------------------------------------------------------------------

def _candidatos_decision(datos: DatosProblema) -> list[dict]:
    """
    Secciones que requieren/admiten una decisión estructural, tomadas del parse FRESCO
    (antes de aplicar overrides): CLAS de 3h sin distribución (requerida) y componentes de
    1h (ajuste opcional a 2h).
    """
    cand: list[dict] = []
    for s in datos.secciones:
        curso = datos.cursos.get(s.codigo_curso)
        info = dict(
            sec_id=s.id, codigo=s.codigo_curso,
            titulo=curso.titulo if curso else "", seccion=s.seccion,
            profesor=(datos.profesores.get(s.rut_profesor).nombre
                      if datos.profesores.get(s.rut_profesor) else s.rut_profesor) or "",
        )
        if s.distribucion_indefinida:
            cand.append({**info, "tipo": "distribucion"})
        elif s.duracion_bloque == "1h":
            cand.append({**info, "tipo": "duracion_1h"})
    return cand


def _build_decisiones(candidatos: list[dict], overrides: dict) -> list[DecisionSeccion]:
    """Arma la lista de DecisionSeccion combinando los candidatos con los overrides vigentes."""
    ov_dist = overrides.get("distribucion", {})
    ov_dur = overrides.get("duracion", {})
    out: list[DecisionSeccion] = []
    for c in candidatos:
        if c["tipo"] == "distribucion":
            out.append(DecisionSeccion(
                **{k: c[k] for k in ("sec_id", "codigo", "titulo", "seccion", "profesor")},
                tipo="distribucion", opciones=["3-juntas", "2+1"],
                actual=ov_dist.get(c["sec_id"], ""), requerida=True,
                mensaje=("Clase de 3h sin distribución definida. Elige cómo dictarla: "
                         "'3-juntas' (un bloque de 3h) o '2+1' (un bloque de 2h + uno de 1h). "
                         "Hasta entonces no se programa."),
            ))
        else:  # duracion_1h
            out.append(DecisionSeccion(
                **{k: c[k] for k in ("sec_id", "codigo", "titulo", "seccion", "profesor")},
                tipo="duracion_1h", opciones=["1h", "2h"],
                actual=ov_dur.get(c["sec_id"], "1h"), requerida=False,
                mensaje=("Componente de 1 hora (inusual). Por defecto usa un bloque de 1h; "
                         "puedes cambiarlo a un bloque de 2h si corresponde."),
            ))
    return out


def _aplicar_overrides(datos: DatosProblema, overrides: dict) -> None:
    """Aplica las decisiones del usuario sobre las secciones (in-place) antes de resolver."""
    sec_by_id = {s.id: s for s in datos.secciones}
    for sid, opcion in overrides.get("distribucion", {}).items():
        s = sec_by_id.get(sid)
        if not s or opcion not in ("3-juntas", "2+1"):
            continue
        est = _estructura_bloques("CLAS", 3, opcion)
        s.cantidad_bloques_necesarios = est["cantidad"]
        s.tipos_bloques_necesarios = est["tipos"]
        s.duracion_bloque = est["duracion"]
        s.distribucion_indefinida = est["indefinida"]
    for sid, dur in overrides.get("duracion", {}).items():
        s = sec_by_id.get(sid)
        if not s or dur not in ("1h", "2h"):
            continue
        s.duracion_bloque = dur
        s.tipos_bloques_necesarios = []


def _solve_sync(req: SolveRequest) -> None:
    try:
        _set_progress("Cargando datos…")
        datos = cargar_datos(INPUTS_DIR)
        # Candidatos a decisión (del parse fresco, antes de aplicar overrides) y luego
        # aplicar las decisiones ya tomadas por el usuario.
        _state["decisiones_cand"] = _candidatos_decision(datos)
        _aplicar_overrides(datos, _state["overrides"])
        _state["datos"] = datos

        _set_progress("Generando el mejor horario posible…")
        # Sin relajación automática. resolver_por_partes entrega el horario COMPLETO si
        # existe (FACTIBLE), o el subconjunto factible + unidades bloqueadas (PARCIAL), o
        # nada colocable (INFEASIBLE). En ningún caso viola restricciones duras.
        resultado = resolver_por_partes(
            datos,
            carreras=req.carreras,
            tiempo_limite_s=req.tiempo_limite_cpsat,
        )
        asignaciones_cpsat = resultado.asignaciones

        # Diagnóstico accionable de las unidades que no se pudieron colocar.
        diagnostico = None
        if resultado.bloqueadas:
            _set_progress("Diagnosticando conflictos…")
            diagnostico = diagnosticar(datos, resultado, req.carreras)

        metricas_api = None
        reporte_raw = None
        excel_bytes = None
        asignaciones: dict = {}

        # Solo optimizamos/exportamos si hay algo colocado (FACTIBLE o PARCIAL).
        if asignaciones_cpsat:
            _set_progress("Optimizando restricciones blandas (GA)…")
            resultado_ga = ejecutar_ga(
                datos,
                asignaciones_cpsat,
                n_generaciones=req.n_generaciones,
                pop_size=req.pop_size,
                seed=req.seed,
            )
            asignaciones = resultado_ga.asignaciones

            _set_progress("Calculando métricas y reporte…")
            ctx           = construir_contexto(datos, asignaciones_cpsat)
            fitness_cpsat = calcular_fitness(encode(asignaciones_cpsat, ctx), ctx)[0]
            fitness_ga    = resultado_ga.fitness_final
            mejora_pct    = (
                (fitness_cpsat - fitness_ga) / fitness_cpsat * 100
                if fitness_cpsat > 0 else 0.0
            )
            n_bloques_totales = sum(len(b) for b in asignaciones.values())

            reporte_raw = generar_reporte_detallado(datos, asignaciones)

            pen_rb = reporte_raw["resumen"]["penalizacion_por_rb"]
            metricas_dict = {
                "fitness_cpsat": fitness_cpsat,
                "fitness_ga":    fitness_ga,
                "mejora_pct":    mejora_pct,
                "rb_detalle": {
                    f"RB{k+1} (peso {v})": pen_rb.get(f"RB{k+1}", 0)
                    for k, v in enumerate(PESOS.values())
                },
            }
            metricas_api = {
                "fitness_cpsat":          fitness_cpsat,
                "fitness_ga":             fitness_ga,
                "mejora_pct":             mejora_pct,
                "n_secciones":            len(asignaciones),
                "n_bloques_totales":      n_bloques_totales,
                # Factibilidad del horario COLOCADO (siempre respeta las duras). El estado
                # global FACTIBLE/PARCIAL/INFEASIBLE va en SolveResult.estado, no aquí.
                "estado_cpsat":           "FEASIBLE",
            }

            _set_progress("Generando Excel…")
            OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
            try:
                excel_bytes = exportar_horario(
                    datos, asignaciones,
                    output_path=OUTPUTS_DIR / "horario_generado.xlsx",
                    metricas=metricas_dict,
                    reporte=reporte_raw,
                )
            except PermissionError:
                excel_bytes = exportar_horario(
                    datos, asignaciones,
                    metricas=metricas_dict,
                    reporte=reporte_raw,
                )

        _state["estado"]       = resultado.estado
        _state["asignaciones"] = asignaciones
        _state["metricas"]     = metricas_api
        _state["reporte"]      = reporte_raw
        _state["diagnostico"]  = diagnostico
        _state["excel_bytes"]  = excel_bytes
        _state["status"]       = "ready"
        _state["progress"]     = "Completado"
        _state["error"]        = ""

    except Exception as exc:
        _state["status"]   = "error"
        _state["progress"] = ""
        _state["error"]    = str(exc)
        traceback.print_exc()


async def _solve_background(req: SolveRequest) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _solve_sync, req)


# ---------------------------------------------------------------------------
# Helpers de serialización
# ---------------------------------------------------------------------------

def _build_secciones(datos: DatosProblema, asignaciones: dict) -> list[SeccionAsignada]:
    sec_by_id = {s.id: s for s in datos.secciones}
    result: list[SeccionAsignada] = []
    for sec_id, bloques_idx in asignaciones.items():
        s = sec_by_id.get(sec_id)
        if not s:
            continue
        curso = datos.cursos.get(s.codigo_curso)
        prof  = datos.profesores.get(s.rut_profesor)

        bloques_list = [
            BloqueAsignado(
                dia=TODOS_BLOQUES[i].dia.value,
                hora_inicio=TODOS_BLOQUES[i].hora_inicio,
                hora_fin=TODOS_BLOQUES[i].hora_fin,
                tipo_bloque=TODOS_BLOQUES[i].tipo,
            )
            for i in bloques_idx
        ]
        cars_parts, sems_parts = [], []
        if curso:
            for car in _CARRERAS:
                sems = curso.semestres_por_carrera.get(car)
                if sems:
                    cars_parts.append(car)
                    sems_parts.append("/".join(sorted(sems, key=_sem_sort_key)))

        result.append(SeccionAsignada(
            id=sec_id,
            codigo=s.codigo_curso,
            titulo=curso.titulo if curso else "",
            seccion=s.seccion,
            tipo=s.componente.value,
            profesor=prof.nombre if prof else s.rut_profesor,
            bloques=bloques_list,
            carreras=" · ".join(cars_parts),
            semestres=" · ".join(sems_parts),
        ))
    return result


def _build_reporte(reporte_raw: dict) -> ReporteDetallado:
    def _viol(v: dict) -> ViolacionItem:
        return ViolacionItem(
            tipo=v["tipo"],
            descripcion=v["descripcion"],
            mensaje=v["mensaje"],
            secciones=[SeccionRef(**s) for s in v["secciones"]],
            bloques=v["bloques"],
            contexto=v["contexto"],
            penalizacion=v.get("penalizacion"),
        )

    res = reporte_raw["resumen"]
    return ReporteDetallado(
        resumen=ResumenReporte(
            total_duras=res["total_duras"],
            total_blandas=res["total_blandas"],
            por_tipo_dura=res["por_tipo_dura"],
            por_tipo_blanda=res["por_tipo_blanda"],
            penalizacion_total=res["penalizacion_total"],
            penalizacion_por_rb=res["penalizacion_por_rb"],
        ),
        violaciones_duras=[_viol(v) for v in reporte_raw["violaciones_duras"]],
        violaciones_blandas=[_viol(v) for v in reporte_raw["violaciones_blandas"]],
    )


def _build_diagnostico(diag) -> DiagnosticoResult:
    """Convierte el dataclass Diagnostico (core) al schema Pydantic de la API."""
    return DiagnosticoResult(
        unidades=[
            DiagnosticoUnidadItem(
                carrera=u.carrera,
                semestre=u.semestre,
                causa_principal=u.causa_principal,
                sugerencias=[
                    SugerenciaItem(
                        causa=s.causa,
                        severidad=s.severidad,
                        mensaje=s.mensaje,
                        acciones=s.acciones,
                        secciones=s.secciones,
                        profesores=s.profesores,
                        bloques=s.bloques,
                    )
                    for s in u.sugerencias
                ],
            )
            for u in diag.unidades
        ]
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """Sube uno o más archivos Excel al directorio inputs/."""
    try:
        INPUTS_DIR.mkdir(parents=True, exist_ok=True)
        saved = []
        for f in files:
            nombre = Path(f.filename or "").name
            if not nombre:
                continue
            contenido = await f.read()
            try:
                (INPUTS_DIR / nombre).write_bytes(contenido)
            except PermissionError:
                # En Windows, un archivo abierto en Excel (o de solo lectura) queda
                # bloqueado para escritura. Mensaje claro en vez de un 500 genérico.
                raise HTTPException(
                    status_code=409,
                    detail=(f"No se pudo guardar '{nombre}': el archivo está abierto en "
                            f"Excel u otro programa, o es de solo lectura. Ciérralo e "
                            f"intenta de nuevo."),
                )
            saved.append(nombre)
        if not saved:
            raise HTTPException(status_code=400, detail="No se recibió ningún archivo válido")
        return {"uploaded": saved}
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error al guardar archivos: {exc}")


@router.post("/solve", status_code=202)
async def solve(req: SolveRequest, background_tasks: BackgroundTasks):
    """Lanza el solver en background. Devuelve 409 si ya está corriendo."""
    async with _lock:
        if _state["status"] == "running":
            raise HTTPException(status_code=409, detail="Solver ya está en ejecución")
        _state["status"]                 = "running"
        _state["progress"]               = "Iniciando…"
        _state["error"]                  = ""
        _state["estado"]                 = ""
        _state["asignaciones"]           = None
        _state["metricas"]               = None
        _state["reporte"]                = None
        _state["diagnostico"]            = None
        _state["excel_bytes"]            = None

    background_tasks.add_task(_solve_background, req)
    return {"detail": "Solver iniciado"}


@router.get("/status", response_model=StatusResponse)
def get_status():
    return StatusResponse(
        status=_state["status"],
        progress=_state["progress"],
        error=_state["error"],
    )


@router.get("/results", response_model=SolveResult)
def get_results():
    """
    Devuelve el resultado del solve. Según `estado`:
      FACTIBLE   — secciones + métricas + reporte (horario completo).
      PARCIAL    — secciones + métricas + reporte del subconjunto colocado, más diagnóstico.
      INFEASIBLE — sin horario; solo diagnóstico.
    404 si aún no está listo.
    """
    if _state["status"] != "ready":
        raise HTTPException(
            status_code=404,
            detail=f"Resultados no disponibles (status={_state['status']})",
        )
    secciones = (
        _build_secciones(_state["datos"], _state["asignaciones"])
        if _state["asignaciones"] else []
    )
    metricas_raw = _state["metricas"]
    metricas = None
    if metricas_raw:
        metricas = MetricasResult(
            fitness_cpsat=metricas_raw["fitness_cpsat"],
            fitness_ga=metricas_raw["fitness_ga"],
            mejora_pct=metricas_raw["mejora_pct"],
            n_secciones=metricas_raw["n_secciones"],
            n_bloques_totales=metricas_raw["n_bloques_totales"],
            estado_cpsat=metricas_raw["estado_cpsat"],
        )
    reporte = _build_reporte(_state["reporte"]) if _state["reporte"] else None
    diagnostico = _build_diagnostico(_state["diagnostico"]) if _state["diagnostico"] else None
    decisiones = _build_decisiones(_state["decisiones_cand"], _state["overrides"])
    return SolveResult(
        estado=_state["estado"] or "FACTIBLE",
        metricas=metricas,
        secciones=secciones,
        reporte=reporte,
        diagnostico=diagnostico,
        decisiones=decisiones,
    )


@router.get("/diagnostico", response_model=DiagnosticoResult)
def get_diagnostico():
    """Devuelve el diagnóstico de conflictos del último solve. 404 si no hay."""
    if _state["status"] != "ready" or _state["diagnostico"] is None:
        raise HTTPException(
            status_code=404,
            detail="No hay diagnóstico disponible (el horario es factible o aún no se resolvió).",
        )
    return _build_diagnostico(_state["diagnostico"])


@router.get("/report", response_model=ReporteDetallado)
def get_report():
    """Devuelve solo el reporte de violaciones. 404 si no está listo."""
    if _state["status"] != "ready" or _state["reporte"] is None:
        raise HTTPException(
            status_code=404,
            detail=f"Reporte no disponible (status={_state['status']})",
        )
    return _build_reporte(_state["reporte"])


@router.post("/editar/bloques-validos", response_model=BloquesValidosResponse)
def editar_bloques_validos(req: BloquesValidosRequest):
    """
    Para una sección del horario actual, devuelve los bloques candidatos del hueco `indice`
    marcados como 'valido' (verde) o 'conflicto' (rojo, con motivos). No modifica el estado.
    """
    if _state["status"] != "ready" or not _state["asignaciones"]:
        raise HTTPException(status_code=404, detail="No hay un horario cargado para editar.")
    if req.sec_id not in _state["asignaciones"]:
        raise HTTPException(status_code=404, detail=f"Sección {req.sec_id} no está en el horario.")

    candidatos = bloques_validos(
        _state["datos"], _state["asignaciones"], req.sec_id, req.indice
    )
    return BloquesValidosResponse(
        sec_id=req.sec_id,
        indice=req.indice,
        candidatos=[BloqueValido(**c) for c in candidatos],
    )


@router.post("/editar/mover", response_model=MoverResponse)
def editar_mover(req: MoverRequest):
    """
    Mueve el hueco `indice` de una sección al bloque `destino` y revalida. Aplica el cambio
    (el sistema informa los conflictos resultantes, no bloquea) y regenera reporte y Excel.
    """
    if _state["status"] != "ready" or not _state["asignaciones"]:
        raise HTTPException(status_code=404, detail="No hay un horario cargado para editar.")
    if req.sec_id not in _state["asignaciones"]:
        raise HTTPException(status_code=404, detail=f"Sección {req.sec_id} no está en el horario.")

    datos = _state["datos"]
    try:
        nueva, conflictos = aplicar_movimiento(
            datos, _state["asignaciones"], req.sec_id, req.indice, req.destino
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Persistir el cambio y regenerar reporte + Excel para mantener todo consistente.
    _state["asignaciones"] = nueva
    _state["reporte"] = generar_reporte_detallado(datos, nueva)
    try:
        _state["excel_bytes"] = exportar_horario(
            datos, nueva,
            output_path=OUTPUTS_DIR / "horario_generado.xlsx",
            reporte=_state["reporte"],
        )
    except PermissionError:
        _state["excel_bytes"] = exportar_horario(datos, nueva, reporte=_state["reporte"])

    seccion = _build_secciones(datos, {req.sec_id: nueva[req.sec_id]})[0]
    return MoverResponse(
        sec_id=req.sec_id,
        seccion=seccion,
        conflictos=[ConflictoItem(**c) for c in conflictos],
    )


@router.get("/conflictos", response_model=list[ConflictoActivo])
def get_conflictos():
    """
    Lista todos los conflictos duros vigentes en el horario actual (deduplicados). Base del
    panel de 'conflictos activos': se refresca tras cada edición para que el usuario no pierda
    de vista ningún tope que haya dejado. Lista vacía si no hay horario o no hay conflictos.
    """
    if _state["status"] != "ready" or not _state["asignaciones"]:
        return []
    conflictos = validar_asignacion(_state["datos"], _state["asignaciones"])
    return [ConflictoActivo(**c) for c in conflictos]


@router.post("/decisiones/distribucion", response_model=list[DecisionSeccion])
def set_distribucion(req: DecisionRequest):
    """
    Registra la distribución elegida para una CLAS de 3h sin definir ("3-juntas" | "2+1").
    No re-resuelve: el cambio se aplica al regenerar el horario (POST /solve). Devuelve la
    lista de decisiones actualizada.
    """
    if req.opcion not in ("3-juntas", "2+1"):
        raise HTTPException(status_code=400, detail="Opción inválida (usa '3-juntas' o '2+1').")
    _state["overrides"]["distribucion"][req.sec_id] = req.opcion
    return _build_decisiones(_state["decisiones_cand"], _state["overrides"])


@router.post("/decisiones/duracion", response_model=list[DecisionSeccion])
def set_duracion(req: DecisionRequest):
    """
    Registra la duración elegida para un componente de 1h ("1h" | "2h"). No re-resuelve;
    se aplica al regenerar (POST /solve). Devuelve la lista de decisiones actualizada.
    """
    if req.opcion not in ("1h", "2h"):
        raise HTTPException(status_code=400, detail="Opción inválida (usa '1h' o '2h').")
    _state["overrides"]["duracion"][req.sec_id] = req.opcion
    return _build_decisiones(_state["decisiones_cand"], _state["overrides"])


@router.get("/export")
def export_excel():
    """Descarga el archivo .xlsx generado. 404 si no está listo."""
    if _state["status"] != "ready" or _state["excel_bytes"] is None:
        raise HTTPException(
            status_code=404,
            detail=f"Excel no disponible (status={_state['status']})",
        )
    return Response(
        content=_state["excel_bytes"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="horario_generado.xlsx"'},
    )