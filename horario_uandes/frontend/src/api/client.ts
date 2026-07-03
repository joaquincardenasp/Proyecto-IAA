import type {
  SolveResult,
  StatusResponse,
  BloquesValidosResponse,
  MoverResponse,
  DecisionSeccion,
  ConflictoActivo,
  PlanificacionInfo,
  VersionInfo,
} from '../types'

// En desarrollo: BASE = '/api'  →  Vite proxea a http://localhost:8000/api
// En producción: BASE = 'https://tu-backend.onrender.com/api'
//   (Render Static Site → Environment Variable: VITE_API_BASE_URL=https://tu-backend.onrender.com)
const BASE = `${import.meta.env.VITE_API_BASE_URL ?? ''}/api`

// ── Sesión / token ──────────────────────────────────────────────────────────────
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? ''
export const AUTH_ENABLED = !!GOOGLE_CLIENT_ID

let _token: string | null = localStorage.getItem('authToken')
export function setToken(t: string | null) {
  _token = t
  if (t) localStorage.setItem('authToken', t)
  else localStorage.removeItem('authToken')
}
export function getToken() { return _token }

/** fetch que inyecta el token de sesión en todas las peticiones a la API. */
function afetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {})
  if (_token) headers.set('Authorization', `Bearer ${_token}`)
  return fetch(input, { ...init, headers })
}

// ── Auth ────────────────────────────────────────────────────────────────────────

export interface Usuario { email: string; name: string; picture: string }

export async function loginGoogle(credential: string): Promise<Usuario> {
  const r = await fetch(`${BASE}/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential }),
  })
  if (!r.ok) {
    const e = await r.json().catch(() => ({}))
    throw new Error((e as { detail?: string }).detail ?? 'Error al iniciar sesión')
  }
  const data = await r.json()
  setToken(data.token)
  return data.user as Usuario
}

/** Devuelve el usuario de la sesión actual, o null si no hay/expiró. */
export async function getMe(): Promise<Usuario | null> {
  if (!_token) return null
  const r = await afetch(`${BASE}/auth/me`)
  if (!r.ok) { setToken(null); return null }
  return (await r.json()).user as Usuario
}

export function logout() { setToken(null) }

export async function uploadFiles(files: File[]): Promise<{ uploaded: string[] }> {
  const fd = new FormData()
  files.forEach(f => fd.append('files', f))
  const r = await afetch(`${BASE}/upload`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error('Error al subir archivos')
  return r.json()
}

/** Lanza el solver con los parámetros por defecto del backend. */
export async function postSolve(): Promise<void> {
  const r = await afetch(`${BASE}/solve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail ?? `Error ${r.status}`)
  }
}

export async function getStatus(): Promise<StatusResponse> {
  const r = await afetch(`${BASE}/status`)
  return r.json()
}

export async function getResults(): Promise<SolveResult> {
  const r = await afetch(`${BASE}/results`)
  if (!r.ok) throw new Error('Resultados no disponibles')
  return r.json()
}

export async function getBloquesValidos(
  secId: string,
  indice: number,
): Promise<BloquesValidosResponse> {
  const r = await afetch(`${BASE}/editar/bloques-validos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sec_id: secId, indice }),
  })
  if (!r.ok) throw new Error('No se pudieron obtener los bloques válidos')
  return r.json()
}

export async function postMover(
  secId: string,
  indice: number,
  destino: number,
): Promise<MoverResponse> {
  const r = await afetch(`${BASE}/editar/mover`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sec_id: secId, indice, destino }),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail ?? `Error ${r.status}`)
  }
  return r.json()
}

async function _postDecision(
  ruta: 'distribucion' | 'duracion',
  secId: string,
  opcion: string,
): Promise<DecisionSeccion[]> {
  const r = await afetch(`${BASE}/decisiones/${ruta}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sec_id: secId, opcion }),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail ?? `Error ${r.status}`)
  }
  return r.json()
}

export const setDistribucion = (secId: string, opcion: string) =>
  _postDecision('distribucion', secId, opcion)
export const setDuracion = (secId: string, opcion: string) =>
  _postDecision('duracion', secId, opcion)

export async function getConflictos(): Promise<ConflictoActivo[]> {
  const r = await afetch(`${BASE}/conflictos`)
  if (!r.ok) return []
  return r.json()
}

// ── Planificaciones y versiones ────────────────────────────────────────────────

export async function crearPlanificacion(
  nombre: string, maestro: File, salas: File | null,
): Promise<PlanificacionInfo> {
  const fd = new FormData()
  fd.append('nombre', nombre)
  fd.append('maestro', maestro)
  if (salas) fd.append('salas', salas)
  const r = await afetch(`${BASE}/planificaciones`, { method: 'POST', body: fd })
  if (!r.ok) {
    const e = await r.json().catch(() => ({}))
    throw new Error((e as { detail?: string }).detail ?? 'Error al crear la planificación')
  }
  return r.json()
}

export async function listarPlanificaciones(): Promise<PlanificacionInfo[]> {
  const r = await afetch(`${BASE}/planificaciones`)
  if (!r.ok) return []
  return r.json()
}

export async function activarPlanificacion(id: number): Promise<void> {
  const r = await afetch(`${BASE}/planificaciones/${id}/activar`, { method: 'POST' })
  if (!r.ok) throw new Error('No se pudo activar la planificación')
}

export async function eliminarPlanificacion(id: number): Promise<void> {
  await afetch(`${BASE}/planificaciones/${id}`, { method: 'DELETE' })
}

export async function guardarVersion(pid: number, nombre: string): Promise<VersionInfo> {
  const r = await afetch(`${BASE}/planificaciones/${pid}/versiones`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nombre }),
  })
  if (!r.ok) {
    const e = await r.json().catch(() => ({}))
    throw new Error((e as { detail?: string }).detail ?? 'Error al guardar la versión')
  }
  return r.json()
}

export async function listarVersiones(pid: number): Promise<VersionInfo[]> {
  const r = await afetch(`${BASE}/planificaciones/${pid}/versiones`)
  if (!r.ok) return []
  return r.json()
}

export async function cargarVersion(vid: number): Promise<void> {
  const r = await afetch(`${BASE}/versiones/${vid}/cargar`, { method: 'POST' })
  if (!r.ok) throw new Error('No se pudo cargar la versión')
}

export async function eliminarVersion(vid: number): Promise<void> {
  await afetch(`${BASE}/versiones/${vid}`, { method: 'DELETE' })
}

export const EXPORT_URL = `${BASE}/export`

/** Descarga el Excel con el token de sesión (navegación directa no lo llevaría). */
export async function descargarExcel(): Promise<void> {
  const r = await afetch(`${BASE}/export`)
  if (!r.ok) throw new Error('No se pudo descargar el Excel')
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'horario_generado.xlsx'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
