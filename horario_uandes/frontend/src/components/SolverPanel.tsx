import { useState, useRef } from 'react'
import { AlertCircle, CheckCircle2, FileSpreadsheet, Loader2, UploadCloud } from 'lucide-react'
import { uploadFiles, postSolve } from '../api/client'
import type { StatusResponse } from '../types'

// ── Archivos esperados ────────────────────────────────────────────────────────

const EXPECTED: { name: string; label: string; required: boolean; hint?: string }[] = [
  {
    name:     'Maestro_XXXXXX.xlsx',
    label:    'Maestro de secciones',
    required: true,
    hint:     'El nombre debe comenzar con "Maestro". Contiene hojas MAESTRO y PROFESORES.',
  },
  {
    name:     'SALAS_ESPECIALES_ING.xlsx',
    label:    'Salas especiales de Ingeniería',
    required: false,
    hint:     'Contiene hojas BBDD y SALAS ESPECIALES.',
  },
]

// ── Componente ────────────────────────────────────────────────────────────────

interface Props {
  status: StatusResponse
  onSolveStarted: () => void
}

export default function SolverPanel({ status, onSolveStarted }: Props) {
  const [uploaded, setUploaded]     = useState<Set<string>>(new Set())
  const [uploading, setUploading]   = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [solveError, setSolveError]   = useState('')
  const [isDragOver, setIsDragOver]   = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const isRunning = status.status === 'running'

  // ── Upload ──────────────────────────────────────────────────────────────────

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    const xlsx = Array.from(files).filter(f => f.name.endsWith('.xlsx'))
    if (xlsx.length === 0) {
      setUploadError('Solo se aceptan archivos .xlsx')
      return
    }
    setUploading(true)
    setUploadError('')
    try {
      const res = await uploadFiles(xlsx)
      setUploaded(prev => new Set([...prev, ...res.uploaded]))
    } catch (e) {
      setUploadError(String(e))
    } finally {
      setUploading(false)
    }
  }

  // ── Solve ───────────────────────────────────────────────────────────────────

  async function handleSolve() {
    setSolveError('')
    try {
      await postSolve()
      onSolveStarted()
    } catch (e) {
      setSolveError(String(e))
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-xl mx-auto space-y-8">

      {/* ── Sección: Archivos ─────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-800 mb-0.5 uppercase tracking-wide">
          Archivos de entrada
        </h2>
        <p className="text-sm text-gray-500 mb-5">
          Sube el Maestro del semestre y, opcionalmente, el archivo de salas especiales.
          Si ya están en el servidor puedes omitir este paso y generar directamente.
        </p>

        {/* Zona de arrastre */}
        <div
          onDrop={e => {
            e.preventDefault()
            setIsDragOver(false)
            handleFiles(e.dataTransfer.files)
          }}
          onDragOver={e => { e.preventDefault(); setIsDragOver(true) }}
          onDragLeave={() => setIsDragOver(false)}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-10 text-center cursor-pointer
                      transition-colors select-none
                      ${isDragOver
                        ? 'border-[#B71C1C] bg-[#FEF2F2]'
                        : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
                      }`}
        >
          {uploading ? (
            <Loader2
              size={28}
              className="mx-auto mb-3 text-[#B71C1C] animate-spin"
            />
          ) : (
            <UploadCloud
              size={28}
              className={`mx-auto mb-3 transition-colors
                ${isDragOver ? 'text-[#B71C1C]' : 'text-gray-400'}`}
            />
          )}
          <p className="text-sm font-medium text-gray-700">
            {uploading ? 'Subiendo archivos…' : 'Arrastra los archivos aquí'}
          </p>
          <p className="text-xs text-gray-400 mt-1">
            o haz clic para seleccionar desde el explorador
          </p>
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx"
            multiple
            className="hidden"
            onChange={e => handleFiles(e.target.files)}
          />
        </div>

        {uploadError && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-red-600">
            <AlertCircle size={12} />
            {uploadError}
          </p>
        )}

        {/* Lista de archivos esperados */}
        <div className="mt-4 border border-gray-200 rounded-lg overflow-hidden divide-y divide-gray-100">
          {EXPECTED.map(f => {
            // El Maestro puede tener nombre variable (Maestro_202510.xlsx, etc.)
            // así que hacemos matching por prefijo
            const prefix = f.name.replace('XXXXXX.xlsx', '').toLowerCase()
            const isUploaded = prefix
              ? [...uploaded].some(n => n.toLowerCase().startsWith(prefix))
              : uploaded.has(f.name)
            return (
              <div key={f.name} className="flex items-start gap-3 px-4 py-3 bg-white">
                <FileSpreadsheet size={14} className="text-gray-300 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className={`text-xs leading-tight
                    ${isUploaded ? 'text-gray-900 font-medium' : 'text-gray-600'}`}>
                    {f.label}
                  </p>
                  <p className="text-[10px] text-gray-400 mt-0.5">{f.name}</p>
                  {f.hint && (
                    <p className="text-[10px] text-gray-400 mt-0.5 leading-relaxed">
                      {f.hint}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0 mt-0.5">
                  {f.required
                    ? <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wide">
                        requerido
                      </span>
                    : <span className="text-[10px] text-gray-300 uppercase tracking-wide">
                        opcional
                      </span>
                  }
                  {isUploaded && (
                    <CheckCircle2 size={15} className="text-green-600" />
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* ── Sección: Generar ──────────────────────────────────────────────── */}
      <section>
        {solveError && (
          <div className="mb-4 flex items-start gap-2 p-3 bg-red-50 border border-red-200
                          rounded-lg text-sm text-red-700">
            <AlertCircle size={14} className="shrink-0 mt-0.5" />
            <span>{solveError}</span>
          </div>
        )}

        <button
          onClick={handleSolve}
          disabled={isRunning}
          className={`w-full py-3 rounded-lg text-sm font-semibold tracking-wide
                      transition-colors
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
      </section>
    </div>
  )
}
