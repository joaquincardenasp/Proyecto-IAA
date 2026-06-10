export type Dia = 'L' | 'M' | 'X' | 'J' | 'V'
export type TipoSeccion = 'CLAS' | 'AYUD' | 'LABT'
export type SolverStatus = 'idle' | 'running' | 'ready' | 'error'

export interface BloqueAsignado {
  dia: Dia
  hora_inicio: string
  hora_fin: string
  tipo_bloque: '2h' | '3h'
}

export interface SeccionAsignada {
  id: string
  codigo: string
  titulo: string
  seccion: string
  tipo: TipoSeccion
  profesor: string
  bloques: BloqueAsignado[]
  carreras: string   // "Plan Común · ICI · ..."
  semestres: string  // "1 · 2 · ..."
}

export interface MetricasResult {
  fitness_cpsat: number
  fitness_ga: number
  mejora_pct: number
  n_secciones: number
  n_bloques_totales: number
  estado_cpsat: string
}

export interface SeccionRef {
  id: string
  codigo: string
  titulo: string
  seccion: string
  tipo: string   // CLAS | AYUD | LABT
}

export interface ViolacionItem {
  tipo: string          // "RD1" | "RD3" | "RD4" | "RB1" | ... | "RB5"
  descripcion: string   // label corto: "Tope de malla", "Conflicto de profesor", ...
  mensaje: string       // descripción completa legible
  secciones: SeccionRef[]
  bloques: string[]     // ["Martes 10:30-12:20", ...]
  contexto: string      // "ICI · semestre 5", "Prof. Juan Pérez", ...
  penalizacion: number | null
}

export interface ResumenReporte {
  total_duras: number
  total_blandas: number
  por_tipo_dura: Record<string, number>
  por_tipo_blanda: Record<string, number>
  penalizacion_total: number
  penalizacion_por_rb: Record<string, number>
}

export interface ReporteDetallado {
  resumen: ResumenReporte
  violaciones_duras: ViolacionItem[]
  violaciones_blandas: ViolacionItem[]
}

export interface SolveResult {
  metricas: MetricasResult
  secciones: SeccionAsignada[]
  reporte?: ReporteDetallado
}

export interface StatusResponse {
  status: SolverStatus
  progress: string
  error: string
}

export interface SolveParams {
  carreras: string[]
  n_generaciones: number
  pop_size: number
  tiempo_limite_cpsat: number
  seed: number
}
