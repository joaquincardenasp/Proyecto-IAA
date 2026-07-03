import type {
  SolveResult,
  StatusResponse,
  BloquesValidosResponse,
  MoverResponse,
  DecisionSeccion,
} from '../types'

// En desarrollo: BASE = '/api'  →  Vite proxea a http://localhost:8000/api
// En producción: BASE = 'https://tu-backend.onrender.com/api'
//   (Render Static Site → Environment Variable: VITE_API_BASE_URL=https://tu-backend.onrender.com)
const BASE = `${import.meta.env.VITE_API_BASE_URL ?? ''}/api`

export async function uploadFiles(files: File[]): Promise<{ uploaded: string[] }> {
  const fd = new FormData()
  files.forEach(f => fd.append('files', f))
  const r = await fetch(`${BASE}/upload`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error('Error al subir archivos')
  return r.json()
}

/** Lanza el solver con los parámetros por defecto del backend. */
export async function postSolve(): Promise<void> {
  const r = await fetch(`${BASE}/solve`, {
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
  const r = await fetch(`${BASE}/status`)
  return r.json()
}

export async function getResults(): Promise<SolveResult> {
  const r = await fetch(`${BASE}/results`)
  if (!r.ok) throw new Error('Resultados no disponibles')
  return r.json()
}

export async function getBloquesValidos(
  secId: string,
  indice: number,
): Promise<BloquesValidosResponse> {
  const r = await fetch(`${BASE}/editar/bloques-validos`, {
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
  const r = await fetch(`${BASE}/editar/mover`, {
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
  const r = await fetch(`${BASE}/decisiones/${ruta}`, {
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

export const EXPORT_URL = `${BASE}/export`
