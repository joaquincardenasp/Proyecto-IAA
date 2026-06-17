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
from ..core.parser import cargar_datos
from ..core.parser_historico import leer_historico
from ..core.reporter import generar_reporte_detallado
from ..core.solver_cpsat import resolver_con_fallback          # ← usa el fallback
from ..core.solver_ga import (
    PESOS,
    calcular_fitness,
    construir_contexto,
    ejecutar_ga,
    encode,
)
from ..schemas.solve import (
    BloqueAsignado,
    MetricasResult,
    ReporteDetallado,
    ResumenReporte,
    SeccionAsignada,
    SeccionRef,
    SolveRequest,
    SolveResult,
    StatusResponse,
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
    "asignaciones":            None,     # dict[str, list[int]]
    "metricas":                None,     # dict
    "reporte":                 None,     # dict (salida de generar_reporte_detallado)
    "excel_bytes":             None,     # bytes
    "datos":                   None,     # DatosProblema
    "advertencia_relajacion":  "",       # mensaje de fallback para el frontend
}
_lock     = asyncio.Lock()
_executor = ThreadPoolExecutor(max_workers=1)


# ---------------------------------------------------------------------------
# Lógica sincrónica del solver (corre en el executor)
# ---------------------------------------------------------------------------

def _set_progress(msg: str) -> None:
    _state["progress"] = msg


def _solve_sync(req: SolveRequest) -> None:
    try:
        _set_progress("Cargando datos…")
        datos     = cargar_datos(INPUTS_DIR)
        historico = leer_historico(INPUTS_DIR)
        _state["datos"] = datos

        _set_progress("Ejecutando CP-SAT…")
        # resolver_con_fallback intenta en hasta 6 niveles de relajación;
        # nunca lanza excepción por INFEASIBLE — siempre devuelve algo.
        resultado_cpsat = resolver_con_fallback(
            datos,
            carreras=req.carreras,
            tiempo_limite_s=req.tiempo_limite_cpsat,
        )

        if resultado_cpsat.estado not in ("OPTIMAL", "FEASIBLE"):
            # Solo falla si ni el nivel más relajado encontró solución (muy raro).
            raise RuntimeError(
                "CP-SAT no encontró solución ni siquiera con restricciones mínimas. "
                "Revisa los datos de disponibilidad en el maestro."
            )

        # Guardar la advertencia de relajación para devolverla al frontend.
        _state["advertencia_relajacion"] = resultado_cpsat.advertencia_relajacion
        if resultado_cpsat.nivel_relajacion > 0:
            _set_progress(
                f"CP-SAT: solución parcial nivel {resultado_cpsat.nivel_relajacion}/5. "
                "Ejecutando GA…"
            )
        else:
            _set_progress(f"CP-SAT: {resultado_cpsat.estado}. Ejecutando GA…")

        resultado_ga = ejecutar_ga(
            datos,
            resultado_cpsat.asignaciones,
            historico,
            n_generaciones=req.n_generaciones,
            pop_size=req.pop_size,
            seed=req.seed,
        )

        asignaciones = resultado_ga.asignaciones

        _set_progress("Calculando métricas y reporte…")
        ctx           = construir_contexto(datos, resultado_cpsat.asignaciones, historico)
        fitness_cpsat = calcular_fitness(encode(resultado_cpsat.asignaciones, ctx), ctx)[0]
        fitness_ga    = resultado_ga.fitness_final
        mejora_pct    = (
            (fitness_cpsat - fitness_ga) / fitness_cpsat * 100
            if fitness_cpsat > 0 else 0.0
        )
        n_bloques_totales = sum(len(b) for b in asignaciones.values())

        reporte_raw = generar_reporte_detallado(datos, asignaciones, historico)

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
            "estado_cpsat":           resultado_cpsat.estado,
            "nivel_relajacion":       resultado_cpsat.nivel_relajacion,
            "advertencia_relajacion": resultado_cpsat.advertencia_relajacion,
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

        _state["asignaciones"] = asignaciones
        _state["metricas"]     = metricas_api
        _state["reporte"]      = reporte_raw
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
            (INPUTS_DIR / nombre).write_bytes(contenido)
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
        _state["asignaciones"]           = None
        _state["metricas"]               = None
        _state["reporte"]                = None
        _state["excel_bytes"]            = None
        _state["advertencia_relajacion"] = ""

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
    """Devuelve secciones, métricas y reporte de violaciones. 404 si no está listo."""
    if _state["status"] != "ready":
        raise HTTPException(
            status_code=404,
            detail=f"Resultados no disponibles (status={_state['status']})",
        )
    secciones = _build_secciones(_state["datos"], _state["asignaciones"])
    metricas_raw = _state["metricas"]
    metricas = MetricasResult(
        fitness_cpsat=metricas_raw["fitness_cpsat"],
        fitness_ga=metricas_raw["fitness_ga"],
        mejora_pct=metricas_raw["mejora_pct"],
        n_secciones=metricas_raw["n_secciones"],
        n_bloques_totales=metricas_raw["n_bloques_totales"],
        estado_cpsat=metricas_raw["estado_cpsat"],
        nivel_relajacion=metricas_raw.get("nivel_relajacion", 0),
        advertencia_relajacion=metricas_raw.get("advertencia_relajacion", ""),
    )
    reporte = _build_reporte(_state["reporte"]) if _state["reporte"] else None
    return SolveResult(metricas=metricas, secciones=secciones, reporte=reporte)


@router.get("/report", response_model=ReporteDetallado)
def get_report():
    """Devuelve solo el reporte de violaciones. 404 si no está listo."""
    if _state["status"] != "ready" or _state["reporte"] is None:
        raise HTTPException(
            status_code=404,
            detail=f"Reporte no disponible (status={_state['status']})",
        )
    return _build_reporte(_state["reporte"])


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