import { useState, useEffect, useCallback } from 'react'
import {
  FolderOpen, Plus, Save, Trash2, Check, Loader2, Clock, Upload,
} from 'lucide-react'
import type { PlanificacionInfo, VersionInfo } from '../types'
import {
  crearPlanificacion, listarPlanificaciones, activarPlanificacion, eliminarPlanificacion,
  guardarVersion, listarVersiones, cargarVersion, eliminarVersion,
} from '../api/client'

const LS_KEY = 'planificacionActiva'

interface Props {
  /** Se llama tras activar/crear/cargar para que el padre refresque estado y resultados. */
  onRestaurado: () => void | Promise<void>
  /** Reporta al padre cuál planificación está activa (o null). */
  onActivaChange: (pl: PlanificacionInfo | null) => void
}

export default function PlanificacionesPanel({ onRestaurado, onActivaChange }: Props) {
  const [pls, setPls] = useState<PlanificacionInfo[]>([])
  const [versiones, setVersiones] = useState<VersionInfo[]>([])
  const [activaId, setActivaId] = useState<number | null>(
    () => { const v = localStorage.getItem(LS_KEY); return v ? Number(v) : null },
  )
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState('')

  // Formulario nueva planificación
  const [nuevoNombre, setNuevoNombre] = useState('')
  const [maestro, setMaestro] = useState<File | null>(null)
  const [salas, setSalas] = useState<File | null>(null)
  const [creando, setCreando] = useState(false)

  const refrescarVersiones = useCallback(async (id: number | null) => {
    setVersiones(id ? await listarVersiones(id) : [])
  }, [])

  const refrescarPls = useCallback(async () => {
    setPls(await listarPlanificaciones())
  }, [])

  // Al montar: cargar lista y re-activar la planificación guardada (sobrevive recarga).
  useEffect(() => {
    (async () => {
      await refrescarPls()
      const id = localStorage.getItem(LS_KEY)
      if (id) {
        try {
          await activarPlanificacion(Number(id))
          await refrescarVersiones(Number(id))
          await onRestaurado()
        } catch { /* la planificación pudo eliminarse */ }
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function setActiva(id: number | null) {
    setActivaId(id)
    if (id) localStorage.setItem(LS_KEY, String(id))
    else localStorage.removeItem(LS_KEY)
  }

  // Reportar al padre la planificación activa (para gatear "Generar horario").
  useEffect(() => {
    onActivaChange(pls.find(p => p.id === activaId) ?? null)
  }, [pls, activaId, onActivaChange])

  async function activar(id: number) {
    setCargando(true); setError('')
    try {
      await activarPlanificacion(id)
      setActiva(id)
      await refrescarPls()
      await refrescarVersiones(id)
      await onRestaurado()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al activar')
    } finally { setCargando(false) }
  }

  async function crear() {
    if (!nuevoNombre.trim() || !maestro) {
      setError('Nombre y archivo Maestro son obligatorios.'); return
    }
    setCreando(true); setError('')
    try {
      const pl = await crearPlanificacion(nuevoNombre.trim(), maestro, salas)
      setActiva(pl.id)
      setNuevoNombre(''); setMaestro(null); setSalas(null)
      await refrescarPls()
      await refrescarVersiones(pl.id)
      await onRestaurado()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al crear')
    } finally { setCreando(false) }
  }

  async function borrarPl(id: number) {
    if (!confirm('¿Eliminar la planificación y todas sus versiones? No se puede deshacer.')) return
    await eliminarPlanificacion(id)
    if (activaId === id) setActiva(null)
    await refrescarPls()
    if (activaId === id) setVersiones([])
  }

  async function guardar() {
    if (!activaId) return
    const nombre = prompt('Nombre de la versión:', `Versión ${versiones.filter(v => !v.es_autosave).length + 1}`)
    if (!nombre) return
    try {
      await guardarVersion(activaId, nombre)
      await refrescarVersiones(activaId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al guardar la versión')
    }
  }

  async function cargar(vid: number) {
    setCargando(true); setError('')
    try {
      await cargarVersion(vid)
      await onRestaurado()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cargar la versión')
    } finally { setCargando(false) }
  }

  async function borrarVersion(vid: number) {
    await eliminarVersion(vid)
    if (activaId) await refrescarVersiones(activaId)
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
          {error}
        </div>
      )}

      {/* ── Nueva planificación ─────────────────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h3 className="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
          <Plus size={15} /> Nueva planificación
        </h3>
        <div className="grid gap-3 md:grid-cols-3">
          <input
            type="text" placeholder="Nombre (ej. Horario 2025-2)"
            value={nuevoNombre} onChange={e => setNuevoNombre(e.target.value)}
            className="text-sm border border-gray-300 rounded px-3 py-2 outline-none focus:border-gray-500"
          />
          <FileInput label="Maestro (.xlsx)" file={maestro} onChange={setMaestro} />
          <FileInput label="Salas especiales (.xlsx)" file={salas} onChange={setSalas} />
        </div>
        <button
          onClick={crear} disabled={creando}
          className="mt-3 flex items-center gap-2 text-xs font-medium bg-[#B71C1C] text-white
                     hover:bg-red-800 disabled:opacity-60 px-3 py-2 rounded transition-colors"
        >
          {creando ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          Crear y activar
        </button>
      </div>

      {/* ── Lista de planificaciones ────────────────────────────────────────── */}
      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Planificaciones ({pls.length})
        </h3>
        {pls.length === 0 ? (
          <p className="text-sm text-gray-400">Aún no hay planificaciones. Crea una arriba.</p>
        ) : (
          <div className="space-y-2">
            {pls.map(pl => (
              <div
                key={pl.id}
                className={`bg-white border rounded-lg p-4 ${
                  activaId === pl.id ? 'border-[#B71C1C] border-l-4' : 'border-gray-200'
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <FolderOpen size={15} className="text-gray-400 shrink-0" />
                      <span className="text-sm font-semibold text-gray-800 truncate">{pl.nombre}</span>
                      {activaId === pl.id && (
                        <span className="text-[10px] font-bold bg-red-100 text-red-700 px-1.5 py-0.5 rounded">
                          ACTIVA
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-gray-400 mt-0.5">
                      {pl.maestro_nombre} · {pl.n_versiones} versión{pl.n_versiones !== 1 ? 'es' : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {activaId !== pl.id && (
                      <button
                        onClick={() => activar(pl.id)} disabled={cargando}
                        className="text-xs font-medium text-[#B71C1C] hover:bg-red-50 px-2.5 py-1.5 rounded"
                      >
                        Activar
                      </button>
                    )}
                    <button onClick={() => borrarPl(pl.id)} className="text-gray-400 hover:text-red-600 p-1">
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                {/* Versiones de la planificación activa */}
                {activaId === pl.id && (
                  <div className="mt-3 pt-3 border-t border-gray-100">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                        Versiones
                      </span>
                      <button
                        onClick={guardar}
                        className="flex items-center gap-1 text-[11px] font-medium text-green-700 hover:bg-green-50 px-2 py-1 rounded"
                      >
                        <Save size={12} /> Guardar versión actual
                      </button>
                    </div>
                    {versiones.length === 0 ? (
                      <p className="text-[11px] text-gray-400">Sin versiones guardadas todavía.</p>
                    ) : (
                      <ul className="space-y-1">
                        {versiones.map(v => (
                          <li key={v.id} className="flex items-center justify-between gap-2 text-xs">
                            <span className="flex items-center gap-1.5 min-w-0">
                              {v.es_autosave
                                ? <Clock size={12} className="text-gray-400 shrink-0" />
                                : <Check size={12} className="text-green-600 shrink-0" />}
                              <span className="truncate text-gray-700">{v.nombre}</span>
                              <span className="text-[10px] text-gray-400 shrink-0">
                                {new Date(v.creada).toLocaleString()}
                              </span>
                            </span>
                            <span className="flex items-center gap-1 shrink-0">
                              <button
                                onClick={() => cargar(v.id)} disabled={cargando}
                                className="text-[11px] font-medium text-blue-700 hover:bg-blue-50 px-2 py-0.5 rounded"
                              >
                                Cargar
                              </button>
                              {!v.es_autosave && (
                                <button onClick={() => borrarVersion(v.id)} className="text-gray-400 hover:text-red-600 p-0.5">
                                  <Trash2 size={12} />
                                </button>
                              )}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
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
    <label className="flex items-center gap-2 text-xs border border-gray-300 rounded px-3 py-2
                      cursor-pointer hover:border-gray-400 text-gray-600 truncate">
      <Upload size={13} className="shrink-0 text-gray-400" />
      <span className="truncate">{file ? file.name : label}</span>
      <input
        type="file" accept=".xlsx" className="hidden"
        onChange={e => onChange(e.target.files?.[0] ?? null)}
      />
    </label>
  )
}
