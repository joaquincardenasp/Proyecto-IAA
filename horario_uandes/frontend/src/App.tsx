import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  Download,
  Loader2,
} from "lucide-react";
import {
  getStatus,
  getResults,
  EXPORT_URL,
  guardarHorario,
  getBloquesCatalogo,
  validarHorario,
} from "./api/client";
import type {
  SolveResult,
  StatusResponse,
  BloqueCatalogo,
  ValidarHorarioResponse,
  Dia,
  SeccionAsignada,
} from "./types";
import SolverPanel from "./components/SolverPanel";
import HorarioGrid from "./components/HorarioGrid";
import MetricasPanel from "./components/MetricasPanel";
import ValidacionPanel from "./components/ValidacionPanel";
import DiagnosticoPanel from "./components/DiagnosticoPanel";

type Tab = "solver" | "horario" | "metricas" | "diagnostico";

// ── Etapas del proceso ────────────────────────────────────────────────────────

const STAGES: { label: string; match: (p: string) => boolean }[] = [
  {
    label: "Leyendo archivos",
    match: (p) => p.includes("datos") || p.includes("Iniciando"),
  },
  {
    label: "Generando horario base",
    match: (p) =>
      p.includes("mejor horario") ||
      p.includes("Diagnosticando") ||
      (p.includes("CP-SAT") && !p.includes("GA")),
  },
  {
    label: "Optimizando (Alg. Genético)",
    match: (p) => p.includes("GA") || p.includes("métricas"),
  },
  {
    label: "Exportando resultados",
    match: (p) => p.includes("Excel") || p.includes("Completado"),
  },
];

function progressToStage(progress: string): number {
  const idx = STAGES.findIndex((s) => s.match(progress));
  return idx >= 0 ? idx + 1 : 1;
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab] = useState<Tab>("solver");
  const [status, setStatus] = useState<StatusResponse>({
    status: "idle",
    progress: "",
    error: "",
  });
  const [results, setResults] = useState<SolveResult | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Estado de edición manual del horario ──────────────────────────────────
  const [editando, setEditando] = useState(false);
  const [seccionesEditables, setSeccionesEditables] = useState<
    SeccionAsignada[]
  >([]);
  const [bloquesCatalogo, setBloquesCatalogo] = useState<BloqueCatalogo[]>([]);
  const [validacion, setValidacion] = useState<ValidarHorarioResponse | null>(
    null,
  );
  const [validando, setValidando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [guardadoOk, setGuardadoOk] = useState(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    setStatus({ status: "running", progress: "Iniciando…", error: "" });
    pollRef.current = setInterval(async () => {
      try {
        const s = await getStatus();
        setStatus(s);
        if (s.status === "ready") {
          stopPolling();
          const r = await getResults();
          setResults(r);
          // INFEASIBLE no tiene horario → abrir directo el diagnóstico.
          setTab(r.estado === "INFEASIBLE" ? "diagnostico" : "horario");
        } else if (s.status === "error") {
          stopPolling();
        }
      } catch (e) {
        console.error("Poll error:", e);
      }
    }, 2000);
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  useEffect(() => {
    getBloquesCatalogo().then(setBloquesCatalogo).catch(console.error);
  }, []);

  useEffect(() => {
    if (results) setSeccionesEditables(results.secciones);
  }, [results]);

  const isRunning = status.status === "running";
  const activeStage = isRunning ? progressToStage(status.progress) : 0;

  const tieneHorario = !!results && results.secciones.length > 0;
  const tieneDiagnostico =
    !!results?.diagnostico && results.diagnostico.unidades.length > 0;
  const nBloqueadas = results?.diagnostico?.unidades.length ?? 0;

  const TABS: { id: Tab; label: string; disabled?: boolean }[] = [
    { id: "solver", label: "Generar horario" },
    { id: "horario", label: "Horario", disabled: !tieneHorario },
    { id: "metricas", label: "Métricas", disabled: !results?.metricas },
    { id: "diagnostico", label: "Diagnóstico", disabled: !tieneDiagnostico },
  ];

  function toMin(h: string) {
    const [a, b] = h.split(":").map(Number);
    return a * 60 + b;
  }
  function minToHora(m: number) {
    const h = Math.floor(m / 60),
      mm = m % 60;
    return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
  }

  function moverBloque(
    secId: string,
    bloqueIdx: number,
    nuevoDia: Dia,
    nuevaHoraInicio: string,
  ) {
    setSeccionesEditables((prev) =>
      prev.map((sec) => {
        if (sec.id !== secId) return sec;
        const orig = sec.bloques[bloqueIdx];
        if (!orig) return sec;
        const dur = toMin(orig.hora_fin) - toMin(orig.hora_inicio);
        const nuevos = sec.bloques.map((b, i) =>
          i === bloqueIdx
            ? {
                ...b,
                dia: nuevoDia,
                hora_inicio: nuevaHoraInicio,
                hora_fin: minToHora(toMin(nuevaHoraInicio) + dur),
              }
            : b,
        );
        return { ...sec, bloques: nuevos };
      }),
    );
    setValidacion(null);
  }

  function buildPayload() {
    const findIdx = (b: {
      dia: Dia;
      hora_inicio: string;
      hora_fin: string;
      tipo_bloque: string;
    }) => {
      const iniM = toMin(b.hora_inicio);
      const finM = toMin(b.hora_fin);

      const exacto = bloquesCatalogo.find(
        (c) =>
          c.dia === b.dia &&
          toMin(c.hora_inicio) === iniM &&
          toMin(c.hora_fin) === finM,
      );
      if (exacto) return exacto.idx;

      const candsTipo = bloquesCatalogo.filter(
        (c) => c.dia === b.dia && c.tipo === b.tipo_bloque,
      );
      if (candsTipo.length > 0) {
        return candsTipo.reduce((best, c) =>
          Math.abs(toMin(c.hora_inicio) - iniM) <
          Math.abs(toMin(best.hora_inicio) - iniM)
            ? c
            : best,
        ).idx;
      }

      const candsDia = bloquesCatalogo.filter((c) => c.dia === b.dia);
      if (candsDia.length === 0) return undefined;
      return candsDia.reduce((best, c) =>
        Math.abs(toMin(c.hora_inicio) - iniM) <
        Math.abs(toMin(best.hora_inicio) - iniM)
          ? c
          : best,
      ).idx;
    };

    return seccionesEditables.map((sec) => ({
      sec_id: sec.id,
      bloques: sec.bloques
        .map((b) => findIdx(b))
        .filter((i): i is number => i !== undefined),
    }));
  }

  async function calcularRestricciones() {
    setValidando(true);
    try {
      const res = await validarHorario(buildPayload());
      setValidacion(res);
    } catch (e) {
      console.error(e);
    } finally {
      setValidando(false);
    }
  }

  const hayCambios = useMemo(() => {
    if (!results) return false;
    return (
      JSON.stringify(seccionesEditables) !== JSON.stringify(results.secciones)
    );
  }, [seccionesEditables, results]);

  function descartarCambios() {
    if (!results) return;
    setSeccionesEditables(results.secciones);
    setValidacion(null);
    setGuardadoOk(false);
  }

  async function guardarCambios() {
    setGuardando(true);
    setGuardadoOk(false);
    try {
      const nuevoResultado = await guardarHorario(buildPayload());
      setResults(nuevoResultado);
      setSeccionesEditables(nuevoResultado.secciones);
      setValidacion(null);
      setGuardadoOk(true);
      setTimeout(() => setGuardadoOk(false), 3000);
    } catch (e) {
      console.error(e);
      alert(`No se pudo guardar el horario: ${(e as Error).message}`);
    } finally {
      setGuardando(false);
    }
  }

  const seccionesConViolacion = useMemo(() => {
    if (!validacion) return undefined;
    const set = new Set<string>();
    for (const v of validacion.violaciones_duras)
      for (const s of v.secciones) set.add(s);
    return set;
  }, [validacion]);

  return (
    <div className="min-h-screen bg-[#FAFAFA] flex flex-col">
      {/* ── Header institucional ──────────────────────────────────────────── */}
      <header className="bg-[#B71C1C] shrink-0">
        <div className="max-w-screen-xl mx-auto px-6 py-4 flex items-center gap-5">
          <div className="border-r border-red-700 pr-5 shrink-0">
            <span className="text-white font-bold text-sm tracking-widest uppercase">
              Uandes
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-white font-semibold text-sm leading-tight truncate">
              Generador de Horarios
            </h1>
            <p className="text-red-300 text-xs mt-0.5 truncate">
              Facultad de Ingeniería y Ciencias Aplicadas
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {isRunning && (
              <span className="flex items-center gap-1.5 text-xs text-red-200">
                <Loader2 size={13} className="animate-spin" />
                Procesando
              </span>
            )}
            {tieneHorario && (
              <a
                href={EXPORT_URL}
                download="horario_generado.xlsx"
                className="flex items-center gap-1.5 text-xs font-medium bg-white
                          text-[#B71C1C] hover:bg-red-50 px-3 py-1.5 rounded transition-colors"
              >
                <Download size={13} />
                Descargar Excel
              </a>
            )}
          </div>
        </div>
      </header>

      {/* ── Barra de navegación ───────────────────────────────────────────── */}
      <div className="bg-white border-b border-gray-200 shrink-0">
        <div className="max-w-screen-xl mx-auto px-6">
          <nav className="flex">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => !t.disabled && setTab(t.id)}
                disabled={t.disabled}
                className={`px-5 py-3.5 text-sm font-medium border-b-2 transition-colors
                  ${
                    tab === t.id
                      ? "border-[#B71C1C] text-[#B71C1C]"
                      : t.disabled
                        ? "border-transparent text-gray-300 cursor-not-allowed"
                        : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                  }`}
              >
                {t.label}
                {t.id === "horario" && tieneHorario && (
                  <span className="ml-2 text-[11px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded font-normal tabular-nums">
                    {results!.secciones.length}
                  </span>
                )}
                {t.id === "diagnostico" && tieneDiagnostico && (
                  <span className="ml-2 text-[11px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium tabular-nums">
                    {nBloqueadas}
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* ── Progreso por etapas ───────────────────────────────────────────── */}
      {isRunning && (
        <div className="bg-white border-b border-gray-100 py-4 shrink-0">
          <div className="max-w-screen-xl mx-auto px-6">
            <div className="flex items-center">
              {STAGES.map((stage, i) => {
                const num = i + 1;
                const isDone = activeStage > num;
                const isActive = activeStage === num;
                const isLast = i === STAGES.length - 1;
                return (
                  <div
                    key={i}
                    className="flex items-center flex-1 last:flex-none"
                  >
                    <div className="flex items-center gap-2 shrink-0">
                      <div
                        className={`w-6 h-6 rounded-full flex items-center justify-center
                          ${isDone ? "bg-green-600" : isActive ? "bg-[#B71C1C]" : "bg-gray-200"}`}
                      >
                        {isDone ? (
                          <Check
                            size={11}
                            className="text-white"
                            strokeWidth={3}
                          />
                        ) : (
                          <span
                            className={`text-[10px] font-bold ${isActive ? "text-white" : "text-gray-400"}`}
                          >
                            {num}
                          </span>
                        )}
                      </div>
                      <span
                        className={`text-xs font-medium hidden md:block
                          ${isDone ? "text-green-600" : isActive ? "text-[#B71C1C]" : "text-gray-400"}`}
                      >
                        {stage.label}
                      </span>
                    </div>
                    {!isLast && (
                      <div
                        className={`h-px flex-1 mx-3 transition-colors ${isDone ? "bg-green-300" : "bg-gray-200"}`}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── Banner de error ───────────────────────────────────────────────── */}
      {status.status === "error" && status.error && (
        <div className="bg-red-50 border-b border-red-200 px-6 py-2.5 shrink-0">
          <div className="max-w-screen-xl mx-auto flex items-center gap-2 text-sm text-red-700">
            <AlertCircle size={14} className="shrink-0" />
            {status.error}
          </div>
        </div>
      )}

      {/* ── Banner de estado del resultado (PARCIAL / INFEASIBLE) ─────────────── */}
      {results &&
        results.estado !== "FACTIBLE" &&
        status.status === "ready" && (
          <div
            className={`border-b px-6 py-2.5 shrink-0 ${
              results.estado === "INFEASIBLE"
                ? "bg-red-50 border-red-200"
                : "bg-amber-50 border-amber-200"
            }`}
          >
            <div
              className={`max-w-screen-xl mx-auto flex items-center gap-2 text-sm ${
                results.estado === "INFEASIBLE"
                  ? "text-red-700"
                  : "text-amber-700"
              }`}
            >
              <AlertTriangle size={14} className="shrink-0" />
              {results.estado === "INFEASIBLE" ? (
                <span>
                  No fue posible generar un horario. Revisa el{" "}
                  <button
                    onClick={() => setTab("diagnostico")}
                    className="font-semibold underline underline-offset-2"
                  >
                    diagnóstico
                  </button>{" "}
                  para ver la causa y las acciones sugeridas.
                </span>
              ) : (
                <span>
                  Horario parcial: {results.secciones.length} secciones
                  generadas. {nBloqueadas} unidad{nBloqueadas !== 1 ? "es" : ""}{" "}
                  sin ubicar —{" "}
                  <button
                    onClick={() => setTab("diagnostico")}
                    className="font-semibold underline underline-offset-2"
                  >
                    ver diagnóstico
                  </button>
                  .
                </span>
              )}
            </div>
          </div>
        )}

      {/* ── Contenido ─────────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-screen-xl mx-auto w-full px-6 py-8">
        {tab === "solver" && (
          <SolverPanel status={status} onSolveStarted={startPolling} />
        )}

        {tab === "horario" && results && (
          <>
            <div className="flex items-center gap-2 mb-4">
              <button
                onClick={() => setEditando((e) => !e)}
                className={`text-xs font-medium px-3 py-1.5 rounded transition-colors
                  ${editando ? "bg-gray-800 text-white" : "border border-gray-300 text-gray-600 hover:bg-gray-50"}`}
              >
                {editando ? "Modo edición activo" : "Editar horario"}
              </button>
              {editando && (
                <>
                  <button
                    onClick={calcularRestricciones}
                    disabled={validando}
                    className="text-xs font-medium px-3 py-1.5 rounded bg-[#B71C1C] text-white hover:bg-[#C62828]
                              disabled:opacity-50"
                  >
                    {validando ? "Calculando…" : "Calcular restricciones"}
                  </button>
                  <button
                    onClick={descartarCambios}
                    disabled={!hayCambios}
                    className="text-xs font-medium px-3 py-1.5 rounded border border-gray-300
                              text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                  >
                    Descartar cambios
                  </button>
                  <button
                    onClick={guardarCambios}
                    disabled={!hayCambios || guardando}
                    className="text-xs font-medium px-3 py-1.5 rounded bg-green-700 text-white
                              hover:bg-green-800 disabled:opacity-40"
                  >
                    {guardando ? "Guardando…" : "Guardar"}
                  </button>
                  {guardadoOk && (
                    <span className="text-xs text-green-700 font-medium">
                      ✓ Horario guardado
                    </span>
                  )}
                </>
              )}
            </div>

            <HorarioGrid
              secciones={editando ? seccionesEditables : results.secciones}
              bloquesCatalogo={bloquesCatalogo}
              editable={editando}
              seccionesConViolacion={seccionesConViolacion}
              onMoverBloque={moverBloque}
            />

            {validacion && (
              <ValidacionPanel
                resultado={validacion}
                onClose={() => setValidacion(null)}
                onJumpToSeccion={(secId) => {
                  document
                    .getElementById(`sec-${secId}`)
                    ?.scrollIntoView({ behavior: "smooth", block: "center" });
                }}
              />
            )}
          </>
        )}

        {tab === "metricas" && results?.metricas && (
          <MetricasPanel
            metricas={results.metricas}
            secciones={results.secciones}
            reporte={results.reporte}
          />
        )}
        {tab === "diagnostico" && results?.diagnostico && (
          <DiagnosticoPanel
            diagnostico={results.diagnostico}
            estado={results.estado}
            nColocadas={results.secciones.length}
          />
        )}
      </main>
    </div>
  );
}
