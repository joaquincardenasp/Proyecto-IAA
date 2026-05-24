import type { SolveResult, StatusResponse } from '../types'

const BASE = '/api'

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

export const EXPORT_URL = `${BASE}/export`
