import { useState, useMemo, useEffect, useCallback } from 'react'
import {
  Search, X, Move, Check, AlertTriangle, Loader2, ShieldCheck, ChevronLeft,
  History, SlidersHorizontal,
} from 'lucide-react'
import type {
  SeccionAsignada, TipoSeccion, Dia, BloqueValido, ConflictoActivo, VersionInfo,
} from '../types'
import {
  getBloquesValidos, postMover, getConflictos, listarVersiones, cargarVersion,
} from '../api/client'
import { TIPO_COLOR, TIPO_LABEL } from '../theme'

// ── Constantes de grilla ────────────────────────────────────────────────────────

const DIAS: { key: Dia; label: string; short: string }[] = [
  { key: 'L', label: 'Lunes', short: 'Lun' },
  { key: 'M', label: 'Martes', short: 'Mar' },
  { key: 'X', label: 'Miércoles', short: 'Mié' },
  { key: 'J', label: 'Jueves', short: 'Jue' },
  { key: 'V', label: 'Viernes', short: 'Vie' },
]
const DIAS_LABEL: Record<Dia, string> = { L: 'Lunes', M: 'Martes', X: 'Miércoles', J: 'Jueves', V: 'Viernes' }

const SUB_BLOQUES: { inicio: string; fin: string; min: number }[] = [
  { inicio: '08:30', fin: '09:20', min: 510 }, { inicio: '09:30', fin: '10:20', min: 570 },
  { inicio: '10:30', fin: '11:20', min: 630 }, { inicio: '11:30', fin: '12:20', min: 690 },
  { inicio: '12:30', fin: '13:20', min: 750 }, { inicio: '13:30', fin: '14:20', min: 810 },
  { inicio: '14:30', fin: '15:20', min: 870 }, { inicio: '15:30', fin: '16:20', min: 930 },
  { inicio: '16:30', fin: '17:20', min: 990 }, { inicio: '17:30', fin: '18:20', min: 1050 },
  { inicio: '18:30', fin: '19:20', min: 1110 },
]
const SUB_MIN = SUB_BLOQUES.map(s => s.min)
const ROW_H = 42
const HEADER_H = 34

const TIPO_FILTER_LABEL: Record<TipoSeccion, string> = TIPO_LABEL
const CARRERAS = ['Plan Común', 'ICI', 'IOC', 'ICE', 'ICC', 'ICA', 'ICQ']

function toMin(h: string): number { const [hh, mm] = h.split(':').map(Number); return hh * 60 + mm }
function rowOf(horaInicio: string): number { return SUB_MIN.indexOf(toMin(horaInicio)) }
function spanOf(horaInicio: string, horaFin: string): number {
  const a = toMin(horaInicio), b = toMin(horaFin)
  return SUB_MIN.filter(m => m >= a && m < b).length || 1
}

function getSemestresForCarrera(sec: SeccionAsignada, carrera: string): string[] {
  const cars = sec.carreras.split(' · '), sems = sec.semestres.split(' · ')
  const idx = cars.indexOf(carrera)
  if (idx === -1) return []
  return sems[idx]?.split('/').map(s => s.trim()).filter(Boolean) ?? []
}
function semSortKey(s: string): [number, string] {
  const d = s.replace(/\D/g, ''); return [d ? parseInt(d, 10) : 999, s]
}
function compareSems(a: string, b: string): number {
  const [na, sa] = semSortKey(a), [nb, sb] = semSortKey(b)
  return na !== nb ? na - nb : sa.localeCompare(sb)
}

interface Filters { carrera: string; semestre: string; tipo: TipoSeccion | ''; texto: string }

interface Placement {
  key: string; sections: SeccionAsignada[]; startRow: number; span: number; lane: number; lanes: number
}

function aplicarFiltros(secciones: SeccionAsignada[], f: Filters): SeccionAsignada[] {
  const q = f.texto.toLowerCase()
  return secciones.filter(sec => {
    if (f.tipo && sec.tipo !== f.tipo) return false
    if (f.carrera && !sec.carreras.includes(f.carrera)) return false
    if (f.carrera && f.semestre && !getSemestresForCarrera(sec, f.carrera).includes(f.semestre)) return false
    if (q && ![sec.codigo, sec.titulo, sec.profesor, sec.seccion].join(' ').toLowerCase().includes(q)) return false
    return true
  })
}

function asignarCarriles(placements: Placement[]): void {
  const orden = [...placements].sort((a, b) => a.startRow - b.startRow || (a.startRow + a.span) - (b.startRow + b.span))
  let cluster: Placement[] = [], clusterEnd = -1
  const clusters: Placement[][] = []
  for (const p of orden) {
    if (cluster.length && p.startRow < clusterEnd) { cluster.push(p); clusterEnd = Math.max(clusterEnd, p.startRow + p.span) }
    else { if (cluster.length) clusters.push(cluster); cluster = [p]; clusterEnd = p.startRow + p.span }
  }
  if (cluster.length) clusters.push(cluster)
  for (const cl of clusters) {
    const laneEnd: number[] = []
    for (const p of cl) {
      let li = laneEnd.findIndex(end => end <= p.startRow)
      if (li === -1) { li = laneEnd.length; laneEnd.push(0) }
      p.lane = li; laneEnd[li] = p.startRow + p.span
    }
    for (const p of cl) p.lanes = laneEnd.length
  }
}

function buildPlacements(filtered: SeccionAsignada[]): Record<Dia, Placement[]> {
  const out = {} as Record<Dia, Placement[]>
  for (const d of DIAS) {
    const porKey = new Map<string, Placement>(); const orden: string[] = []
    for (const sec of filtered) for (const b of sec.bloques) {
      if (b.dia !== d.key) continue
      const startRow = rowOf(b.hora_inicio); if (startRow < 0) continue
      const span = spanOf(b.hora_inicio, b.hora_fin)
      const key = `${sec.codigo}|${startRow}|${span}`
      let p = porKey.get(key)
      if (!p) { p = { key: `${d.key}-${key}`, sections: [], startRow, span, lane: 0, lanes: 1 }; porKey.set(key, p); orden.push(key) }
      if (!p.sections.some(s => s.id === sec.id)) p.sections.push(sec)
    }
    const placements = orden.map(k => porKey.get(k)!)
    asignarCarriles(placements)
    out[d.key] = placements
  }
  return out
}

// ── Componente principal ──────────────────────────────────────────────────────

interface Props {
  secciones: SeccionAsignada[]
  planificacionId: number
  onEdited: () => void | Promise<void>
  onRestaurado: () => void | Promise<void>
}

export default function HorarioWorkspace({ secciones, planificacionId, onEdited, onRestaurado }: Props) {
  const [filters, setFilters] = useState<Filters>({ carrera: '', semestre: '', tipo: '', texto: '' })
  const [selected, setSelected] = useState<SeccionAsignada | null>(null)
  const [conflictos, setConflictos] = useState<ConflictoActivo[]>([])

  const seccionPorId = useMemo(() => new Map(secciones.map(s => [s.id, s])), [secciones])

  const refrescarConflictos = useCallback(async () => {
    try { setConflictos(await getConflictos()) } catch { /* noop */ }
  }, [])
  useEffect(() => { refrescarConflictos() }, [refrescarConflictos, secciones])

  // Mantener la selección apuntando a la versión más reciente de la sección.
  useEffect(() => {
    if (selected) { const s = seccionPorId.get(selected.id); if (s && s !== selected) setSelected(s) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seccionPorId])

  async function handleMoved(sec: SeccionAsignada) {
    setSelected(sec)
    await onEdited()
    await refrescarConflictos()
  }

  const availableSems = useMemo(() => {
    if (!filters.carrera) return []
    const set = new Set<string>()
    for (const sec of secciones) for (const s of getSemestresForCarrera(sec, filters.carrera)) set.add(s)
    return Array.from(set).sort(compareSems)
  }, [secciones, filters.carrera])

  const filtered = useMemo(() => aplicarFiltros(secciones, filters), [secciones, filters])
  const placements = useMemo(() => buildPlacements(filtered), [filtered])
  const bodyHeight = SUB_BLOQUES.length * ROW_H

  return (
    <div className="flex gap-5 items-start">
      {/* ── Columna izquierda: panel de control ──────────────────────────── */}
      <aside className="w-[270px] shrink-0 space-y-4 sticky top-6">
        <VersionSelector planificacionId={planificacionId} onRestaurado={onRestaurado} />
        <FiltrosPanel
          filters={filters} setFilters={setFilters}
          availableSems={availableSems} total={filtered.length}
        />
        <Leyenda />
      </aside>

      {/* ── Columna central: grilla ──────────────────────────────────────── */}
      <section className="flex-1 min-w-0 space-y-4">
        <ConflictosActivos
          conflictos={conflictos}
          onSelectSeccion={(id) => { const s = seccionPorId.get(id); if (s) setSelected(s) }}
        />
        <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="flex" style={{ minWidth: 760 }}>
            <div className="w-16 shrink-0 border-r border-gray-200">
              <div style={{ height: HEADER_H }} className="bg-gray-50 border-b border-gray-200" />
              {SUB_BLOQUES.map((sb, i) => (
                <div key={sb.inicio} style={{ height: ROW_H }}
                  className={`px-2 flex flex-col justify-center items-end border-t border-gray-100
                    ${i % 2 === 1 ? 'bg-gray-50/40' : ''}`}>
                  <span className="text-[10px] font-semibold text-gray-500 tabular-nums leading-none">{sb.inicio}</span>
                </div>
              ))}
            </div>
            {DIAS.map(d => (
              <div key={d.key} className="flex-1 min-w-0 border-l border-gray-200 first:border-l-0">
                <div style={{ height: HEADER_H }}
                  className="bg-gray-50 text-gray-600 text-xs font-semibold flex items-center justify-center border-b border-gray-200">
                  {d.label}
                </div>
                <div className="relative" style={{ height: bodyHeight }}>
                  {SUB_BLOQUES.map((_, i) => (
                    <div key={i} style={{ top: i * ROW_H, height: ROW_H }}
                      className={`absolute inset-x-0 border-t border-gray-100 ${i % 2 === 1 ? 'bg-gray-50/40' : ''}`} />
                  ))}
                  {placements[d.key].map(p => (
                    <div key={p.key} className="absolute p-0.5 transition-all"
                      style={{ top: p.startRow * ROW_H, height: p.span * ROW_H,
                               left: `${(p.lane / p.lanes) * 100}%`, width: `${100 / p.lanes}%` }}>
                      <BloquePlacement
                        p={p} selectedId={selected?.id ?? null}
                        onSelect={(s) => setSelected(s === selected ? null : s)}
                      />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Columna derecha: detalle y acciones ──────────────────────────── */}
      <aside className="w-[340px] shrink-0 sticky top-6">
        {selected ? (
          <PanelDetalle sec={selected} onClose={() => setSelected(null)} onMoved={handleMoved} />
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl p-6 text-center shadow-sm">
            <SlidersHorizontal size={22} className="mx-auto mb-3 text-gray-300" />
            <p className="text-sm text-gray-500">Selecciona un bloque en la grilla para ver su detalle y moverlo.</p>
          </div>
        )}
      </aside>
    </div>
  )
}

// ── Bloque de la grilla ─────────────────────────────────────────────────────────

function BloquePlacement({
  p, selectedId, onSelect,
}: {
  p: Placement; selectedId: string | null; onSelect: (sec: SeccionAsignada) => void
}) {
  if (p.sections.length === 1) {
    const sec = p.sections[0]
    return <SeccionCard sec={sec} selected={selectedId === sec.id} onClick={() => onSelect(sec)} />
  }
  return (
    <div className="h-full rounded-md overflow-y-auto flex flex-col bg-white border border-gray-200">
      {p.sections.map((sec, idx) => {
        const c = TIPO_COLOR[sec.tipo]
        return (
          <button key={sec.id} onClick={() => onSelect(sec)}
            className={`w-full text-left px-1.5 py-1 text-xs transition-all shrink-0 ${c.card}
              ${idx > 0 ? `border-t ${c.border}` : ''}
              ${selectedId === sec.id ? `ring-2 ring-inset ${c.ring} shadow-sm` : 'hover:brightness-[0.97]'}`}>
            <span className="flex items-center gap-1 leading-tight">
              <span className="font-semibold truncate">{sec.codigo}-{sec.seccion}</span>
              <span className={`text-[8px] font-bold px-1 py-px rounded shrink-0 ${c.tag}`}>{sec.tipo}</span>
            </span>
            {idx === 0 && <span className="block truncate text-[10px] opacity-75 leading-tight">{sec.titulo}</span>}
            <span className="block truncate text-[10px] opacity-60 leading-tight">{sec.profesor}</span>
          </button>
        )
      })}
    </div>
  )
}

function SeccionCard({ sec, selected, onClick }: { sec: SeccionAsignada; selected: boolean; onClick: () => void }) {
  const c = TIPO_COLOR[sec.tipo]
  return (
    <button onClick={onClick}
      className={`h-full w-full text-left rounded-md px-1.5 py-1 text-xs transition-all flex flex-col justify-center overflow-hidden
        ${c.card} ${selected ? `ring-2 ring-inset ${c.ring} shadow-sm` : 'hover:brightness-[0.97]'}`}>
      <span className="flex items-center gap-1 leading-tight">
        <span className="font-semibold truncate">{sec.codigo}-{sec.seccion}</span>
        <span className={`text-[8px] font-bold px-1 py-px rounded shrink-0 ${c.tag}`}>{sec.tipo}</span>
      </span>
      <span className="block truncate text-[10px] opacity-75 leading-tight">{sec.titulo}</span>
      <span className="block truncate text-[10px] opacity-60 leading-tight">{sec.profesor}</span>
    </button>
  )
}

// ── Panel izquierdo: filtros ────────────────────────────────────────────────────

function FiltrosPanel({
  filters, setFilters, availableSems, total,
}: {
  filters: Filters
  setFilters: React.Dispatch<React.SetStateAction<Filters>>
  availableSems: string[]
  total: number
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3 shadow-sm">
      <div className="flex items-center gap-2">
        <SlidersHorizontal size={14} className="text-gray-400" />
        <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Filtros</h3>
        <span className="ml-auto text-[11px] text-gray-400 tabular-nums">{total} secc.</span>
      </div>

      <div className="flex items-center gap-2 border border-gray-200 rounded-lg px-2.5 py-1.5 focus-within:border-gray-400 transition-colors">
        <Search size={13} className="text-gray-400 shrink-0" />
        <input type="text" placeholder="Buscar…" value={filters.texto}
          onChange={e => setFilters(f => ({ ...f, texto: e.target.value }))}
          className="flex-1 text-xs text-gray-700 placeholder-gray-400 border-none outline-none bg-transparent min-w-0" />
        {filters.texto && <button onClick={() => setFilters(f => ({ ...f, texto: '' }))}><X size={12} className="text-gray-400 hover:text-gray-600" /></button>}
      </div>

      <Selector label="Carrera" value={filters.carrera}
        options={[{ v: '', l: 'Todas las carreras' }, ...CARRERAS.map(c => ({ v: c, l: c }))]}
        onChange={v => setFilters(f => ({ ...f, carrera: v, semestre: '' }))} />

      {filters.carrera && availableSems.length > 0 && (
        <Selector label="Semestre" value={filters.semestre}
          options={[{ v: '', l: 'Todos' }, ...availableSems.map(s => ({ v: s, l: `Semestre ${s}` }))]}
          onChange={v => setFilters(f => ({ ...f, semestre: v }))} />
      )}

      <div>
        <p className="text-[11px] font-medium text-gray-400 mb-1.5">Tipo</p>
        <div className="grid grid-cols-2 gap-1">
          <TipoBtn active={filters.tipo === ''} onClick={() => setFilters(f => ({ ...f, tipo: '' }))} cls="bg-gray-800 text-white">Todos</TipoBtn>
          {(['CLAS', 'AYUD', 'LABT'] as TipoSeccion[]).map(t => (
            <TipoBtn key={t} active={filters.tipo === t} onClick={() => setFilters(f => ({ ...f, tipo: t }))} cls={TIPO_COLOR[t].btnActive}>
              {TIPO_FILTER_LABEL[t]}
            </TipoBtn>
          ))}
        </div>
      </div>
    </div>
  )
}

function Selector({ label, value, options, onChange }: {
  label: string; value: string; options: { v: string; l: string }[]; onChange: (v: string) => void
}) {
  return (
    <div>
      <p className="text-[11px] font-medium text-gray-400 mb-1.5">{label}</p>
      <select value={value} onChange={e => onChange(e.target.value)}
        className="w-full text-xs text-gray-700 border border-gray-200 rounded-lg px-2.5 py-1.5 outline-none focus:border-gray-400 bg-white cursor-pointer">
        {options.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
      </select>
    </div>
  )
}

function TipoBtn({ active, onClick, cls, children }: { active: boolean; onClick: () => void; cls: string; children: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={`text-[11px] font-medium px-2 py-1.5 rounded-lg border transition-colors
        ${active ? cls : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:bg-gray-50'}`}>
      {children}
    </button>
  )
}

// ── Panel izquierdo: leyenda ────────────────────────────────────────────────────

function Leyenda() {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2.5">Leyenda</h3>
      <div className="space-y-1.5">
        {(['CLAS', 'AYUD', 'LABT'] as TipoSeccion[]).map(t => (
          <div key={t} className="flex items-center gap-2 text-xs text-gray-600">
            <span className={`inline-block w-3 h-3 rounded-sm ${TIPO_COLOR[t].legend}`} />
            {TIPO_LABEL[t]}
          </div>
        ))}
      </div>
      <p className="text-[10px] text-gray-400 mt-3 leading-relaxed">
        Cada fila es un sub-bloque de 50 min; la altura del curso indica su duración.
      </p>
    </div>
  )
}

// ── Panel izquierdo: selector de versión ────────────────────────────────────────

function VersionSelector({ planificacionId, onRestaurado }: { planificacionId: number; onRestaurado: () => void | Promise<void> }) {
  const [versiones, setVersiones] = useState<VersionInfo[]>([])
  const [cargando, setCargando] = useState(false)

  const refrescar = useCallback(async () => setVersiones(await listarVersiones(planificacionId)), [planificacionId])
  useEffect(() => { refrescar() }, [refrescar])

  async function cambiar(vid: string) {
    if (!vid) return
    setCargando(true)
    try { await cargarVersion(Number(vid)); await onRestaurado() } finally { setCargando(false) }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <div className="flex items-center gap-2 mb-2.5">
        <History size={14} className="text-gray-400" />
        <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Versión</h3>
        {cargando && <Loader2 size={12} className="animate-spin text-gray-400 ml-auto" />}
      </div>
      {versiones.length === 0 ? (
        <p className="text-[11px] text-gray-400">Sin versiones guardadas. Usa la pestaña Versiones.</p>
      ) : (
        <select onChange={e => cambiar(e.target.value)} defaultValue=""
          className="w-full text-xs text-gray-700 border border-gray-200 rounded-lg px-2.5 py-1.5 outline-none focus:border-gray-400 bg-white cursor-pointer">
          <option value="">Cargar una versión…</option>
          {versiones.map(v => (
            <option key={v.id} value={v.id}>{v.es_autosave ? '● Autoguardado' : v.nombre}</option>
          ))}
        </select>
      )}
    </div>
  )
}

// ── Panel derecho: detalle del bloque + mover ───────────────────────────────────

function PanelDetalle({
  sec, onClose, onMoved,
}: {
  sec: SeccionAsignada
  onClose: () => void
  onMoved: (sec: SeccionAsignada) => void | Promise<void>
}) {
  const [moveIdx, setMoveIdx] = useState<number | null>(null)
  const [candidatos, setCandidatos] = useState<BloqueValido[] | null>(null)
  const [cargando, setCargando] = useState(false)
  const [aplicando, setAplicando] = useState<number | null>(null)
  const [resultado, setResultado] = useState<{ tipo: string; motivo: string }[] | 'ok' | null>(null)
  const [error, setError] = useState('')
  const c = TIPO_COLOR[sec.tipo]

  // Al cambiar de sección, resetear el modo mover.
  useEffect(() => { setMoveIdx(null); setCandidatos(null); setResultado(null); setError('') }, [sec.id])

  async function abrirMover(idx: number) {
    setMoveIdx(idx); setCandidatos(null); setResultado(null); setError(''); setCargando(true)
    try { setCandidatos((await getBloquesValidos(sec.id, idx)).candidatos) }
    catch (e) { setError(e instanceof Error ? e.message : 'Error') }
    finally { setCargando(false) }
  }
  async function confirmar(destino: number) {
    if (moveIdx === null) return
    setAplicando(destino); setError('')
    try {
      const r = await postMover(sec.id, moveIdx, destino)
      setResultado(r.conflictos.length ? r.conflictos : 'ok')
      setMoveIdx(null); setCandidatos(null)
      await onMoved(r.seccion)
    } catch (e) { setError(e instanceof Error ? e.message : 'Error') }
    finally { setAplicando(null) }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className={`px-4 py-3 border-b border-gray-100 flex items-start justify-between gap-2 ${c.card.split(' ').filter(x => x.startsWith('bg-')).join(' ')}`}>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${c.tag}`}>{TIPO_LABEL[sec.tipo]}</span>
            <span className="text-sm font-semibold text-gray-900 truncate">{sec.codigo}-{sec.seccion}</span>
          </div>
          <p className="text-xs text-gray-600 mt-1 leading-snug">{sec.titulo}</p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-700 shrink-0"><X size={16} /></button>
      </div>

      <div className="p-4 space-y-3">
        <Campo label="Profesor" value={sec.profesor} />
        <div className="grid grid-cols-2 gap-3">
          <Campo label="Carreras" value={sec.carreras || '—'} />
          <Campo label="Semestres" value={sec.semestres || '—'} />
        </div>

        {resultado === 'ok' && (
          <div className="flex items-center gap-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-3 py-2">
            <Check size={13} /> Bloque movido sin conflictos.
          </div>
        )}
        {Array.isArray(resultado) && (
          <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
            <div className="flex items-center gap-2 font-medium mb-1"><AlertTriangle size={13} /> Movido, con conflictos:</div>
            <ul className="space-y-0.5 ml-5 list-disc">
              {resultado.map((cc, i) => <li key={i}><span className="font-semibold">{cc.tipo}:</span> {cc.motivo}</li>)}
            </ul>
          </div>
        )}
        {error && <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</div>}

        <div>
          <p className="text-[11px] font-medium text-gray-400 mb-2">Bloques asignados</p>
          <div className="space-y-1.5">
            {sec.bloques.map((b, i) => (
              <div key={i} className={`flex items-center justify-between gap-2 text-xs rounded-lg px-3 py-1.5
                ${moveIdx === i ? 'bg-blue-50 border border-blue-300' : 'bg-gray-50 border border-gray-100'}`}>
                <span className="text-gray-700">{DIAS_LABEL[b.dia as Dia]} · {b.hora_inicio}–{b.hora_fin}</span>
                <button onClick={() => (moveIdx === i ? setMoveIdx(null) : abrirMover(i))}
                  className="flex items-center gap-1 text-[11px] font-medium text-blue-700 hover:bg-blue-100 px-2 py-0.5 rounded transition-colors">
                  <Move size={11} /> {moveIdx === i ? 'Cancelar' : 'Mover'}
                </button>
              </div>
            ))}
          </div>
        </div>

        {moveIdx !== null && (
          <MinimapaMover cargando={cargando} candidatos={candidatos} aplicando={aplicando} onPick={confirmar} />
        )}
      </div>
    </div>
  )
}

function Campo({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] text-gray-400 font-medium">{label}</p>
      <p className="text-xs text-gray-800 mt-0.5 leading-snug">{value}</p>
    </div>
  )
}

// ── Minimapa de movimiento (5 días × horas, destinos verde/rojo) ─────────────────

const MINI_H = 15

function MinimapaMover({
  cargando, candidatos, aplicando, onPick,
}: {
  cargando: boolean
  candidatos: BloqueValido[] | null
  aplicando: number | null
  onPick: (destino: number) => void
}) {
  if (cargando) {
    return <div className="flex items-center gap-2 text-xs text-gray-500 pt-2"><Loader2 size={13} className="animate-spin" /> Calculando destinos…</div>
  }
  if (!candidatos) return null

  const porDia: Record<Dia, BloqueValido[]> = { L: [], M: [], X: [], J: [], V: [] }
  for (const c of candidatos) porDia[c.dia].push(c)
  const nValidos = candidatos.filter(c => c.estado === 'valido').length
  const bodyH = SUB_BLOQUES.length * MINI_H

  return (
    <div className="border-t border-gray-100 pt-3">
      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 mb-2">
        <p className="text-[11px] font-medium text-gray-600">Elige el destino</p>
        <span className="flex items-center gap-1 text-[10px] text-emerald-700"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-100 border border-emerald-500" /> válido ({nValidos})</span>
        <span className="flex items-center gap-1 text-[10px] text-red-600"><span className="w-2.5 h-2.5 rounded-sm bg-red-50 border border-red-400" /> conflicto</span>
      </div>
      <div className="rounded-lg border border-gray-200 overflow-hidden bg-white">
        <div className="flex">
          <div className="w-8 shrink-0 border-r border-gray-100">
            <div style={{ height: 16 }} className="bg-gray-50" />
            {SUB_BLOQUES.map((sb, i) => (
              <div key={i} style={{ height: MINI_H }} className={`flex items-center justify-end pr-1 ${i % 2 === 1 ? 'bg-gray-50/50' : ''}`}>
                <span className="text-[7px] text-gray-400 tabular-nums leading-none">{sb.inicio.slice(0, 2)}</span>
              </div>
            ))}
          </div>
          {DIAS.map(d => (
            <div key={d.key} className="flex-1 border-l border-gray-100 first:border-l-0 min-w-0">
              <div style={{ height: 16 }} className="bg-gray-50 flex items-center justify-center">
                <span className="text-[8px] font-semibold text-gray-500">{d.short}</span>
              </div>
              <div className="relative" style={{ height: bodyH }}>
                {SUB_BLOQUES.map((_, i) => (
                  <div key={i} style={{ top: i * MINI_H, height: MINI_H }} className={`absolute inset-x-0 border-t border-gray-50 ${i % 2 === 1 ? 'bg-gray-50/40' : ''}`} />
                ))}
                {porDia[d.key].map(c => {
                  const row = rowOf(c.hora_inicio), span = spanOf(c.hora_inicio, c.hora_fin)
                  if (row < 0) return null
                  const valido = c.estado === 'valido', busy = aplicando === c.bloque
                  return (
                    <button key={c.bloque} disabled={c.actual || aplicando !== null}
                      onClick={() => onPick(c.bloque)} title={c.actual ? 'Posición actual' : c.motivos.join(' · ')}
                      style={{ top: row * MINI_H + 1, height: span * MINI_H - 2 }}
                      className={`absolute inset-x-0.5 rounded-sm border text-[7px] flex items-center justify-center transition-colors
                        ${c.actual
                          ? 'bg-gray-800 border-gray-800 text-white cursor-default'
                          : valido
                            ? 'bg-emerald-100 border-emerald-500 hover:bg-emerald-200 text-emerald-800'
                            : 'bg-red-50 border-red-400 hover:bg-red-100 text-red-600'}`}>
                      {busy ? <Loader2 size={8} className="animate-spin" /> : c.actual ? '●' : ''}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
      <p className="text-[10px] text-gray-400 mt-1.5">Pasa el cursor por un destino en rojo para ver el motivo del conflicto.</p>
    </div>
  )
}

// ── Conflictos activos (barra persistente) ──────────────────────────────────────

const CONFLICTO_LABEL: Record<string, string> = {
  RD1: 'Tope de malla', RD2: 'Disponibilidad', RD3: 'Profesor duplicado', RD4: 'Sala saturada',
  RD6: 'Duración', RD7: 'Ayudantía < 12:30', RD8: 'Horario de minor', NRC: 'Componentes', intra: 'Solape interno',
}

function ConflictosActivos({ conflictos, onSelectSeccion }: { conflictos: ConflictoActivo[]; onSelectSeccion: (id: string) => void }) {
  const [abierto, setAbierto] = useState(true)
  if (conflictos.length === 0) {
    return (
      <div className="flex items-center gap-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-2.5">
        <ShieldCheck size={15} className="shrink-0" /> Sin conflictos activos en el horario.
      </div>
    )
  }
  return (
    <div className="border border-red-200 rounded-xl overflow-hidden shadow-sm">
      <button onClick={() => setAbierto(!abierto)} className="w-full flex items-center justify-between px-4 py-2.5 bg-red-50 hover:bg-red-100 transition-colors">
        <span className="flex items-center gap-2 text-sm font-semibold text-red-800">
          <AlertTriangle size={15} /> {conflictos.length} conflicto{conflictos.length !== 1 ? 's' : ''} activo{conflictos.length !== 1 ? 's' : ''}
        </span>
        <span className="text-[11px] text-red-600">{abierto ? 'ocultar' : 'ver'}</span>
      </button>
      {abierto && (
        <ul className="divide-y divide-red-100 bg-white max-h-56 overflow-y-auto">
          {conflictos.map((c, i) => (
            <li key={i} className="px-4 py-2.5">
              <div className="flex items-start gap-2">
                <span className="text-[10px] font-bold bg-red-100 text-red-700 px-1.5 py-0.5 rounded shrink-0 mt-0.5">
                  {CONFLICTO_LABEL[c.tipo] ?? c.tipo}
                </span>
                <div className="min-w-0">
                  <p className="text-xs text-gray-800 leading-relaxed">{c.motivo}</p>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {c.secciones.map(sid => (
                      <button key={sid} onClick={() => onSelectSeccion(sid)}
                        className="text-[10px] font-medium bg-gray-100 hover:bg-gray-200 text-gray-600 px-1.5 py-0.5 rounded transition-colors">
                        {sid}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
