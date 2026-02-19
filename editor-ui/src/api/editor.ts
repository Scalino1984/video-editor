import type { Project, Clip, RenderResult, SavedProject, JobItem } from '../types'

const B = import.meta.env.VITE_API_URL || window.location.origin

// ── Projects ──
export async function listProjects(): Promise<Project[]> {
  const r = await fetch(`${B}/api/editor/projects`)
  return r.json()
}

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

export async function saveProject(pid: string): Promise<{ saved: string }> {
  const r = await fetch(`${B}/api/editor/projects/${pid}/save`, { method: 'POST' })
  return r.json()
}

export async function listSavedProjects(): Promise<SavedProject[]> {
  const r = await fetch(`${B}/api/editor/saved-projects`)
  return r.json()
}

export async function loadSavedProject(filename: string): Promise<Project> {
  const r = await fetch(`${B}/api/editor/load-project/${encodeURIComponent(filename)}`, { method: 'POST' })
  return r.json()
}

export function apiBase(): string { return B }

// ── Assets ──
export async function uploadAsset(pid: string, file: File): Promise<{ id: string; filename: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${B}/api/editor/projects/${pid}/assets`, { method: 'POST', body: fd })
  return r.json()
}

export async function deleteAsset(pid: string, assetId: string): Promise<void> {
  await fetch(`${B}/api/editor/projects/${pid}/assets/${assetId}`, { method: 'DELETE' })
}

export function assetFileUrl(pid: string, assetId: string): string {
  return `${B}/api/editor/projects/${pid}/assets/${assetId}/file`
}

export function assetThumbUrl(pid: string, assetId: string): string {
  return `${B}/api/editor/projects/${pid}/assets/${assetId}/thumb`
}

// ── Clips ──
export async function addClip(
  pid: string, assetId: string, track: string, start = -1, duration = 0,
  extra: Record<string, unknown> = {},
): Promise<{ id: string }> {
  const fd = new FormData()
  fd.append('asset_id', assetId)
  fd.append('track', track)
  fd.append('start', String(start))
  fd.append('duration', String(duration))
  for (const [k, v] of Object.entries(extra)) fd.append(k, String(v))
  const r = await fetch(`${B}/api/editor/projects/${pid}/clips`, { method: 'POST', body: fd })
  return r.json()
}

export async function updateClip(pid: string, clipId: string, data: Partial<Clip>): Promise<Clip> {
  const r = await fetch(`${B}/api/editor/projects/${pid}/clips/${clipId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return r.json()
}

export async function deleteClip(pid: string, clipId: string): Promise<void> {
  await fetch(`${B}/api/editor/projects/${pid}/clips/${clipId}`, { method: 'DELETE' })
}

export async function splitClip(pid: string, clipId: string, atTime: number): Promise<{ clip1: Clip; clip2: Clip }> {
  const r = await fetch(`${B}/api/editor/projects/${pid}/clips/${clipId}/split?at_time=${atTime}`, { method: 'POST' })
  return r.json()
}

// ── Effects (JSON body, not FormData) ──
export async function addEffect(pid: string, clipId: string, type: string, params: Record<string, unknown> = {}): Promise<void> {
  await fetch(`${B}/api/editor/projects/${pid}/clips/${clipId}/effects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, params }),
  })
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
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail || err.message || 'Render failed')
  }
  return r.json()
}

export async function renderLoop(
  pid: string, assetId: string, loopCount: number, duration: number, width = 1920, height = 1080,
): Promise<RenderResult> {
  const fd = new FormData()
  fd.append('asset_id', assetId)
  fd.append('loop_count', String(loopCount))
  fd.append('duration', String(duration))
  fd.append('width', String(width))
  fd.append('height', String(height))
  const r = await fetch(`${B}/api/editor/projects/${pid}/render-loop`, { method: 'POST', body: fd })
  if (!r.ok) throw new Error('Loop render failed')
  return r.json()
}

export function renderDownloadUrl(file: string): string {
  return `${B}/api/editor/renders/${encodeURIComponent(file)}`
}

// ── Import ──
export async function importJob(pid: string, jobId: string): Promise<void> {
  await fetch(`${B}/api/editor/projects/${pid}/import-job/${jobId}`, { method: 'POST' })
}

export async function listLibrary(limit = 100): Promise<{ items: JobItem[] }> {
  const r = await fetch(`${B}/api/library?limit=${limit}`)
  return r.json()
}

// ── AI Chat (SSE streaming) ──
export async function* streamAIChat(
  pid: string, message: string, history: { role: string; content: string }[],
): AsyncGenerator<string> {
  const resp = await fetch(`${B}/api/editor/projects/${pid}/ai-chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  })
  const reader = resp.body?.getReader()
  if (!reader) return
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim()
        if (data === '[DONE]') return
        try { const j = JSON.parse(data); if (j.text) yield j.text } catch { /* skip */ }
      }
    }
  }
}
