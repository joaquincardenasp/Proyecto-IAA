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

export interface DecisionSeccion {
  sec_id: string
  codigo: string
  titulo: string
  seccion: string
  profesor: string
  tipo: 'distribucion' | 'duracion_1h'
  opciones: string[]        // ["3-juntas","2+1"] | ["1h","2h"]
  actual: string            // opción vigente ("" si aún no se elige)
  requerida: boolean        // true = bloquea la programación
  mensaje: string
}

export interface SolveResult {
  estado: EstadoSolve
  metricas?: MetricasResult
  secciones: SeccionAsignada[]
  reporte?: ReporteDetallado
  diagnostico?: DiagnosticoResult
  decisiones: DecisionSeccion[]
}

export interface StatusResponse {
  status: SolverStatus
  progress: string
  error: string
}

// ── Edición manual (click-para-mover) ──────────────────────────────────────────

export interface BloqueValido {
  bloque: number
  dia: Dia
  hora_inicio: string
  hora_fin: string
  es_helper: boolean
  actual: boolean
  estado: 'valido' | 'conflicto'
  motivos: string[]
}

export interface BloquesValidosResponse {
  sec_id: string
  indice: number
  candidatos: BloqueValido[]
}

export interface ConflictoItem {
  tipo: string
  motivo: string
}

export interface MoverResponse {
  sec_id: string
  seccion: SeccionAsignada
  conflictos: ConflictoItem[]
}

export interface ConflictoActivo {
  tipo: string
  motivo: string
  secciones: string[]
}

// ── Persistencia: planificaciones y versiones ─────────────────────────────────

export interface PlanificacionInfo {
  id: number
  nombre: string
  creada: string
  actualizada: string
  maestro_nombre: string
  salas_nombre: string
  n_versiones: number
  activa: boolean
  tiene_horario: boolean
  estado_horario: string   // FACTIBLE | PARCIAL | INFEASIBLE | ""
  n_secciones: number
  n_conflictos: number
}

export interface VersionInfo {
  id: number
  planificacion_id: number
  nombre: string
  creada: string
  es_autosave: boolean
}

export interface SolveParams {
  carreras: string[]
  n_generaciones: number
  pop_size: number
  tiempo_limite_cpsat: number
  seed: number
}
