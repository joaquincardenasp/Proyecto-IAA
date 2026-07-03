import { AlertOctagon, AlertTriangle, Lightbulb, User, Clock, Layers } from 'lucide-react'
import type { DiagnosticoResult, DiagnosticoUnidad, Sugerencia, EstadoSolve } from '../types'

// ── Etiquetas de causa ─────────────────────────────────────────────────────────

const CAUSA_LABEL: Record<string, string> = {
  sin_bloques: 'Sin bloques disponibles',
  dias_insuficientes: 'Disponibilidad insuficiente',
  '2mas1_sin_par': 'Distribución 2+1 sin horario válido',
  RD2: 'Disponibilidad de profesores',
  RD3: 'Profesor asignado en conflicto',
  RD4: 'Capacidad de salas especiales',
  contencion: 'Recursos compartidos entre semestres',
  combinacion: 'Combinación de restricciones',
}

function causaLabel(c: string): string {
  return CAUSA_LABEL[c] ?? c
}

// ── Props ───────────────────────────────────────────────────────────────────────

interface Props {
  diagnostico: DiagnosticoResult
  estado: EstadoSolve
  nColocadas: number
}

// ── Componente ──────────────────────────────────────────────────────────────────

export default function DiagnosticoPanel({ diagnostico, estado, nColocadas }: Props) {
  const unidades = diagnostico.unidades

  return (
    <div className="space-y-6">
      {/* ── Banner de contexto ──────────────────────────────────────────────── */}
      <div
        className={`rounded-lg border p-5 ${
          estado === 'INFEASIBLE'
            ? 'bg-red-50 border-red-200'
            : 'bg-amber-50 border-amber-200'
        }`}
      >
        <div className="flex items-start gap-3">
          {estado === 'INFEASIBLE' ? (
            <AlertOctagon size={20} className="text-red-600 shrink-0 mt-0.5" />
          ) : (
            <AlertTriangle size={20} className="text-amber-600 shrink-0 mt-0.5" />
          )}
          <div>
            <h2
              className={`text-sm font-semibold ${
                estado === 'INFEASIBLE' ? 'text-red-800' : 'text-amber-800'
              }`}
            >
              {estado === 'INFEASIBLE'
                ? 'No fue posible generar un horario'
                : 'Horario parcial: quedaron conflictos por resolver'}
            </h2>
            <p
              className={`text-xs mt-1 leading-relaxed ${
                estado === 'INFEASIBLE' ? 'text-red-700' : 'text-amber-700'
              }`}
            >
              {estado === 'INFEASIBLE' ? (
                <>
                  El sistema no relaja restricciones automáticamente. A continuación se explica
                  qué lo impide y qué acciones puedes tomar para desbloquearlo.
                </>
              ) : (
                <>
                  Se generaron <strong>{nColocadas}</strong> secciones respetando todas las
                  restricciones. Las siguientes unidades no se pudieron ubicar; abajo está el
                  motivo y las acciones sugeridas para cada una.
                </>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* ── Unidades bloqueadas ─────────────────────────────────────────────── */}
      {unidades.length === 0 ? (
        <p className="text-sm text-gray-500">No hay conflictos que diagnosticar.</p>
      ) : (
        <div className="space-y-4">
          {unidades.map((u, i) => (
            <UnidadCard key={i} unidad={u} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Tarjeta por unidad bloqueada ────────────────────────────────────────────────

function UnidadCard({ unidad }: { unidad: DiagnosticoUnidad }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      {/* Cabecera de la unidad */}
      <div className="flex items-center gap-2 px-5 py-3 border-b border-gray-100 bg-gray-50">
        <Layers size={15} className="text-gray-500 shrink-0" />
        <span className="text-sm font-semibold text-gray-800">
          {unidad.carrera} · Semestre {unidad.semestre}
        </span>
        <span className="ml-auto text-[10px] font-bold uppercase tracking-wide
                         bg-gray-200 text-gray-600 px-2 py-0.5 rounded">
          {causaLabel(unidad.causa_principal)}
        </span>
      </div>

      {/* Sugerencias */}
      <div className="divide-y divide-gray-100">
        {unidad.sugerencias.map((s, i) => (
          <SugerenciaBlock key={i} sug={s} />
        ))}
      </div>
    </div>
  )
}

// ── Bloque de una sugerencia ────────────────────────────────────────────────────

function SugerenciaBlock({ sug }: { sug: Sugerencia }) {
  const alta = sug.severidad === 'alta'
  return (
    <div className="px-5 py-4">
      {/* Mensaje / explicación */}
      <div className="flex items-start gap-2.5">
        <span
          className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${
            alta ? 'bg-red-500' : 'bg-amber-500'
          }`}
        />
        <p className="text-sm text-gray-800 leading-relaxed">{sug.mensaje}</p>
      </div>

      {/* Chips: profesores y bloques */}
      {(sug.profesores.length > 0 || sug.bloques.length > 0) && (
        <div className="flex flex-wrap gap-1.5 mt-2.5 ml-4">
          {sug.profesores.map((p, i) => (
            <span
              key={`p${i}`}
              className="inline-flex items-center gap-1 text-[11px] bg-gray-100
                         text-gray-600 px-2 py-0.5 rounded"
            >
              <User size={11} /> {p}
            </span>
          ))}
          {sug.bloques.map((b, i) => (
            <span
              key={`b${i}`}
              className="inline-flex items-center gap-1 text-[11px] bg-gray-100
                         text-gray-600 px-2 py-0.5 rounded"
            >
              <Clock size={11} /> {b}
            </span>
          ))}
        </div>
      )}

      {/* Acciones sugeridas */}
      {sug.acciones.length > 0 && (
        <div className="mt-3 ml-4 bg-blue-50 border border-blue-100 rounded-md p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <Lightbulb size={13} className="text-blue-600" />
            <span className="text-[11px] font-semibold text-blue-800 uppercase tracking-wide">
              Acciones sugeridas
            </span>
          </div>
          <ul className="space-y-1.5">
            {sug.acciones.map((a, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-gray-700 leading-relaxed">
                <span className="text-blue-400 mt-0.5 shrink-0">→</span>
                <span>{a}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}