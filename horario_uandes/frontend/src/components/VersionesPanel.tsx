import { useState, useEffect, useCallback } from 'react'
import { Save, Trash2, Check, Clock, Loader2 } from 'lucide-react'
import type { VersionInfo } from '../types'
import { listarVersiones, guardarVersion, cargarVersion, eliminarVersion } from '../api/client'

interface Props {
  planificacionId: number
  /** Tras cargar una versión, refrescar el horario en el padre. */
  onRestaurado: () => void | Promise<void>
}

export default function VersionesPanel({ planificacionId, onRestaurado }: Props) {
  const [versiones, setVersiones] = useState<VersionInfo[]>([])
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState('')

  const refrescar = useCallback(async () => {
    setVersiones(await listarVersiones(planificacionId))
  }, [planificacionId])

  useEffect(() => { refrescar() }, [refrescar])

  async function guardar() {
    const n = versiones.filter(v => !v.es_autosave).length + 1
    const nombre = prompt('Nombre de la versión:', `Versión ${n}`)
    if (!nombre) return
    try {
      await guardarVersion(planificacionId, nombre)
      await refrescar()
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

  async function borrar(vid: number) {
    if (!confirm('¿Eliminar esta versión?')) return
    await eliminarVersion(vid)
    await refrescar()
  }

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Versiones</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Guarda el horario actual como una versión para volver a ella más tarde.
          </p>
        </div>
        <button
          onClick={guardar}
          className="flex items-center gap-2 text-xs font-medium bg-green-600 text-white
                     hover:bg-green-700 px-3 py-2 rounded transition-colors shrink-0"
        >
          <Save size={13} /> Guardar versión actual
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
          {error}
        </div>
      )}

      {versiones.length === 0 ? (
        <p className="text-sm text-gray-400">Sin versiones guardadas todavía.</p>
      ) : (
        <ul className="border border-gray-200 rounded-lg divide-y divide-gray-100 bg-white">
          {versiones.map(v => (
            <li key={v.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <span className="flex items-center gap-2 min-w-0">
                {v.es_autosave
                  ? <Clock size={14} className="text-gray-400 shrink-0" />
                  : <Check size={14} className="text-green-600 shrink-0" />}
                <span className="min-w-0">
                  <span className="text-sm text-gray-800 truncate block">
                    {v.nombre}
                    {v.es_autosave && <span className="text-[10px] text-gray-400 ml-1">(automático)</span>}
                  </span>
                  <span className="text-[11px] text-gray-400">
                    {new Date(v.creada + (v.creada.endsWith('Z') ? '' : 'Z')).toLocaleString()}
                  </span>
                </span>
              </span>
              <span className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => cargar(v.id)} disabled={cargando}
                  className="flex items-center gap-1 text-[11px] font-medium text-blue-700
                             hover:bg-blue-50 px-2.5 py-1 rounded disabled:opacity-60"
                >
                  {cargando ? <Loader2 size={12} className="animate-spin" /> : null} Cargar
                </button>
                {!v.es_autosave && (
                  <button onClick={() => borrar(v.id)} className="text-gray-400 hover:text-red-600 p-1">
                    <Trash2 size={13} />
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
