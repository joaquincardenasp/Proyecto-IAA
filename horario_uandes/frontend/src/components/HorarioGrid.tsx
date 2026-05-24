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

const FRANJAS = [
  { hora: '8:30',  label: '08:30' },
  { hora: '10:30', label: '10:30' },
  { hora: '12:30', label: '12:30' },
  { hora: '13:30', label: '13:30' },
  { hora: '15:30', label: '15:30' },
  { hora: '17:30', label: '17:30' },
]

const DIAS_LABEL: Record<Dia, string> = {
  L: 'Lunes', M: 'Martes', X: 'Miércoles', J: 'Jueves', V: 'Viernes',
}

// Paleta monocromática rojo/gris — sin colores arco iris
const TIPO_CARD: Record<TipoSeccion, string> = {
  CLAS: 'bg-red-50 border-l-[3px] border-red-700 text-red-950',
  AYUD: 'bg-gray-100 border-l-[3px] border-gray-500 text-gray-900',
  LABT: 'bg-stone-100 border-l-[3px] border-stone-600 text-stone-900',
}
const TIPO_TAG: Record<TipoSeccion, string> = {
  CLAS: 'bg-red-100 text-red-800',
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

/**
 * Extrae los semestres que una sección tiene para una carrera concreta.
 * carreras = "Plan Común · ICI"  y  semestres = "1/2 · 5"
 * getSemestresForCarrera(sec, "Plan Común") → ["1", "2"]
 */
function getSemestresForCarrera(sec: SeccionAsignada, carrera: string): string[] {
  const cars = sec.carreras.split(' · ')
  const sems = sec.semestres.split(' · ')
  const idx  = cars.indexOf(carrera)
  if (idx === -1) return []
  return sems[idx]?.split('/').map(s => s.trim()).filter(Boolean) ?? []
}

/**
 * Ordena semestres igual que el backend: "1" < "2" < … < "9a" < "9f" < "10"
 */
function semSortKey(s: string): [number, string] {
  const digits = s.replace(/\D/g, '')
  return [digits ? parseInt(digits, 10) : 999, s]
}

function compareSems(a: string, b: string): number {
  const [na, sa] = semSortKey(a)
  const [nb, sb] = semSortKey(b)
  return na !== nb ? na - nb : sa.localeCompare(sb)
}

/** Etiqueta legible para un semestre: "1" → "1.°", "9a" → "9a" */
function semLabel(s: string): string {
  return `Sem. ${s}`
}

// ── Tipos ─────────────────────────────────────────────────────────────────────

interface Filters {
  carrera:  string          // '' = todas las carreras
  semestre: string          // '' = todos los semestres (solo aplica si carrera ≠ '')
  tipo:     TipoSeccion | ''
  texto:    string
}

type GridMap = Map<Dia, Map<string, SeccionAsignada[]>>

// ── buildGrid ─────────────────────────────────────────────────────────────────

function buildGrid(secciones: SeccionAsignada[], filters: Filters): GridMap {
  const grid: GridMap = new Map()
  for (const d of DIAS) {
    const dmap = new Map<string, SeccionAsignada[]>()
    for (const f of FRANJAS) dmap.set(f.hora, [])
    grid.set(d.key, dmap)
  }

  const q = filters.texto.toLowerCase()

  for (const sec of secciones) {
    // Filtro tipo
    if (filters.tipo && sec.tipo !== filters.tipo) continue

    // Filtro carrera
    if (filters.carrera && !sec.carreras.includes(filters.carrera)) continue

    // Filtro semestre (solo cuando hay carrera seleccionada)
    if (filters.carrera && filters.semestre) {
      const sems = getSemestresForCarrera(sec, filters.carrera)
      if (!sems.includes(filters.semestre)) continue
    }

    // Filtro texto libre
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

  // Semestres disponibles para la carrera actualmente seleccionada
  const availableSems = useMemo(() => {
    if (!filters.carrera) return []
    const set = new Set<string>()
    for (const sec of secciones) {
      for (const s of getSemestresForCarrera(sec, filters.carrera)) {
        set.add(s)
      }
    }
    return Array.from(set).sort(compareSems)
  }, [secciones, filters.carrera])

  const grid  = useMemo(() => buildGrid(secciones, filters), [secciones, filters])
  const total = useMemo(() => {
    let n = 0
    grid.forEach(dm => dm.forEach(arr => { n += arr.length }))
    return n
  }, [grid])

  function setCarrera(car: string) {
    // Resetear semestre al cambiar carrera
    setFilters(f => ({ ...f, carrera: car, semestre: '' }))
  }

  function setSemestre(sem: string) {
    setFilters(f => ({ ...f, semestre: sem }))
  }

  return (
    <div className="flex flex-col gap-5">

      {/* ── Panel de filtros ───────────────────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">

        {/* Fila 1 — Tabs de carrera */}
        <div className="flex flex-wrap gap-1.5">
          <TabBtn
            active={filters.carrera === ''}
            onClick={() => setCarrera('')}
          >
            Todas las carreras
          </TabBtn>
          {CARRERAS.map(car => (
            <TabBtn
              key={car}
              active={filters.carrera === car}
              onClick={() => setCarrera(car)}
            >
              {car}
            </TabBtn>
          ))}
        </div>

        {/* Fila 2 — Tabs de semestre (solo cuando hay carrera seleccionada) */}
        {filters.carrera !== '' && availableSems.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-0.5 border-t border-gray-100">
            <TabBtn
              active={filters.semestre === ''}
              onClick={() => setSemestre('')}
              secondary
            >
              Todos los semestres
            </TabBtn>
            {availableSems.map(sem => (
              <TabBtn
                key={sem}
                active={filters.semestre === sem}
                onClick={() => setSemestre(sem)}
                secondary
              >
                {semLabel(sem)}
              </TabBtn>
            ))}
          </div>
        )}

        {/* Fila 3 — Tipo + búsqueda */}
        <div className="flex flex-wrap items-center gap-3 pt-0.5 border-t border-gray-100">
          {/* Tipo */}
          <div className="flex gap-1">
            {(['', 'CLAS', 'AYUD', 'LABT'] as const).map(t => (
              <button
                key={t}
                onClick={() => setFilters(f => ({ ...f, tipo: t as TipoSeccion | '' }))}
                className={`px-2.5 py-1 text-xs rounded transition-colors
                  ${filters.tipo === t
                    ? t === ''
                      ? 'bg-gray-800 text-white'
                      : t === 'CLAS'
                        ? 'bg-red-700 text-white'
                        : t === 'AYUD'
                          ? 'bg-gray-500 text-white'
                          : 'bg-stone-600 text-white'
                    : 'border border-gray-200 text-gray-500 hover:border-gray-300'
                  }`}
              >
                {t === '' ? 'Todos' : TIPO_LABEL[t]}
              </button>
            ))}
          </div>

          {/* Búsqueda */}
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

          {/* Contador */}
          <span className="text-xs text-gray-400 ml-auto shrink-0 tabular-nums">
            {total} secciones
          </span>
        </div>
      </div>

      {/* ── Grilla ─────────────────────────────────────────────────────────── */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table
          className="w-full border-collapse bg-white text-sm"
          style={{ minWidth: 860 }}
        >
          <thead>
            <tr>
              <th className="w-20 bg-gray-800 text-white text-xs font-medium p-3 text-left">
                Hora
              </th>
              {DIAS.map(d => (
                <th
                  key={d.key}
                  className="bg-[#B71C1C] text-white text-xs font-semibold p-3
                             text-center w-1/5"
                >
                  {d.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {FRANJAS.map((franja, fi) => (
              <tr
                key={franja.hora}
                className={fi % 2 === 0 ? 'bg-white' : 'bg-gray-50/60'}
              >
                <td className="p-2 pr-3 text-right border-r border-gray-200 align-top">
                  <span className="text-xs font-medium text-gray-400">
                    {franja.label}
                  </span>
                </td>
                {DIAS.map(d => {
                  const secs = grid.get(d.key)?.get(franja.hora) ?? []
                  return (
                    <td
                      key={d.key}
                      className="p-1 align-top border-l border-gray-100"
                    >
                      {secs.length > 0 ? (
                        <div className="space-y-1">
                          {secs.map(sec => (
                            <SeccionCard
                              key={sec.id + franja.hora}
                              sec={sec}
                              isSelected={selected?.id === sec.id}
                              onClick={() => setSelected(sec === selected ? null : sec)}
                            />
                          ))}
                        </div>
                      ) : (
                        <div className="h-8" />
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Detalle al hacer click ─────────────────────────────────────────── */}
      {selected && (
        <SeccionDetail
          sec={selected}
          onClose={() => setSelected(null)}
        />
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

// ── Sub-componentes ───────────────────────────────────────────────────────────

/** Botón de tab reutilizable para carrera y semestre */
function TabBtn({
  children, active, onClick, secondary = false,
}: {
  children: React.ReactNode
  active: boolean
  onClick: () => void
  secondary?: boolean
}) {
  if (active) {
    return (
      <button
        onClick={onClick}
        className={`px-3 py-1.5 text-xs font-medium rounded transition-colors
          ${secondary
            ? 'bg-gray-700 text-white'
            : 'bg-[#B71C1C] text-white'
          }`}
      >
        {children}
      </button>
    )
  }
  return (
    <button
      onClick={onClick}
      className="px-3 py-1.5 text-xs font-medium rounded border border-gray-200
                 text-gray-600 hover:border-gray-300 hover:bg-gray-50 transition-colors"
    >
      {children}
    </button>
  )
}

/** Tarjeta compacta de sección en la grilla */
function SeccionCard({
  sec, onClick, isSelected,
}: {
  sec: SeccionAsignada
  onClick: () => void
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

/** Panel expandido de detalle */
function SeccionDetail({
  sec, onClose,
}: {
  sec: SeccionAsignada
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
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 p-0.5 transition-colors"
        >
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
            <span
              key={i}
              className="text-xs bg-gray-100 text-gray-700 px-3 py-1 rounded"
            >
              {DIAS_LABEL[b.dia as Dia]} · {b.hora_inicio}–{b.hora_fin} ({b.tipo_bloque})
            </span>
          ))}
        </div>
      </div>
    </div>
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
