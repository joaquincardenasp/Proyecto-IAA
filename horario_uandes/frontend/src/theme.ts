import type { TipoSeccion } from './types'

// ── Colores por tipo de sección (bloques del horario) ──────────────────────────
// Paleta nítida y profesional; texto oscuro sobre fondo tenue → WCAG AA/AAA.
//   Cátedra = azul marino · Ayudantía = verde esmeralda · Lab/Taller = violeta

export const TIPO_COLOR: Record<
  TipoSeccion,
  {
    card: string      // fondo + borde izquierdo + texto del bloque
    border: string    // separador entre secciones apiladas
    tag: string       // chip de tipo
    dot: string       // punto/relleno sólido
    btnActive: string // botón de filtro activo
    legend: string    // muestra de color en la leyenda
    ring: string      // anillo de selección
  }
> = {
  CLAS: {
    card: 'bg-blue-50 border-l-[3px] border-blue-700 text-blue-900',
    border: 'border-blue-200',
    tag: 'bg-blue-100 text-blue-800',
    dot: 'bg-blue-700',
    btnActive: 'bg-blue-700 text-white border-blue-700',
    legend: 'bg-blue-700',
    ring: 'ring-blue-500',
  },
  AYUD: {
    card: 'bg-emerald-50 border-l-[3px] border-emerald-600 text-emerald-900',
    border: 'border-emerald-200',
    tag: 'bg-emerald-100 text-emerald-800',
    dot: 'bg-emerald-600',
    btnActive: 'bg-emerald-600 text-white border-emerald-600',
    legend: 'bg-emerald-600',
    ring: 'ring-emerald-500',
  },
  LABT: {
    card: 'bg-violet-50 border-l-[3px] border-violet-600 text-violet-900',
    border: 'border-violet-200',
    tag: 'bg-violet-100 text-violet-800',
    dot: 'bg-violet-600',
    btnActive: 'bg-violet-600 text-white border-violet-600',
    legend: 'bg-violet-600',
    ring: 'ring-violet-500',
  },
}

export const TIPO_LABEL: Record<TipoSeccion, string> = {
  CLAS: 'Cátedra',
  AYUD: 'Ayudantía',
  LABT: 'Lab / Taller',
}
