import { useMemo, useState } from 'react'
import { BookOpen, CalendarDays, CheckSquare, TrendingDown, ChevronDown, ChevronRight, AlertTriangle, AlertCircle } from 'lucide-react'
import type { MetricasResult, SeccionAsignada, TipoSeccion, Dia, ReporteDetallado, ViolacionItem } from '../types'

// ── Constantes ────────────────────────────────────────────────────────────────

const DIAS_LABEL: Record<Dia, string> = {
  L: 'Lunes', M: 'Martes', X: 'Miércoles', J: 'Jueves', V: 'Viernes',
}
const TIPO_LABEL: Record<TipoSeccion, string> = {
  CLAS: 'Cátedra',
  AYUD: 'Ayudantía',
  LABT: 'Lab / Taller',
}
const TIPO_BAR: Record<TipoSeccion, string> = {
  CLAS: 'bg-blue-700',
  AYUD: 'bg-emerald-600',
  LABT: 'bg-violet-600',
}

// ── Restricciones blandas optimizadas ────────────────────────────────────────

const RESTRICCIONES = [
  { id: 'RB1', label: 'Labs de Programación en bloques consecutivos',     peso: 100 },
  { id: 'RB2', label: 'Profesores de jornada sin bloques extremos',       peso: 80  },
  { id: 'RB5', label: 'Profesores sin ventanas (huecos) el mismo día',    peso: 60  },
  { id: 'RB3', label: 'Componentes del mismo curso en días distintos',    peso: 50  },
  { id: 'RB4', label: 'Máximo una sesión por tipo, curso y día',          peso: 50  },
]

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  metricas: MetricasResult
  secciones: SeccionAsignada[]
  reporte?: ReporteDetallado
}

// ── Componente ────────────────────────────────────────────────────────────────

export default function MetricasPanel({ metricas, secciones, reporte }: Props) {

  // Distribución por día
  const dayDist = useMemo(() => {
    const cnt: Record<string, number> = { L: 0, M: 0, X: 0, J: 0, V: 0 }
    for (const sec of secciones)
      for (const b of sec.bloques)
        cnt[b.dia] = (cnt[b.dia] ?? 0) + 1
    return cnt
  }, [secciones])

  const maxDay = Math.max(...Object.values(dayDist), 1)

  // Distribución por tipo
  const tipoDist = useMemo(() => {
    const cnt: Record<string, number> = { CLAS: 0, AYUD: 0, LABT: 0 }
    for (const sec of secciones)
      cnt[sec.tipo] = (cnt[sec.tipo] ?? 0) + 1
    return cnt
  }, [secciones])

  // Balance de distribución por día
  const avg    = metricas.n_bloques_totales / 5
  const devs   = (['L', 'M', 'X', 'J', 'V'] as Dia[]).map(d => Math.abs((dayDist[d] ?? 0) - avg))
  const cv     = avg > 0 ? (Math.max(...devs) / avg) * 100 : 0
  const balanced = cv < 20

  return (
    <div className="space-y-6">

      {/* ── Estadísticas principales ──────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          icon={<BookOpen size={16} className="text-gray-500" />}
          value={metricas.n_secciones}
          label="Secciones asignadas"
        />
        <StatCard
          icon={<CalendarDays size={16} className="text-gray-500" />}
          value={metricas.n_bloques_totales}
          label="Bloques totales"
        />
        <StatCard
          icon={<CheckSquare size={16} className="text-gray-500" />}
          value={metricas.estado_cpsat}
          label="Estado CP-SAT"
          highlight={metricas.estado_cpsat === 'OPTIMAL'}
        />
        <StatCard
          icon={<TrendingDown size={16} className="text-green-600" />}
          value={`${metricas.mejora_pct.toFixed(1)} %`}
          label="Mejora del algoritmo genético"
          highlight
        />
      </div>

      {/* ── Gráficos ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">

        {/* Distribución por día */}
        <div className="bg-white border border-gray-200 rounded-lg p-5">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">
            Distribución por día
          </h3>
          <div className="space-y-3">
            {(['L', 'M', 'X', 'J', 'V'] as Dia[]).map(dia => {
              const n = dayDist[dia] ?? 0
              const pct = (n / maxDay) * 100
              return (
                <div key={dia} className="flex items-center gap-3">
                  <span className="text-xs text-gray-500 w-20 shrink-0">
                    {DIAS_LABEL[dia]}
                  </span>
                  <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-700 rounded-full transition-all duration-300"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-400 w-6 text-right tabular-nums shrink-0">
                    {n}
                  </span>
                </div>
              )
            })}
          </div>
          {/* Indicador de balance */}
          <div
            className={`mt-4 flex items-center gap-2 text-xs px-3 py-2 rounded
              ${balanced
                ? 'bg-green-50 text-green-700'
                : 'bg-yellow-50 text-yellow-700'
              }`}
          >
            <span className="font-medium">
              {balanced ? 'Distribución balanceada' : 'Distribución desbalanceada'}
            </span>
            <span className="text-gray-400 ml-auto tabular-nums">
              desv. máx. {cv.toFixed(0)} %
            </span>
          </div>
        </div>

        {/* Distribución por tipo de componente */}
        <div className="bg-white border border-gray-200 rounded-lg p-5">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">
            Secciones por componente
          </h3>
          <div className="space-y-3">
            {(['CLAS', 'AYUD', 'LABT'] as TipoSeccion[]).map(tipo => {
              const n   = tipoDist[tipo] ?? 0
              const pct = metricas.n_secciones > 0
                ? (n / metricas.n_secciones) * 100
                : 0
              return (
                <div key={tipo} className="flex items-center gap-3">
                  <span className="text-xs text-gray-500 w-24 shrink-0">
                    {TIPO_LABEL[tipo]}
                  </span>
                  <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${TIPO_BAR[tipo]}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-400 w-16 text-right tabular-nums shrink-0">
                    {n} ({pct.toFixed(0)} %)
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* ── Comparativa de fitness ────────────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">
          Penalización — CP-SAT vs. Algoritmo Genético
        </h3>
        <div className="flex items-center gap-6">
          <div className="text-center">
            <p className="text-2xl font-bold text-gray-800 tabular-nums">
              {metricas.fitness_cpsat.toFixed(0)}
            </p>
            <p className="text-xs text-gray-400 mt-0.5">CP-SAT inicial</p>
          </div>
          <div className="flex-1 flex flex-col items-center gap-1">
            <div className="w-full h-px bg-gray-200 relative">
              <div
                className="absolute top-0 left-0 h-px bg-green-500 transition-all"
                style={{ width: `${metricas.mejora_pct}%` }}
              />
            </div>
            <span className="text-xs font-semibold text-green-600">
              − {metricas.mejora_pct.toFixed(1)} % penalización
            </span>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold text-green-700 tabular-nums">
              {metricas.fitness_ga.toFixed(0)}
            </p>
            <p className="text-xs text-gray-400 mt-0.5">Tras optimización GA</p>
          </div>
        </div>
      </div>

      {/* ── Restricciones blandas ─────────────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-4">
          Restricciones blandas optimizadas
        </h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-left pb-2 text-xs text-gray-400 font-medium w-12">ID</th>
              <th className="text-left pb-2 text-xs text-gray-400 font-medium">Descripción</th>
              <th className="text-right pb-2 text-xs text-gray-400 font-medium w-16">Peso</th>
              {reporte && (
                <th className="text-right pb-2 text-xs text-gray-400 font-medium w-24">
                  Penalización
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {RESTRICCIONES.map(rb => {
              const pen = reporte?.resumen.penalizacion_por_rb[rb.id] ?? null
              return (
                <tr key={rb.id}>
                  <td className="py-2 pr-4">
                    <span className="text-[10px] font-bold bg-gray-100 text-gray-600
                                     px-1.5 py-0.5 rounded">
                      {rb.id}
                    </span>
                  </td>
                  <td className="py-2 pr-4 text-gray-700 text-xs">{rb.label}</td>
                  <td className="py-2 text-right text-gray-400 text-xs tabular-nums">
                    {rb.peso}
                  </td>
                  {reporte && (
                    <td className={`py-2 text-right text-xs tabular-nums font-medium
                      ${pen ? 'text-amber-700' : 'text-green-600'}`}>
                      {pen ? pen.toFixed(0) : '✓ 0'}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* ── Reporte de violaciones ────────────────────────────────────────── */}
      {reporte && (
        <ReporteViolaciones reporte={reporte} />
      )}

    </div>
  )
}

// ── Sub-componentes ───────────────────────────────────────────────────────────

function StatCard({
  icon, value, label, highlight = false,
}: {
  icon: React.ReactNode
  value: string | number
  label: string
  highlight?: boolean
}) {
  return (
    <div className={`bg-white border rounded-lg p-4
      ${highlight ? 'border-t-2 border-t-blue-700 border-gray-200' : 'border-gray-200'}`}>
      <div className="flex items-center gap-2 mb-2">
        {icon}
      </div>
      <div className="text-xl font-bold text-gray-900 tabular-nums leading-tight">
        {value}
      </div>
      <div className="text-xs text-gray-400 mt-1 leading-tight">{label}</div>
    </div>
  )
}

// ── Reporte de violaciones ────────────────────────────────────────────────────

type Filtro = 'todas' | 'duras' | 'blandas'

function ReporteViolaciones({ reporte }: { reporte: ReporteDetallado }) {
  const [filtro, setFiltro] = useState<Filtro>('todas')
  const { resumen, violaciones_duras, violaciones_blandas } = reporte

  // Agrupar por tipo
  const agrupar = (viols: ViolacionItem[]) => {
    const map = new Map<string, ViolacionItem[]>()
    for (const v of viols) {
      if (!map.has(v.tipo)) map.set(v.tipo, [])
      map.get(v.tipo)!.push(v)
    }
    return map
  }
  const gruposDuras   = agrupar(violaciones_duras)
  const gruposBlandas = agrupar(violaciones_blandas)

  const totalDuras   = resumen.total_duras
  const totalBlandas = resumen.total_blandas

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Detalle de restricciones
        </h3>
        <div className="flex gap-1">
          {(['todas', 'duras', 'blandas'] as Filtro[]).map(f => (
            <button
              key={f}
              onClick={() => setFiltro(f)}
              className={`text-[11px] px-2.5 py-1 rounded font-medium transition-colors
                ${filtro === f
                  ? 'bg-gray-800 text-white'
                  : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
            >
              {f === 'todas' ? 'Todas' : f === 'duras' ? 'Duras' : 'Blandas'}
            </button>
          ))}
        </div>
      </div>

      {/* Resumen rápido */}
      <div className="flex gap-3">
        <div className={`flex items-center gap-2 px-3 py-2 rounded text-xs font-medium
          ${totalDuras === 0
            ? 'bg-green-50 text-green-700 border border-green-200'
            : 'bg-red-50 text-red-700 border border-red-200'
          }`}>
          <AlertCircle size={13} />
          <span>{totalDuras} violación{totalDuras !== 1 ? 'es' : ''} dura{totalDuras !== 1 ? 's' : ''}</span>
        </div>
        <div className={`flex items-center gap-2 px-3 py-2 rounded text-xs font-medium
          ${totalBlandas === 0
            ? 'bg-green-50 text-green-700 border border-green-200'
            : 'bg-amber-50 text-amber-700 border border-amber-200'
          }`}>
          <AlertTriangle size={13} />
          <span>{totalBlandas} violación{totalBlandas !== 1 ? 'es' : ''} blanda{totalBlandas !== 1 ? 's' : ''}</span>
        </div>
      </div>

      {/* Grupos de violaciones duras */}
      {filtro !== 'blandas' && (
        <div className="space-y-2">
          {totalDuras === 0 ? (
            <p className="text-xs text-green-600 font-medium px-1">
              No se detectaron violaciones de restricciones duras.
            </p>
          ) : (
            Array.from(gruposDuras.entries()).map(([tipo, viols]) => (
              <GrupoViolaciones key={tipo} tipo={tipo} viols={viols} esDura />
            ))
          )}
        </div>
      )}

      {/* Grupos de violaciones blandas */}
      {filtro !== 'duras' && (
        <div className="space-y-2">
          {totalBlandas === 0 ? (
            <p className="text-xs text-green-600 font-medium px-1">
              No se detectaron violaciones de restricciones blandas.
            </p>
          ) : (
            Array.from(gruposBlandas.entries()).map(([tipo, viols]) => (
              <GrupoViolaciones key={tipo} tipo={tipo} viols={viols} esDura={false} />
            ))
          )}
        </div>
      )}
    </div>
  )
}

const TIPO_LABEL_RD: Record<string, string> = {
  RD1: 'Topes de malla',
  RD3: 'Conflictos de profesor',
  RD4: 'Conflictos de sala especial',
}
const TIPO_LABEL_RB: Record<string, string> = {
  RB1: 'Labs Programación no consecutivos',
  RB2: 'Profesores jornada en horarios extremos',
  RB3: 'Componentes del mismo curso en mismo día',
  RB4: 'Múltiples bloques del componente en un día',
  RB5: 'Ventana (hueco) en horario del profesor',
}

function GrupoViolaciones({
  tipo, viols, esDura,
}: {
  tipo: string
  viols: ViolacionItem[]
  esDura: boolean
}) {
  const [abierto, setAbierto] = useState(esDura)  // duras abiertas por defecto
  const label = esDura
    ? (TIPO_LABEL_RD[tipo] ?? tipo)
    : (TIPO_LABEL_RB[tipo] ?? tipo)

  const headerCls = esDura
    ? 'bg-red-50 border-red-200 text-red-800 hover:bg-red-100'
    : 'bg-amber-50 border-amber-200 text-amber-800 hover:bg-amber-100'
  const badgeCls = esDura
    ? 'bg-red-200 text-red-800'
    : 'bg-amber-200 text-amber-800'

  return (
    <div className={`border rounded-lg overflow-hidden ${esDura ? 'border-red-200' : 'border-amber-200'}`}>
      <button
        onClick={() => setAbierto(!abierto)}
        className={`w-full flex items-center justify-between px-3 py-2.5 text-left
          transition-colors ${headerCls}`}
      >
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${badgeCls}`}>
            {tipo}
          </span>
          <span className="text-xs font-medium">{label}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${badgeCls}`}>
            {viols.length}
          </span>
          {abierto
            ? <ChevronDown size={13} className="shrink-0" />
            : <ChevronRight size={13} className="shrink-0" />
          }
        </div>
      </button>

      {abierto && (
        <ul className="divide-y divide-gray-100">
          {viols.map((v, idx) => (
            <li key={idx} className="px-3 py-2.5 bg-white">
              <p className="text-xs text-gray-800 leading-relaxed">{v.mensaje}</p>
              {v.contexto && (
                <p className="text-[11px] text-gray-400 mt-1">{v.contexto}</p>
              )}
              {v.penalizacion != null && (
                <span className="inline-block mt-1 text-[10px] font-medium
                                 bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">
                  −{v.penalizacion.toFixed(0)} pts
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
