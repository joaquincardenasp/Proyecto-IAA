import { useState, useEffect, useCallback } from 'react'
import {
  Plus, Trash2, Loader2, Upload, X, FolderOpen, Calendar, Layers, ChevronRight,
} from 'lucide-react'
import type { PlanificacionInfo } from '../types'
import {
  crearPlanificacion, listarPlanificaciones, eliminarPlanificacion,
} from '../api/client'

interface Props {
  /** Entrar al espacio de trabajo de una planificación. */
  onAbrir: (pl: PlanificacionInfo) => void | Promise<void>
}

export default function InicioPlanificaciones({ onAbrir }: Props) {
  const [pls, setPls] = useState<PlanificacionInfo[]>([])
  const [modal, setModal] = useState(false)
  const [error, setError] = useState('')

  const refrescar = useCallback(async () => {
    setPls(await listarPlanificaciones())
  }, [])

  useEffect(() => { refrescar() }, [refrescar])

  async function borrar(id: number, e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm('¿Eliminar la planificación y todas sus versiones? No se puede deshacer.')) return
    await eliminarPlanificacion(id)
    await refrescar()
  }

  return (
    <div className="space-y-6">
      {/* ── Cabecera ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Planificaciones</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Cada planificación guarda su propio horario y versiones.
          </p>
        </div>
        <button
          onClick={() => { setError(''); setModal(true) }}
          className="flex items-center gap-2 text-sm font-medium bg-[#B71C1C] text-white
                     hover:bg-red-800 px-4 py-2.5 rounded-lg transition-colors shrink-0"
        >
          <Plus size={16} /> Crear nueva planificación
        </button>
      </div>

      {/* ── Lista de tarjetas ────────────────────────────────────────────────── */}
      {pls.length === 0 ? (
        <div className="text-center py-16 border-2 border-dashed border-gray-200 rounded-xl">
          <FolderOpen size={32} className="mx-auto mb-3 text-gray-300" />
          <p className="text-sm text-gray-500">
            Aún no tienes planificaciones. Crea una para empezar.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {pls.map(pl => (
            <PlanCard key={pl.id} pl={pl} onAbrir={onAbrir} onBorrar={borrar} />
          ))}
        </div>
      )}

      {/* ── Modal de creación ────────────────────────────────────────────────── */}
      {modal && (
        <CrearModal
          onClose={() => setModal(false)}
          onCreada={async (pl) => { setModal(false); await refrescar(); await onAbrir(pl) }}
          error={error} setError={setError}
        />
      )}
    </div>
  )
}

// ── Tarjeta de planificación ────────────────────────────────────────────────────

function PlanCard({
  pl, onAbrir, onBorrar,
}: {
  pl: PlanificacionInfo
  onAbrir: (pl: PlanificacionInfo) => void | Promise<void>
  onBorrar: (id: number, e: React.MouseEvent) => void
}) {
  const badge = estadoBadge(pl)
  return (
    <button
      onClick={() => onAbrir(pl)}
      className="group text-left bg-white border border-gray-200 rounded-xl p-5
                 hover:border-[#B71C1C] hover:shadow-sm transition-all flex flex-col gap-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <FolderOpen size={17} className="text-[#B71C1C] shrink-0" />
          <span className="text-sm font-semibold text-gray-900 truncate">{pl.nombre}</span>
        </div>
        <span
          onClick={(e) => onBorrar(pl.id, e)}
          className="text-gray-300 hover:text-red-600 p-1 -m-1 rounded transition-colors shrink-0"
          role="button"
          title="Eliminar"
        >
          <Trash2 size={14} />
        </span>
      </div>

      <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded w-fit ${badge.cls}`}>
        {badge.label}
      </span>

      <div className="text-[11px] text-gray-400 space-y-1 mt-auto">
        <div className="flex items-center gap-1.5">
          <Calendar size={11} /> Modificada {fechaRel(pl.actualizada)}
        </div>
        <div className="flex items-center gap-1.5">
          <Layers size={11} />
          {pl.tiene_horario ? `${pl.n_secciones} secciones · ` : ''}
          {pl.n_versiones} versión{pl.n_versiones !== 1 ? 'es' : ''}
        </div>
      </div>

      <div className="flex items-center gap-1 text-xs font-medium text-[#B71C1C] opacity-0
                      group-hover:opacity-100 transition-opacity">
        Abrir espacio de trabajo <ChevronRight size={14} />
      </div>
    </button>
  )
}

function estadoBadge(pl: PlanificacionInfo): { label: string; cls: string } {
  if (!pl.tiene_horario) return { label: 'Pendiente de generar', cls: 'bg-gray-100 text-gray-500' }
  if (pl.n_conflictos > 0)
    return { label: `Con ${pl.n_conflictos} conflicto${pl.n_conflictos !== 1 ? 's' : ''}`, cls: 'bg-red-100 text-red-700' }
  if (pl.estado_horario === 'PARCIAL') return { label: 'Parcial', cls: 'bg-amber-100 text-amber-700' }
  return { label: 'Generado', cls: 'bg-green-100 text-green-700' }
}

function fechaRel(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'hace instantes'
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`
  return d.toLocaleDateString()
}

// ── Modal de creación ───────────────────────────────────────────────────────────

function CrearModal({
  onClose, onCreada, error, setError,
}: {
  onClose: () => void
  onCreada: (pl: PlanificacionInfo) => void | Promise<void>
  error: string
  setError: (s: string) => void
}) {
  const [nombre, setNombre] = useState('')
  const [maestro, setMaestro] = useState<File | null>(null)
  const [salas, setSalas] = useState<File | null>(null)
  const [creando, setCreando] = useState(false)

  async function crear() {
    if (!nombre.trim() || !maestro) {
      setError('Nombre y archivo Maestro son obligatorios.'); return
    }
    setCreando(true); setError('')
    try {
      const pl = await crearPlanificacion(nombre.trim(), maestro, salas)
      await onCreada(pl)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al crear')
      setCreando(false)
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-md p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-900">Nueva planificación</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        {error && (
          <div className="mb-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
            {error}
          </div>
        )}

        <div className="space-y-3">
          <input
            type="text" placeholder="Nombre (ej. Horario 2025-2)" autoFocus
            value={nombre} onChange={e => setNombre(e.target.value)}
            className="w-full text-sm border border-gray-300 rounded px-3 py-2 outline-none focus:border-gray-500"
          />
          <FileInput label="Maestro (.xlsx) — requerido" file={maestro} onChange={setMaestro} />
          <FileInput label="Salas especiales (.xlsx) — opcional" file={salas} onChange={setSalas} />
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="text-xs font-medium text-gray-500 hover:text-gray-700 px-3 py-2">
            Cancelar
          </button>
          <button
            onClick={crear} disabled={creando}
            className="flex items-center gap-2 text-xs font-medium bg-[#B71C1C] text-white
                       hover:bg-red-800 disabled:opacity-60 px-4 py-2 rounded transition-colors"
          >
            {creando ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
            Crear y abrir
          </button>
        </div>
      </div>
    </div>
  )
}

function FileInput({
  label, file, onChange,
}: {
  label: string
  file: File | null
  onChange: (f: File | null) => void
}) {
  return (
    <label className="flex items-center gap-2 text-xs border border-gray-300 rounded px-3 py-2.5
                      cursor-pointer hover:border-gray-400 text-gray-600 truncate">
      <Upload size={13} className="shrink-0 text-gray-400" />
      <span className="truncate">{file ? file.name : label}</span>
      <input type="file" accept=".xlsx" className="hidden"
             onChange={e => onChange(e.target.files?.[0] ?? null)} />
    </label>
  )
}
