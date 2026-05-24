import { useState, useEffect, useRef, useCallback } from 'react'
import { AlertCircle, Check, Download, Loader2 } from 'lucide-react'
import { getStatus, getResults } from './api/client'
import type { SolveResult, StatusResponse } from './types'
import SolverPanel from './components/SolverPanel'
import HorarioGrid from './components/HorarioGrid'
import MetricasPanel from './components/MetricasPanel'

type Tab = 'solver' | 'horario' | 'metricas'

// ── Etapas del proceso ────────────────────────────────────────────────────────

const STAGES: { label: string; match: (p: string) => boolean }[] = [
  { label: 'Leyendo archivos',              match: p => p.includes('datos') || p.includes('Iniciando') },
  { label: 'Generando horario base',        match: p => p.includes('CP-SAT') && !p.includes('GA') },
  { label: 'Optimizando (Alg. Genético)',   match: p => p.includes('GA') || p.includes('métricas') },
  { label: 'Exportando resultados',         match: p => p.includes('Excel') || p.includes('Completado') },
]

function progressToStage(progress: string): number {
  const idx = STAGES.findIndex(s => s.match(progress))
  return idx >= 0 ? idx + 1 : 1
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab]         = useState<Tab>('solver')
  const [status, setStatus]   = useState<StatusResponse>({ status: 'idle', progress: '', error: '' })
  const [results, setResults] = useState<SolveResult | null>(null)
  const pollRef               = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  const startPolling = useCallback(() => {
    stopPolling()
    setStatus({ status: 'running', progress: 'Iniciando…', error: '' })
    pollRef.current = setInterval(async () => {
      try {
        const s = await getStatus()
        setStatus(s)
        if (s.status === 'ready') {
          stopPolling()
          const r = await getResults()
          setResults(r)
          setTab('horario')
        } else if (s.status === 'error') {
          stopPolling()
        }
      } catch (e) {
        console.error('Poll error:', e)
      }
    }, 2000)
  }, [stopPolling])

  useEffect(() => () => stopPolling(), [stopPolling])

  const isRunning   = status.status === 'running'
  const activeStage = isRunning ? progressToStage(status.progress) : 0

  const TABS: { id: Tab; label: string; disabled?: boolean }[] = [
    { id: 'solver',   label: 'Generar horario' },
    { id: 'horario',  label: 'Horario',  disabled: !results },
    { id: 'metricas', label: 'Métricas', disabled: !results },
  ]

  return (
    <div className="min-h-screen bg-[#FAFAFA] flex flex-col">

      {/* ── Header institucional ──────────────────────────────────────────── */}
      <header className="bg-[#B71C1C] shrink-0">
        <div className="max-w-screen-xl mx-auto px-6 py-4 flex items-center gap-5">
          {/* Logotipo textual */}
          <div className="border-r border-red-700 pr-5 shrink-0">
            <span className="text-white font-bold text-sm tracking-widest uppercase">
              Uandes
            </span>
          </div>

          {/* Título */}
          <div className="flex-1 min-w-0">
            <h1 className="text-white font-semibold text-sm leading-tight truncate">
              Generador de Horarios
            </h1>
            <p className="text-red-300 text-xs mt-0.5 truncate">
              Facultad de Ingeniería y Ciencias Aplicadas
            </p>
          </div>

          {/* Acciones */}
          <div className="flex items-center gap-3 shrink-0">
            {isRunning && (
              <span className="flex items-center gap-1.5 text-xs text-red-200">
                <Loader2 size={13} className="animate-spin" />
                Procesando
              </span>
            )}
            {results && (
              <a
                href="/api/export"
                download="horario_generado.xlsx"
                className="flex items-center gap-1.5 text-xs font-medium bg-white
                           text-[#B71C1C] hover:bg-red-50 px-3 py-1.5 rounded
                           transition-colors"
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
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => !t.disabled && setTab(t.id)}
                disabled={t.disabled}
                className={`px-5 py-3.5 text-sm font-medium border-b-2 transition-colors
                  ${tab === t.id
                    ? 'border-[#B71C1C] text-[#B71C1C]'
                    : t.disabled
                      ? 'border-transparent text-gray-300 cursor-not-allowed'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }`}
              >
                {t.label}
                {t.id === 'horario' && results && (
                  <span className="ml-2 text-[11px] bg-gray-100 text-gray-500
                                   px-1.5 py-0.5 rounded font-normal tabular-nums">
                    {results.secciones.length}
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
                const num      = i + 1
                const isDone   = activeStage > num
                const isActive = activeStage === num
                const isLast   = i === STAGES.length - 1
                return (
                  <div key={i} className="flex items-center flex-1 last:flex-none">
                    <div className="flex items-center gap-2 shrink-0">
                      <div
                        className={`w-6 h-6 rounded-full flex items-center justify-center
                          ${isDone
                            ? 'bg-green-600'
                            : isActive
                              ? 'bg-[#B71C1C]'
                              : 'bg-gray-200'
                          }`}
                      >
                        {isDone
                          ? <Check size={11} className="text-white" strokeWidth={3} />
                          : <span
                              className={`text-[10px] font-bold
                                ${isActive ? 'text-white' : 'text-gray-400'}`}
                            >
                              {num}
                            </span>
                        }
                      </div>
                      <span
                        className={`text-xs font-medium hidden md:block
                          ${isDone
                            ? 'text-green-600'
                            : isActive
                              ? 'text-[#B71C1C]'
                              : 'text-gray-400'
                          }`}
                      >
                        {stage.label}
                      </span>
                    </div>
                    {!isLast && (
                      <div
                        className={`h-px flex-1 mx-3 transition-colors
                          ${isDone ? 'bg-green-300' : 'bg-gray-200'}`}
                      />
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── Banner de error ───────────────────────────────────────────────── */}
      {status.status === 'error' && status.error && (
        <div className="bg-red-50 border-b border-red-200 px-6 py-2.5 shrink-0">
          <div className="max-w-screen-xl mx-auto flex items-center gap-2
                          text-sm text-red-700">
            <AlertCircle size={14} className="shrink-0" />
            {status.error}
          </div>
        </div>
      )}

      {/* ── Contenido ─────────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-screen-xl mx-auto w-full px-6 py-8">
        {tab === 'solver' && (
          <SolverPanel status={status} onSolveStarted={startPolling} />
        )}
        {tab === 'horario' && results && (
          <HorarioGrid secciones={results.secciones} />
        )}
        {tab === 'metricas' && results && (
          <MetricasPanel metricas={results.metricas} secciones={results.secciones} />
        )}
      </main>
    </div>
  )
}
