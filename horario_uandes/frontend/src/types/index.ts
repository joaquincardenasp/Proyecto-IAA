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
  semestres: string 
  tentativa?: boolean; 
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
  tipo: string          // "RD1" | "RD3" | "RD4" | "RB1" | ... | "RB4"
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

// ── Diagnóstico (cuando no hay horario completo factible) ──────────────────────

export type EstadoSolve = 'FACTIBLE' | 'PARCIAL' | 'INFEASIBLE'

export interface Sugerencia {
  causa: string                    // "2mas1_sin_par" | "RD2" | "contencion" | ...
  severidad: 'alta' | 'media'
  mensaje: string
  acciones: string[]
  secciones: string[]
  profesores: string[]
  bloques: string[]
}

export interface DiagnosticoUnidad {
  carrera: string
  semestre: string
  causa_principal: string
  sugerencias: Sugerencia[]
}

export interface DiagnosticoResult {
  unidades: DiagnosticoUnidad[]
}

export interface SolveResult {
  estado: EstadoSolve
  metricas?: MetricasResult
  secciones: SeccionAsignada[]
  reporte?: ReporteDetallado
  diagnostico?: DiagnosticoResult
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
export interface BloqueCatalogo {
  idx: number
  dia: Dia
  hora_inicio: string
  hora_fin: string
  tipo: '1h' | '2h' | '3h'
  es_estandar: boolean
}

export interface ViolacionDura {
  tipo: string
  secciones: string[]
  bloques: number[]
  mensaje: string
}

export interface ValidarHorarioResponse {
  factible: boolean
  violaciones_duras: ViolacionDura[]
  penalizacion_blanda: number
}