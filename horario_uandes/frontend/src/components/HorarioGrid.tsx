import { useState, useMemo } from 'react'
import { Search, X } from 'lucide-react'
import type { SeccionAsignada, TipoSeccion, Dia } from '../types'

// ── Constantes ────────────────────────────────────────────────────────────────

const DIAS: { key: Dia; label: string }[] = [
  { key: 'L', label: 'Lunes' },
  { key: 'M', label: 'Martes' },
  { key: 'X', label: 'Miércoles' },
  { key: 'J', label: 'Jueves' },
  { key: 'V', label: 'Viernes' },
]

const DIAS_LABEL: Record<Dia, string> = {
  L: 'Lunes', M: 'Martes', X: 'Miércoles', J: 'Jueves', V: 'Viernes',
}

// Sub-bloques de 50 minutos (estilo BANNER). Cada fila de la grilla es uno de estos.
// `min` = minuto de inicio (para mapear los bloques de los cursos a filas).
const SUB_BLOQUES: { inicio: string; fin: string; min: number }[] = [
  { inicio: '08:30', fin: '09:20', min: 510 },
  { inicio: '09:30', fin: '10:20', min: 570 },
  { inicio: '10:30', fin: '11:20', min: 630 },
  { inicio: '11:30', fin: '12:20', min: 690 },
  { inicio: '12:30', fin: '13:20', min: 750 },
  { inicio: '13:30', fin: '14:20', min: 810 },
  { inicio: '14:30', fin: '15:20', min: 870 },
  { inicio: '15:30', fin: '16:20', min: 930 },
  { inicio: '16:30', fin: '17:20', min: 990 },
  { inicio: '17:30', fin: '18:20', min: 1050 },
  { inicio: '18:30', fin: '19:20', min: 1110 },
]
const SUB_MIN = SUB_BLOQUES.map(s => s.min)
const ROW_H = 46          // altura de cada fila (sub-bloque) en px
const HEADER_H = 36       // altura del encabezado (h-9)

function toMin(h: string): number {
  const [hh, mm] = h.split(':').map(Number)
  return hh * 60 + mm
}
/** Fila (índice de sub-bloque) en que inicia un bloque; -1 si no calza. */
function rowOf(horaInicio: string): number {
  return SUB_MIN.indexOf(toMin(horaInicio))
}
/** Cuántos sub-bloques de 50 min cubre un bloque (2h → 2, 3h → 3). */
function spanOf(horaInicio: string, horaFin: string): number {
  const a = toMin(horaInicio), b = toMin(horaFin)
  return SUB_MIN.filter(m => m >= a && m < b).length || 1
}

// Color coding por tipo: cátedra = negro, ayudantía = verde, lab/taller = morado.
const TIPO_CARD: Record<TipoSeccion, string> = {
  CLAS: 'bg-gray-50    border-l-[3px] border-gray-900   text-gray-900',
  AYUD: 'bg-green-50   border-l-[3px] border-green-600  text-green-950',
  LABT: 'bg-purple-50  border-l-[3px] border-purple-600 text-purple-950',
}
// Separador horizontal entre secciones paralelas
const TIPO_DIVIDER: Record<TipoSeccion, string> = {
  CLAS: 'border-gray-300',
  AYUD: 'border-green-200',
  LABT: 'border-purple-200',
}
const TIPO_TAG: Record<TipoSeccion, string> = {
  CLAS: 'bg-gray-200   text-gray-800',
  AYUD: 'bg-green-100  text-green-800',
  LABT: 'bg-purple-100 text-purple-800',
}
const TIPO_LABEL: Record<TipoSeccion, string> = {
  CLAS: 'Cátedra',
  AYUD: 'Ayudantía',
  LABT: 'Lab / Taller',
}
// Color del botón de filtro activo por tipo
const TIPO_BTN_ACTIVE: Record<TipoSeccion, string> = {
  CLAS: 'bg-gray-900   text-white',
  AYUD: 'bg-green-600  text-white',
  LABT: 'bg-purple-600 text-white',
}

const CARRERAS = ['Plan Común', 'ICI', 'IOC', 'ICE', 'ICC', 'ICA', 'ICQ']

// ── Helpers de semestre ───────────────────────────────────────────────────────

function getSemestresForCarrera(sec: SeccionAsignada, carrera: string): string[] {
  const cars = sec.carreras.split(' · ')
  const sems = sec.semestres.split(' · ')
  const idx  = cars.indexOf(carrera)
  if (idx === -1) return []
  return sems[idx]?.split('/').map(s => s.trim()).filter(Boolean) ?? []
}

function semSortKey(s: string): [number, string] {
  const digits = s.replace(/\D/g, '')
  return [digits ? parseInt(digits, 10) : 999, s]
}
function compareSems(a: string, b: string): number {
  const [na, sa] = semSortKey(a)
  const [nb, sb] = semSortKey(b)
  return na !== nb ? na - nb : sa.localeCompare(sb)
}

// ── Tipos ─────────────────────────────────────────────────────────────────────

interface Filters {
  carrera:  string
  semestre: string
  tipo:     TipoSeccion | ''
  texto:    string
}

// Una "ubicación" en la grilla: un curso en un día, desde startRow ocupando `span`
// filas. `sections` agrupa las secciones paralelas del mismo curso (mismo bloque).
// `lane`/`lanes` posicionan lado a lado las ubicaciones que se solapan en el tiempo.
interface Placement {
  key:      string
  sections: SeccionAsignada[]
  startRow: number
  span:     number
  lane:     number
  lanes:    number
}

// ── Construcción de ubicaciones por día ─────────────────────────────────────────

function aplicarFiltros(secciones: SeccionAsignada[], filters: Filters): SeccionAsignada[] {
  const q = filters.texto.toLowerCase()
  return secciones.filter(sec => {
    if (filters.tipo && sec.tipo !== filters.tipo) return false
    if (filters.carrera && !sec.carreras.includes(filters.carrera)) return false
    if (filters.carrera && filters.semestre) {
      const sems = getSemestresForCarrera(sec, filters.carrera)
      if (!sems.includes(filters.semestre)) return false
    }
    if (q && ![sec.codigo, sec.titulo, sec.profesor, sec.seccion]
        .join(' ').toLowerCase().includes(q)) return false
    return true
  })
}

// Asigna carriles (columnas lado a lado) a ubicaciones que se solapan en filas.
// Las que no se solapan con nadie quedan en lane 0 con lanes 1 (ancho completo).
function asignarCarriles(placements: Placement[]): void {
  const orden = [...placements].sort((a, b) =>
    a.startRow - b.startRow || (a.startRow + a.span) - (b.startRow + b.span))

  // Agrupar en clusters de ubicaciones que se solapan (directa o transitivamente)
  let cluster: Placement[] = []
  let clusterEnd = -1
  const clusters: Placement[][] = []
  for (const p of orden) {
    if (cluster.length && p.startRow < clusterEnd) {
      cluster.push(p)
      clusterEnd = Math.max(clusterEnd, p.startRow + p.span)
    } else {
      if (cluster.length) clusters.push(cluster)
      cluster = [p]
      clusterEnd = p.startRow + p.span
    }
  }
  if (cluster.length) clusters.push(cluster)

  // Dentro de cada cluster: first-fit por carril; lanes = carriles usados
  for (const cl of clusters) {
    const laneEnd: number[] = []   // fila final ocupada por cada carril
    for (const p of cl) {
      let li = laneEnd.findIndex(end => end <= p.startRow)
      if (li === -1) { li = laneEnd.length; laneEnd.push(0) }
      p.lane = li
      laneEnd[li] = p.startRow + p.span
    }
    for (const p of cl) p.lanes = laneEnd.length
  }
}

function buildPlacements(filtered: SeccionAsignada[]): Record<Dia, Placement[]> {
  const out = {} as Record<Dia, Placement[]>
  for (const d of DIAS) {
    const porKey = new Map<string, Placement>()
    const orden: string[] = []
    for (const sec of filtered) {
      for (const b of sec.bloques) {
        if (b.dia !== d.key) continue
        const startRow = rowOf(b.hora_inicio)
        if (startRow < 0) continue
        const span = spanOf(b.hora_inicio, b.hora_fin)
        const key  = `${sec.codigo}|${startRow}|${span}`
        let p = porKey.get(key)
        if (!p) {
          p = { key: `${d.key}-${key}`, sections: [], startRow, span, lane: 0, lanes: 1 }
          porKey.set(key, p)
          orden.push(key)
        }
        if (!p.sections.some(s => s.id === sec.id)) p.sections.push(sec)
      }
    }
    const placements = orden.map(k => porKey.get(k)!)
    asignarCarriles(placements)
    out[d.key] = placements
  }
  return out
}

// ── Componente principal ──────────────────────────────────────────────────────

interface Props { secciones: SeccionAsignada[] }

export default function HorarioGrid({ secciones }: Props) {
  const [filters, setFilters]   = useState<Filters>({
    carrera: '', semestre: '', tipo: '', texto: '',
  })
  const [selected, setSelected] = useState<SeccionAsignada | null>(null)

  const availableSems = useMemo(() => {
    if (!filters.carrera) return []
    const set = new Set<string>()
    for (const sec of secciones)
      for (const s of getSemestresForCarrera(sec, filters.carrera))
        set.add(s)
    return Array.from(set).sort(compareSems)
  }, [secciones, filters.carrera])

  const filtered   = useMemo(() => aplicarFiltros(secciones, filters), [secciones, filters])
  const placements = useMemo(() => buildPlacements(filtered), [filtered])
  const total      = filtered.length

  function setCarrera(car: string) {
    setFilters(f => ({ ...f, carrera: car, semestre: '' }))
  }

  const bodyHeight = SUB_BLOQUES.length * ROW_H

  return (
    <div className="flex flex-col gap-5">

      {/* ── Filtros ────────────────────────────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">

        {/* Carreras */}
        <div className="flex flex-wrap gap-1.5">
          <TabBtn active={filters.carrera === ''} onClick={() => setCarrera('')}>
            Todas las carreras
          </TabBtn>
          {CARRERAS.map(car => (
            <TabBtn key={car} active={filters.carrera === car} onClick={() => setCarrera(car)}>
              {car}
            </TabBtn>
          ))}
        </div>

        {/* Semestres */}
        {filters.carrera !== '' && availableSems.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-0.5 border-t border-gray-100">
            <TabBtn
              active={filters.semestre === ''}
              onClick={() => setFilters(f => ({ ...f, semestre: '' }))}
              secondary
            >
              Todos los semestres
            </TabBtn>
            {availableSems.map(sem => (
              <TabBtn
                key={sem}
                active={filters.semestre === sem}
                onClick={() => setFilters(f => ({ ...f, semestre: sem }))}
                secondary
              >
                Sem. {sem}
              </TabBtn>
            ))}
          </div>
        )}

        {/* Tipo + búsqueda */}
        <div className="flex flex-wrap items-center gap-3 pt-0.5 border-t border-gray-100">
          <div className="flex gap-1">
            {(['', 'CLAS', 'AYUD', 'LABT'] as const).map(t => (
              <button
                key={t}
                onClick={() => setFilters(f => ({ ...f, tipo: t as TipoSeccion | '' }))}
                className={`px-2.5 py-1 text-xs rounded transition-colors
                  ${filters.tipo === t
                    ? t === '' ? 'bg-gray-800 text-white' : TIPO_BTN_ACTIVE[t]
                    : 'border border-gray-200 text-gray-500 hover:border-gray-300'
                  }`}
              >
                {t === '' ? 'Todos' : TIPO_LABEL[t]}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2 flex-1 min-w-48 border border-gray-200
                          rounded px-3 py-1.5 focus-within:border-gray-400 transition-colors">
            <Search size={13} className="text-gray-400 shrink-0" />
            <input
              type="text"
              placeholder="Código, título o profesor…"
              value={filters.texto}
              onChange={e => setFilters(f => ({ ...f, texto: e.target.value }))}
              className="flex-1 text-xs text-gray-700 placeholder-gray-400
                         border-none outline-none bg-transparent"
            />
            {filters.texto && (
              <button onClick={() => setFilters(f => ({ ...f, texto: '' }))}>
                <X size={12} className="text-gray-400 hover:text-gray-600" />
              </button>
            )}
          </div>

          <span className="text-xs text-gray-400 ml-auto shrink-0 tabular-nums">
            {total} secciones
          </span>
        </div>
      </div>

      {/* ── Grilla de sub-bloques ──────────────────────────────────────────── */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <div className="flex" style={{ minWidth: 900 }}>

          {/* Columna de horas */}
          <div className="w-24 shrink-0 border-r border-gray-200">
            <div style={{ height: HEADER_H }} className="bg-gray-800" />
            {SUB_BLOQUES.map((sb, i) => (
              <div
                key={sb.inicio}
                style={{ height: ROW_H }}
                className={`px-2 flex flex-col justify-center items-end border-t border-gray-100
                  ${i % 2 === 1 ? 'bg-gray-50/50' : ''}`}
              >
                <span className="text-[11px] font-semibold text-gray-600 tabular-nums leading-none">
                  {sb.inicio}
                </span>
                <span className="text-[10px] text-gray-400 tabular-nums leading-none mt-0.5">
                  {sb.fin}
                </span>
              </div>
            ))}
          </div>

          {/* Columnas por día */}
          {DIAS.map(d => (
            <div key={d.key} className="flex-1 min-w-0 border-l border-gray-200 first:border-l-0">
              <div
                style={{ height: HEADER_H }}
                className="bg-[#B71C1C] text-white text-xs font-semibold flex items-center justify-center"
              >
                {d.label}
              </div>
              <div className="relative" style={{ height: bodyHeight }}>
                {/* Líneas de fondo por sub-bloque */}
                {SUB_BLOQUES.map((_, i) => (
                  <div
                    key={i}
                    style={{ top: i * ROW_H, height: ROW_H }}
                    className={`absolute inset-x-0 border-t border-gray-100
                      ${i % 2 === 1 ? 'bg-gray-50/50' : ''}`}
                  />
                ))}
                {/* Ubicaciones (clases) */}
                {placements[d.key].map(p => (
                  <div
                    key={p.key}
                    className="absolute p-0.5"
                    style={{
                      top:    p.startRow * ROW_H,
                      height: p.span * ROW_H,
                      left:   `${(p.lane / p.lanes) * 100}%`,
                      width:  `${100 / p.lanes}%`,
                    }}
                  >
                    {p.sections.length === 1 ? (
                      <SeccionCard
                        sec={p.sections[0]}
                        isSelected={selected?.id === p.sections[0].id}
                        onClick={() => setSelected(p.sections[0] === selected ? null : p.sections[0])}
                      />
                    ) : (
                      <GroupBlock group={p.sections} selected={selected} onSelect={setSelected} />
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Detalle ────────────────────────────────────────────────────────── */}
      {selected && (
        <SeccionDetail sec={selected} onClose={() => setSelected(null)} />
      )}

      {/* ── Leyenda ────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-5 text-xs text-gray-500">
        {(['CLAS', 'AYUD', 'LABT'] as TipoSeccion[]).map(t => (
          <span key={t} className="flex items-center gap-1.5">
            <span className={`inline-block w-2.5 h-2.5 rounded-sm ${TIPO_TAG[t]}`} />
            {TIPO_LABEL[t]}
          </span>
        ))}
        <span className="text-gray-400">
          · Cada fila es un sub-bloque de 50 min; la altura del curso indica su duración
        </span>
      </div>
    </div>
  )
}

// ── GroupBlock ────────────────────────────────────────────────────────────────
//
// Secciones paralelas del MISMO curso (mismo bloque). Borde izquierdo continuo.
// Primera sección: código-sección, título, profesor + tag "N paralelas".
// Secciones siguientes: solo código-sección y profesor.

function GroupBlock({
  group, selected, onSelect,
}: {
  group:    SeccionAsignada[]
  selected: SeccionAsignada | null
  onSelect: (sec: SeccionAsignada | null) => void
}) {
  const tipo = group[0].tipo

  return (
    <div className={`h-full rounded overflow-y-auto flex flex-col ${TIPO_CARD[tipo]}`}>
      {group.map((sec, idx) => (
        <button
          key={sec.id}
          onClick={() => onSelect(sec === selected ? null : sec)}
          className={`w-full text-left px-1.5 py-1 text-xs transition-all shrink-0
            ${idx > 0 ? `border-t ${TIPO_DIVIDER[tipo]}` : ''}
            ${selected?.id === sec.id
              ? 'ring-1 ring-inset ring-gray-400 shadow-sm'
              : 'hover:brightness-95'
            }
          `}
        >
          {idx === 0 ? (
            <>
              <span className="font-semibold block truncate leading-tight">
                {sec.codigo}-{sec.seccion}
              </span>
              <span className="block truncate text-[10px] opacity-75 leading-tight">
                {sec.titulo}
              </span>
              <span className="block truncate text-[10px] opacity-55 leading-tight">
                {sec.profesor}
              </span>
              <span className="block text-[10px] opacity-50 mt-0.5 leading-tight">
                ┄&nbsp;{group.length} secciones paralelas
              </span>
            </>
          ) : (
            <>
              <span className="font-semibold block truncate leading-tight">
                {sec.codigo}-{sec.seccion}
              </span>
              <span className="block truncate text-[10px] opacity-55 leading-tight">
                {sec.profesor}
              </span>
            </>
          )}
        </button>
      ))}
    </div>
  )
}

// ── SeccionCard ───────────────────────────────────────────────────────────────
// Sección individual, centrada verticalmente dentro del span de filas que ocupa.

function SeccionCard({
  sec, onClick, isSelected,
}: {
  sec:        SeccionAsignada
  onClick:    () => void
  isSelected: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`h-full w-full text-left rounded px-1.5 py-1 text-xs transition-all
        flex flex-col justify-center overflow-hidden
        ${TIPO_CARD[sec.tipo]}
        ${isSelected ? 'ring-1 ring-inset ring-gray-400 shadow-sm' : 'hover:brightness-95'}
      `}
    >
      <span className="font-semibold block truncate leading-tight">
        {sec.codigo}-{sec.seccion}
      </span>
      <span className="block truncate text-[10px] opacity-75 leading-tight">
        {sec.titulo}
      </span>
      <span className="block truncate text-[10px] opacity-55 leading-tight">
        {sec.profesor}
      </span>
    </button>
  )
}

// ── SeccionDetail ─────────────────────────────────────────────────────────────

function SeccionDetail({
  sec, onClose,
}: {
  sec:     SeccionAsignada
  onClose: () => void
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-[10px] font-semibold uppercase tracking-wide
                             px-2 py-0.5 rounded ${TIPO_TAG[sec.tipo]}`}>
              {TIPO_LABEL[sec.tipo]}
            </span>
            <h3 className="font-semibold text-gray-900 text-sm">
              {sec.codigo} — Sección {sec.seccion}
            </h3>
          </div>
          <p className="text-gray-600 text-sm">{sec.titulo}</p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-0.5 transition-colors">
          <X size={16} />
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4">
        <Field label="Profesor"  value={sec.profesor} />
        <Field label="Carreras"  value={sec.carreras || '—'} />
        <Field label="Semestres" value={sec.semestres || '—'} />
        <Field
          label="Bloques"
          value={`${sec.bloques.length} bloque${sec.bloques.length !== 1 ? 's' : ''}`}
        />
      </div>

      <div>
        <p className="text-xs font-medium text-gray-400 mb-2">Bloques asignados</p>
        <div className="flex flex-wrap gap-2">
          {sec.bloques.map((b, i) => (
            <span key={i} className="text-xs bg-gray-100 text-gray-700 px-3 py-1 rounded">
              {DIAS_LABEL[b.dia as Dia]} · {b.hora_inicio}–{b.hora_fin} ({b.tipo_bloque})
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Sub-componentes generales ─────────────────────────────────────────────────

function TabBtn({
  children, active, onClick, secondary = false,
}: {
  children:   React.ReactNode
  active:     boolean
  onClick:    () => void
  secondary?: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-xs font-medium rounded transition-colors
        ${active
          ? secondary ? 'bg-gray-700 text-white' : 'bg-[#B71C1C] text-white'
          : 'border border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50'
        }`}
    >
      {children}
    </button>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-gray-400 font-medium">{label}</p>
      <p className="text-sm text-gray-800 mt-0.5">{value}</p>
    </div>
  )
}