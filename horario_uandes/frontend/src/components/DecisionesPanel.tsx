import { useState, useEffect } from 'react'
import { AlertTriangle, Check, RefreshCw, Loader2, Layers, Info } from 'lucide-react'
import type { DecisionSeccion } from '../types'
import { setDistribucion, setDuracion } from '../api/client'

interface Props {
  decisiones: DecisionSeccion[]
  onRegenerar: () => void
  regenerando: boolean
}

const OPCION_LABEL: Record<string, string> = {
  '3-juntas': '3 juntas (1 bloque de 3h)',
  '2+1': '2+1 (2h + 1h)',
  '1h': '1 hora',
  '2h': '2 horas',
}

export default function DecisionesPanel({ decisiones, onRegenerar, regenerando }: Props) {
  const [lista, setLista] = useState<DecisionSeccion[]>(decisiones)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')

  // Sincronizar con el padre cuando llegan decisiones nuevas (tras regenerar/refetch).
  useEffect(() => setLista(decisiones), [decisiones])

  async function elegir(d: DecisionSeccion, opcion: string) {
    if (opcion === d.actual) return
    setBusy(d.sec_id); setError('')
    try {
      const fn = d.tipo === 'distribucion' ? setDistribucion : setDuracion
      const nueva = await fn(d.sec_id, opcion)
      setLista(nueva)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al guardar la decisión')
    } finally {
      setBusy(null)
    }
  }

  const requeridas = lista.filter((d) => d.requerida)
  const opcionales = lista.filter((d) => !d.requerida)
  const pendientes = requeridas.filter((d) => !d.actual).length

  return (
    <div className="space-y-6">
      {/* ── Banner + acción regenerar ─────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 bg-amber-50 border border-amber-200 rounded-lg p-5">
        <div className="flex items-start gap-3">
          <AlertTriangle size={20} className="text-amber-600 shrink-0 mt-0.5" />
          <div>
            <h2 className="text-sm font-semibold text-amber-800">
              Decisiones de estructura de clases
            </h2>
            <p className="text-xs text-amber-700 mt-1 leading-relaxed">
              {pendientes > 0 ? (
                <>
                  <strong>{pendientes}</strong> clase{pendientes !== 1 ? 's' : ''} de 3h no
                  tiene{pendientes !== 1 ? 'n' : ''} distribución definida y{' '}
                  <strong>no se programa{pendientes !== 1 ? 'n' : ''}</strong> hasta que elijas.
                  Define las opciones y luego regenera el horario.
                </>
              ) : (
                <>Todas las decisiones requeridas están tomadas. Regenera para aplicarlas.</>
              )}
            </p>
          </div>
        </div>
        <button
          onClick={onRegenerar}
          disabled={regenerando}
          className="flex items-center gap-2 text-xs font-medium bg-[#B71C1C] text-white
                     hover:bg-red-800 disabled:opacity-60 px-3 py-2 rounded transition-colors shrink-0"
        >
          {regenerando ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          Regenerar horario
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
          {error}
        </div>
      )}

      {/* ── Requeridas: distribución de clases de 3h ──────────────────────── */}
      {requeridas.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Requieren decisión ({requeridas.length})
          </h3>
          <div className="space-y-2">
            {requeridas.map((d) => (
              <DecisionRow key={d.sec_id} d={d} busy={busy === d.sec_id} onElegir={elegir} />
            ))}
          </div>
        </section>
      )}

      {/* ── Opcionales: componentes de 1h ─────────────────────────────────── */}
      {opcionales.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3 flex items-center gap-1.5">
            <Info size={13} /> Ajustes opcionales — componentes de 1 hora ({opcionales.length})
          </h3>
          <div className="space-y-2">
            {opcionales.map((d) => (
              <DecisionRow key={d.sec_id} d={d} busy={busy === d.sec_id} onElegir={elegir} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

// ── Fila de decisión ────────────────────────────────────────────────────────────

function DecisionRow({
  d, busy, onElegir,
}: {
  d: DecisionSeccion
  busy: boolean
  onElegir: (d: DecisionSeccion, opcion: string) => void
}) {
  const sinElegir = d.requerida && !d.actual
  return (
    <div
      className={`bg-white border rounded-lg p-4 ${
        sinElegir ? 'border-amber-300' : 'border-gray-200'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Layers size={14} className="text-gray-400 shrink-0" />
            <span className="text-sm font-semibold text-gray-800">
              {d.codigo}-{d.seccion}
            </span>
            <span className="text-xs text-gray-400 truncate">{d.titulo}</span>
          </div>
          <p className="text-[11px] text-gray-500 mt-1 leading-relaxed">{d.mensaje}</p>
          {d.profesor && (
            <p className="text-[11px] text-gray-400 mt-0.5">Prof. {d.profesor}</p>
          )}
        </div>

        {/* Segmented control de opciones */}
        <div className="flex items-center gap-1 shrink-0">
          {busy && <Loader2 size={13} className="animate-spin text-gray-400 mr-1" />}
          {d.opciones.map((op) => {
            const activo = d.actual === op
            return (
              <button
                key={op}
                onClick={() => onElegir(d, op)}
                disabled={busy}
                className={`flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded
                  border transition-colors disabled:opacity-60
                  ${
                    activo
                      ? 'bg-green-600 border-green-600 text-white'
                      : 'bg-white border-gray-300 text-gray-600 hover:border-gray-400'
                  }`}
              >
                {activo && <Check size={11} />}
                {OPCION_LABEL[op] ?? op}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
