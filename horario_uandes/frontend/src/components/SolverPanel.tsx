import { useState } from 'react'
import { AlertCircle, FolderOpen, Loader2, FileSpreadsheet } from 'lucide-react'
import { postSolve } from '../api/client'
import type { StatusResponse, PlanificacionInfo } from '../types'

interface Props {
  status: StatusResponse
  onSolveStarted: () => void
  planificacion: PlanificacionInfo | null
  onIrAPlanificaciones: () => void
}

export default function SolverPanel({
  status, onSolveStarted, planificacion, onIrAPlanificaciones,
}: Props) {
  const [solveError, setSolveError] = useState('')
  const isRunning = status.status === 'running'

  async function handleSolve() {
    setSolveError('')
    try {
      await postSolve()
      onSolveStarted()
    } catch (e) {
      setSolveError(e instanceof Error ? e.message : String(e))
    }
  }

  // Sin planificación activa no se puede generar (no existe modo efímero).
  if (!planificacion) {
    return (
      <div className="max-w-xl mx-auto text-center py-12">
        <FolderOpen size={32} className="mx-auto mb-4 text-gray-300" />
        <h2 className="text-sm font-semibold text-gray-800">No hay planificación activa</h2>
        <p className="text-sm text-gray-500 mt-2 leading-relaxed">
          Para generar un horario primero debes crear o activar una planificación (con sus
          archivos Maestro y de salas). Así tu trabajo queda guardado y no se pierde.
        </p>
        <button
          onClick={onIrAPlanificaciones}
          className="mt-5 text-xs font-medium bg-[#B71C1C] text-white hover:bg-red-800
                     px-4 py-2 rounded transition-colors"
        >
          Ir a Planificaciones
        </button>
      </div>
    )
  }

  return (
    <div className="max-w-xl mx-auto space-y-6">
      <section className="bg-white border border-gray-200 rounded-lg p-5">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Planificación activa
        </h2>
        <div className="flex items-center gap-2">
          <FolderOpen size={16} className="text-[#B71C1C] shrink-0" />
          <span className="text-sm font-semibold text-gray-800">{planificacion.nombre}</span>
        </div>
        <div className="flex items-center gap-2 mt-2 text-[11px] text-gray-400">
          <FileSpreadsheet size={12} />
          {planificacion.maestro_nombre || 'Maestro'}
          {planificacion.salas_nombre ? ` · ${planificacion.salas_nombre}` : ''}
        </div>
      </section>

      {solveError && (
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200
                        rounded-lg text-sm text-red-700">
          <AlertCircle size={14} className="shrink-0 mt-0.5" />
          <span>{solveError}</span>
        </div>
      )}

      <button
        onClick={handleSolve}
        disabled={isRunning}
        className={`w-full py-3 rounded-lg text-sm font-semibold tracking-wide transition-colors
          ${isRunning
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
            : 'bg-[#B71C1C] hover:bg-[#C62828] text-white'
          }`}
      >
        {isRunning ? (
          <span className="flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            Generando horario…
          </span>
        ) : (
          'Generar Horario'
        )}
      </button>
    </div>
  )
}
