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

export interface SolveResult {
  metricas: MetricasResult
  secciones: SeccionAsignada[]
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
