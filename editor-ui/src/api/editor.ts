import type { Project, RenderResult, SavedProject, JobItem } from '../types'

// In dev mode, Vite proxy handles /api → localhost:8000
// In production standalone, set VITE_API_URL or default to same origin
const B = import.meta.env.VITE_API_URL || window.location.origin

// ── Projects ──
export async function createProject(name: string): Promise<Project> {
  const r = await fetch(`${B}/api/editor/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ name }),
  })
  return r.json()
}

export async function getProject(pid: string): Promise<Project> {
  const r = await fetch(`${B}/api/editor/projects/${pid}`)
  return r.json()
}

export async function updateProject(pid: string, data: Partial<Project>): Promise<void> {
  await fetch(`${B}/api/editor/projects/${pid}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function saveProject(pid: string): Promise<{ file: string }> {
  const r = await fetch(`${B}/api/editor/projects/${pid}/save`, { method: 'POST' })
  return r.json()
}

export async function listSavedProjects(): Promise<SavedProject[]> {
  const r = await fetch(`${B}/api/editor/saved-projects`)
  return r.json()
}

export async function loadSavedProject(filename: string): Promise<Project> {
  const r = await fetch(`${B}/api/editor/load-project/${encodeURIComponent(filename)}`)
  return r.json()
}

// ── Assets ──
export async function uploadAsset(pid: string, file: File): Promise<{ id: string; filename: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${B}/api/editor/projects/${pid}/assets`, { method: 'POST', body: fd })
  return r.json()
}

export function assetFileUrl(pid: string, assetId: string): string {
  return `${B}/api/editor/projects/${pid}/assets/${assetId}/file`
}

export function assetThumbUrl(pid: string, assetId: string): string {
  return `${B}/api/editor/projects/${pid}/assets/${assetId}/thumb`
}

// ── Clips ──
export async function addClip(
  pid: string,
  assetId: string,
  track: string,
  start = -1,
  duration = 0,
): Promise<{ id: string }> {
  const fd = new FormData()
  fd.append('asset_id', assetId)
  fd.append('track', track)
  fd.append('start', String(start))
  fd.append('duration', String(duration))
  const r = await fetch(`${B}/api/editor/projects/${pid}/clips`, { method: 'POST', body: fd })
  return r.json()
}

export async function deleteClip(pid: string, clipId: string): Promise<void> {
  await fetch(`${B}/api/editor/projects/${pid}/clips/${clipId}`, { method: 'DELETE' })
}

export async function splitClip(pid: string, clipId: string, atTime: number): Promise<void> {
  await fetch(`${B}/api/editor/projects/${pid}/clips/${clipId}/split?at_time=${atTime}`, { method: 'POST' })
}

// ── Effects ──
export async function addEffect(
  pid: string,
  clipId: string,
  type: string,
  value: number,
): Promise<void> {
  const fd = new FormData()
  fd.append('type', type)
  fd.append('value', String(value))
  await fetch(`${B}/api/editor/projects/${pid}/clips/${clipId}/effects`, { method: 'POST', body: fd })
}

export async function removeEffect(pid: string, clipId: string, idx: number): Promise<void> {
  await fetch(`${B}/api/editor/projects/${pid}/clips/${clipId}/effects/${idx}`, { method: 'DELETE' })
}

// ── Undo / Redo ──
export async function undo(pid: string): Promise<{ success: boolean; project: Project }> {
  const r = await fetch(`${B}/api/editor/projects/${pid}/undo`, { method: 'POST' })
  return r.json()
}

export async function redo(pid: string): Promise<{ success: boolean; project: Project }> {
  const r = await fetch(`${B}/api/editor/projects/${pid}/redo`, { method: 'POST' })
  return r.json()
}

// ── Render ──
export async function renderProject(pid: string): Promise<RenderResult> {
  const r = await fetch(`${B}/api/editor/projects/${pid}/render`, { method: 'POST' })
  return r.json()
}

export function renderDownloadUrl(file: string): string {
  return `${B}/api/editor/renders/${file}`
}

// ── Import ──
export async function importJob(pid: string, jobId: string): Promise<void> {
  await fetch(`${B}/api/editor/projects/${pid}/import-job/${jobId}`, { method: 'POST' })
}

export async function listLibrary(limit = 100): Promise<{ items: JobItem[] }> {
  const r = await fetch(`${B}/api/library?limit=${limit}`)
  return r.json()
}
