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

// Inicios de bloque posibles, en orden cronológico (minutos desde medianoche).
const HORA_ORDEN: Record<string, number> = {
  '8:30': 510, '9:30': 570, '10:30': 630, '11:30': 690, '12:30': 750,
  '13:30': 810, '14:30': 870, '15:30': 930, '16:30': 990, '17:30': 1050,
}
// Franjas estándar: siempre visibles aunque no tengan clases (grilla institucional).
const FRANJAS_ESTANDAR = ['8:30', '10:30', '12:30', '13:30', '15:30', '17:30']

interface Franja { hora: string; label: string; helper: boolean }

function fmtHora(h: string): string {
  const [hh, mm] = h.split(':')
  return `${hh.padStart(2, '0')}:${mm}`
}

// Construye las filas de la grilla: estándar siempre + cualquier inicio "helper"
// (9:30, 14:30, 16:30, …) que realmente aparezca en los datos.
function buildFranjas(secciones: SeccionAsignada[]): Franja[] {
  const horas = new Set<string>(FRANJAS_ESTANDAR)
  for (const sec of secciones)
    for (const b of sec.bloques)
      horas.add(b.hora_inicio)
  return Array.from(horas)
    .filter(h => h in HORA_ORDEN)
    .sort((a, b) => HORA_ORDEN[a] - HORA_ORDEN[b])
    .map(h => ({ hora: h, label: fmtHora(h), helper: !FRANJAS_ESTANDAR.includes(h) }))
}

const DIAS_LABEL: Record<Dia, string> = {
  L: 'Lunes', M: 'Martes', X: 'Miércoles', J: 'Jueves', V: 'Viernes',
}

// Estilo base por tipo (borde izquierdo + fondo + texto)
const TIPO_CARD: Record<TipoSeccion, string> = {
  CLAS: 'bg-red-50   border-l-[3px] border-red-700   text-red-950',
  AYUD: 'bg-gray-100 border-l-[3px] border-gray-500  text-gray-900',
  LABT: 'bg-stone-100 border-l-[3px] border-stone-600 text-stone-900',
}

// Color del separador horizontal entre secciones paralelas
const TIPO_DIVIDER: Record<TipoSeccion, string> = {
  CLAS: 'border-red-200',
  AYUD: 'border-gray-300',
  LABT: 'border-stone-300',
}

const TIPO_TAG: Record<TipoSeccion, string> = {
  CLAS: 'bg-red-100  text-red-800',
  AYUD: 'bg-gray-200 text-gray-700',
  LABT: 'bg-stone-200 text-stone-700',
}
const TIPO_LABEL: Record<TipoSeccion, string> = {
  CLAS: 'Cátedra',
  AYUD: 'Ayudantía',
  LABT: 'Lab / Taller',
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

// ── Agrupación de celdas ──────────────────────────────────────────────────────
//
// Agrupa las secciones de una celda por codigo_curso preservando orden
// de primera aparición.
//
//   Mismo curso → un grupo  → indicador visual de paralelismo
//   Cursos distintos → grupos distintos → apilados verticalmente

function groupByCourse(secs: SeccionAsignada[]): SeccionAsignada[][] {
  const groups: SeccionAsignada[][] = []
  const index  = new Map<string, number>()
  for (const sec of secs) {
    const i = index.get(sec.codigo)
    if (i !== undefined) {
      groups[i].push(sec)
    } else {
      index.set(sec.codigo, groups.length)
      groups.push([sec])
    }
  }
  return groups
}

// ── Tipos ─────────────────────────────────────────────────────────────────────

interface Filters {
  carrera:  string
  semestre: string
  tipo:     TipoSeccion | ''
  texto:    string
}

type GridMap = Map<Dia, Map<string, SeccionAsignada[]>>

// ── buildGrid ─────────────────────────────────────────────────────────────────

function buildGrid(secciones: SeccionAsignada[], filters: Filters, franjas: Franja[]): GridMap {
  const grid: GridMap = new Map()
  for (const d of DIAS) {
    const dmap = new Map<string, SeccionAsignada[]>()
    for (const f of franjas) dmap.set(f.hora, [])
    grid.set(d.key, dmap)
  }

  const q = filters.texto.toLowerCase()

  for (const sec of secciones) {
    if (filters.tipo && sec.tipo !== filters.tipo) continue
    if (filters.carrera && !sec.carreras.includes(filters.carrera)) continue
    if (filters.carrera && filters.semestre) {
      const sems = getSemestresForCarrera(sec, filters.carrera)
      if (!sems.includes(filters.semestre)) continue
    }
    if (q && ![sec.codigo, sec.titulo, sec.profesor, sec.seccion]
        .join(' ').toLowerCase().includes(q)) continue

    for (const b of sec.bloques) {
      const cell = grid.get(b.dia as Dia)?.get(b.hora_inicio)
      if (cell) cell.push(sec)
    }
  }
  return grid
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

  const franjas = useMemo(() => buildFranjas(secciones), [secciones])
  const grid  = useMemo(() => buildGrid(secciones, filters, franjas), [secciones, filters, franjas])
  const total = useMemo(() => {
    let n = 0
    grid.forEach(dm => dm.forEach(arr => { n += arr.length }))
    return n
  }, [grid])

  function setCarrera(car: string) {
    setFilters(f => ({ ...f, carrera: car, semestre: '' }))
  }

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
                    ? t === ''     ? 'bg-gray-800 text-white'
                    : t === 'CLAS' ? 'bg-red-700 text-white'
                    : t === 'AYUD' ? 'bg-gray-500 text-white'
                                   : 'bg-stone-600 text-white'
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

      {/* ── Grilla ─────────────────────────────────────────────────────────── */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full border-collapse bg-white text-sm" style={{ minWidth: 860 }}>
          <thead>
            <tr>
              <th className="w-20 bg-gray-800 text-white text-xs font-medium p-3 text-left">
                Hora
              </th>
              {DIAS.map(d => (
                <th key={d.key}
                    className="bg-[#B71C1C] text-white text-xs font-semibold p-3 text-center w-1/5">
                  {d.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {franjas.map((franja, fi) => (
              <tr key={franja.hora}
                  className={franja.helper ? 'bg-amber-50/40' : (fi % 2 === 0 ? 'bg-white' : 'bg-gray-50/60')}>
                <td className="p-2 pr-3 text-right border-r border-gray-200 align-top">
                  <span className={`text-xs font-medium ${franja.helper ? 'text-amber-600' : 'text-gray-400'}`}>
                    {franja.label}
                    {franja.helper && <span className="block text-[9px] text-amber-500">fuera de grilla</span>}
                  </span>
                </td>
                {DIAS.map(d => {
                  const secs = grid.get(d.key)?.get(franja.hora) ?? []
                  return (
                    <td key={d.key} className="p-1 align-top border-l border-gray-100">
                      {secs.length > 0
                        ? <CellContent secs={secs} selected={selected} onSelect={setSelected} />
                        : <div className="h-8" />
                      }
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
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
        <span className="text-gray-400">· Haz clic en una sección para ver el detalle</span>
      </div>
    </div>
  )
}

// ── CellContent ───────────────────────────────────────────────────────────────
//
// Lógica de renderizado de una celda:
//   1. Agrupa secciones por curso (groupByCourse)
//   2. Grupo de 1 sección  → SeccionCard normal
//   3. Grupo de N secciones del mismo curso → GroupBlock (indicador de paralelismo)
//   4. Los grupos se apilan verticalmente

function CellContent({
  secs, selected, onSelect,
}: {
  secs:     SeccionAsignada[]
  selected: SeccionAsignada | null
  onSelect: (sec: SeccionAsignada | null) => void
}) {
  const groups = groupByCourse(secs)

  return (
    <div className="space-y-0.5">
      {groups.map((group, gi) =>
        group.length === 1 ? (
          <SeccionCard
            key={group[0].id}
            sec={group[0]}
            isSelected={selected?.id === group[0].id}
            onClick={() => onSelect(group[0] === selected ? null : group[0])}
          />
        ) : (
          <GroupBlock
            key={gi}
            group={group}
            selected={selected}
            onSelect={onSelect}
          />
        )
      )}
    </div>
  )
}

// ── GroupBlock ────────────────────────────────────────────────────────────────
//
// Secciones paralelas del MISMO curso.
// El contenedor comparte el borde izquierdo continuo (visualmente conectado).
// Primera sección: código-sección, título, profesor + tag "N paralelas".
// Secciones siguientes: solo código-sección y profesor (el título se omite).

function GroupBlock({
  group, selected, onSelect,
}: {
  group:    SeccionAsignada[]
  selected: SeccionAsignada | null
  onSelect: (sec: SeccionAsignada | null) => void
}) {
  const tipo = group[0].tipo

  return (
    <div className={`rounded overflow-hidden ${TIPO_CARD[tipo]}`}>
      {group.map((sec, idx) => (
        <button
          key={sec.id}
          onClick={() => onSelect(sec === selected ? null : sec)}
          className={`w-full text-left p-1.5 text-xs transition-all
            ${idx > 0 ? `border-t ${TIPO_DIVIDER[tipo]}` : ''}
            ${selected?.id === sec.id
              ? 'ring-1 ring-inset ring-gray-400 shadow-sm'
              : 'hover:brightness-95'
            }
          `}
        >
          {/* Primera sección: info completa + indicador de paralelismo */}
          {idx === 0 ? (
            <>
              <span className="font-semibold block truncate leading-tight">
                {sec.codigo}-{sec.seccion}
              </span>
              <span className="block truncate text-[10px] opacity-75 mt-0.5 leading-tight">
                {sec.titulo}
              </span>
              <span className="block truncate text-[10px] opacity-55 leading-tight">
                {sec.profesor}
              </span>
              <span className="block text-[10px] text-gray-400 mt-1 leading-tight">
                ┄&nbsp;{group.length} secciones paralelas
              </span>
            </>
          ) : (
            /* Secciones siguientes: solo sección + profesor (título ya mostrado) */
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
// Sección individual (sin paralelas en la misma celda).

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
      className={`w-full text-left rounded p-1.5 text-xs transition-all
        ${TIPO_CARD[sec.tipo]}
        ${isSelected ? 'ring-1 ring-offset-1 ring-gray-400 shadow-sm' : 'hover:brightness-95'}
      `}
    >
      <span className="font-semibold block truncate leading-tight">
        {sec.codigo}-{sec.seccion}
      </span>
      <span className="block truncate text-[10px] opacity-75 mt-0.5 leading-tight">
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
