import { create } from 'zustand'
import type { Project, Clip, SubtitleCue, Theme, PropTab, RenderResult } from '../types'
import * as api from '../api/editor'
import { parseSRT, parseASS } from '../utils/format'

interface Toast {
  id: number
  msg: string
  type: 'ok' | 'err'
}

interface EditorState {
  // ── Project ──
  pid: string | null
  project: Project | null
  selectedClip: string | null

  // ── Playback ──
  playbackTime: number
  playing: boolean
  loopA: number | null
  loopB: number | null

  // ── Subtitle ──
  subtitleCues: SubtitleCue[]

  // ── UI ──
  zoom: number
  snap: boolean
  theme: Theme
  propTab: PropTab
  sidebarTab: 'assets' | 'jobs' | 'templates'
  toasts: Toast[]
  rendering: boolean
  renderResult: RenderResult | null

  // ── Actions ──
  toast: (msg: string, type?: 'ok' | 'err') => void
  setTheme: (t: Theme) => void
  setPropTab: (t: PropTab) => void
  setSidebarTab: (t: 'assets' | 'jobs' | 'templates') => void
  setZoom: (z: number) => void
  toggleSnap: () => void
  setPlaybackTime: (t: number) => void
  setPlaying: (p: boolean) => void
  setLoopA: () => void
  setLoopB: () => void
  clearLoop: () => void
  selectClip: (id: string | null) => void

  // ── Project actions ──
  createProject: (name: string) => Promise<void>
  loadProject: (pid: string) => Promise<void>
  refreshProject: () => Promise<void>
  updateProjectProp: (key: string, value: unknown) => Promise<void>
  saveProject: () => Promise<void>
  undoAction: () => Promise<void>
  redoAction: () => Promise<void>

  // ── Asset/Clip actions ──
  uploadAssets: (files: FileList) => Promise<void>
  addToTimeline: (assetId: string) => Promise<void>
  deleteSelectedClip: () => Promise<void>
  splitAtPlayhead: () => Promise<void>
  addEffect: (type: string, value: number) => Promise<void>
  removeEffect: (idx: number) => Promise<void>

  // ── Subtitles ──
  loadSubtitleCues: () => Promise<void>

  // ── Render ──
  renderProject: () => Promise<void>
}

let _toastId = 0

export const useEditorStore = create<EditorState>((set, get) => ({
  // ── Initial State ──
  pid: null,
  project: null,
  selectedClip: null,
  playbackTime: 0,
  playing: false,
  loopA: null,
  loopB: null,
  subtitleCues: [],
  zoom: 40,
  snap: true,
  theme: 'default',
  propTab: 'project',
  sidebarTab: 'assets',
  toasts: [],
  rendering: false,
  renderResult: null,

  // ── UI Actions ──
  toast: (msg, type = 'ok') => {
    const id = ++_toastId
    set(s => ({ toasts: [...s.toasts, { id, msg, type }] }))
    setTimeout(() => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })), 3000)
  },

  setTheme: (theme) => {
    document.documentElement.dataset.theme = theme === 'default' ? '' : theme
    set({ theme })
  },

  setPropTab: (propTab) => set({ propTab }),
  setSidebarTab: (sidebarTab) => set({ sidebarTab }),
  setZoom: (zoom) => set({ zoom: Math.max(5, Math.min(200, zoom)) }),
  toggleSnap: () => set(s => ({ snap: !s.snap })),
  setPlaybackTime: (playbackTime) => set({ playbackTime }),
  setPlaying: (playing) => set({ playing }),

  setLoopA: () => {
    const t = get().playbackTime
    set({ loopA: t })
    get().toast('Loop A: ' + t.toFixed(1) + 's')
  },
  setLoopB: () => {
    const t = get().playbackTime
    set({ loopB: t })
    get().toast('Loop B: ' + t.toFixed(1) + 's')
  },
  clearLoop: () => {
    set({ loopA: null, loopB: null })
    get().toast('Loop gelöscht')
  },

  selectClip: (selectedClip) => {
    set({ selectedClip, propTab: selectedClip ? 'clip' : 'project' })
  },

  // ── Project Actions ──
  createProject: async (name) => {
    try {
      const project = await api.createProject(name)
      set({ pid: project.id, project, selectedClip: null })
      get().toast('Projekt erstellt: ' + name)
    } catch (e) {
      get().toast('Fehler: ' + (e as Error).message, 'err')
    }
  },

  loadProject: async (pid) => {
    try {
      const project = await api.getProject(pid)
      set({ pid, project, selectedClip: null })
      get().loadSubtitleCues()
    } catch (e) {
      get().toast('Laden fehlgeschlagen', 'err')
    }
  },

  refreshProject: async () => {
    const { pid } = get()
    if (!pid) return
    try {
      const project = await api.getProject(pid)
      set({ project })
      get().loadSubtitleCues()
    } catch { /* noop */ }
  },

  updateProjectProp: async (key, value) => {
    const { pid, project } = get()
    if (!pid || !project) return
    set({ project: { ...project, [key]: value } })
    if (key === 'name') {
      // Update displayed name immediately
    }
    try {
      await api.updateProject(pid, { [key]: value } as Partial<Project>)
    } catch { /* noop */ }
  },

  saveProject: async () => {
    const { pid } = get()
    if (!pid) return
    try {
      const r = await api.saveProject(pid)
      get().toast('Gespeichert: ' + r.file)
    } catch (e) {
      get().toast('Speichern fehlgeschlagen', 'err')
    }
  },

  undoAction: async () => {
    const { pid } = get()
    if (!pid) return
    try {
      const r = await api.undo(pid)
      if (r.success) {
        set({ project: r.project })
        get().toast('↩ Undo')
      }
    } catch { /* noop */ }
  },

  redoAction: async () => {
    const { pid } = get()
    if (!pid) return
    try {
      const r = await api.redo(pid)
      if (r.success) {
        set({ project: r.project })
        get().toast('↪ Redo')
      }
    } catch { /* noop */ }
  },

  // ── Asset / Clip Actions ──
  uploadAssets: async (files) => {
    const { pid } = get()
    if (!pid) {
      get().toast('Erst Projekt erstellen', 'err')
      return
    }
    for (const f of Array.from(files)) {
      try {
        const r = await api.uploadAsset(pid, f)
        get().toast('Asset: ' + r.filename)
      } catch (e) {
        get().toast('Upload: ' + (e as Error).message, 'err')
      }
    }
    await get().refreshProject()
  },

  addToTimeline: async (assetId) => {
    const { pid, project } = get()
    if (!pid || !project) return
    const asset = project.assets[assetId]
    if (!asset) return

    const trackMap: Record<string, string> = {
      video: 'video', audio: 'audio', image: 'video', subtitle: 'subtitle',
    }
    const track = trackMap[asset.type] || 'video'

    // Match subtitle duration to audio
    let dur = 0
    if (asset.type === 'subtitle') {
      const audioClip = project.clips.find(c => c.track === 'audio')
      dur = audioClip?.duration || project.duration || asset.duration || 300
    }

    try {
      await api.addClip(pid, assetId, track, -1, dur)
      await get().refreshProject()
      get().toast('Clip hinzugefügt: ' + asset.filename)
    } catch (e) {
      get().toast('Clip: ' + (e as Error).message, 'err')
    }
  },

  deleteSelectedClip: async () => {
    const { pid, selectedClip } = get()
    if (!pid || !selectedClip) return
    try {
      await api.deleteClip(pid, selectedClip)
      set({ selectedClip: null })
      await get().refreshProject()
      get().toast('Clip gelöscht')
    } catch { /* noop */ }
  },

  splitAtPlayhead: async () => {
    const { pid, selectedClip, playbackTime } = get()
    if (!pid || !selectedClip) return
    try {
      await api.splitClip(pid, selectedClip, playbackTime)
      await get().refreshProject()
      get().toast('Split ✂')
    } catch { /* noop */ }
  },

  addEffect: async (type, value) => {
    const { pid, selectedClip } = get()
    if (!pid || !selectedClip) return
    try {
      await api.addEffect(pid, selectedClip, type, value)
      await get().refreshProject()
    } catch { /* noop */ }
  },

  removeEffect: async (idx) => {
    const { pid, selectedClip } = get()
    if (!pid || !selectedClip) return
    try {
      await api.removeEffect(pid, selectedClip, idx)
      await get().refreshProject()
    } catch { /* noop */ }
  },

  // ── Subtitles ──
  loadSubtitleCues: async () => {
    const { pid, project } = get()
    if (!pid || !project) return
    const subClip = project.clips.find(c => c.track === 'subtitle')
    if (!subClip) {
      set({ subtitleCues: [] })
      return
    }
    const asset = project.assets[subClip.asset_id]
    if (!asset) return
    try {
      const r = await fetch(api.assetFileUrl(pid, subClip.asset_id))
      const text = await r.text()
      const ext = asset.filename.split('.').pop()?.toLowerCase()
      const cues = ext === 'ass' ? parseASS(text) : parseSRT(text)
      set({ subtitleCues: cues })
    } catch { /* noop */ }
  },

  // ── Render ──
  renderProject: async () => {
    const { pid } = get()
    if (!pid) return
    set({ rendering: true, renderResult: null })
    try {
      const r = await api.renderProject(pid)
      set({ renderResult: r, rendering: false })
      get().toast('Render fertig: ' + r.file)
      // Trigger download
      const a = document.createElement('a')
      a.href = api.renderDownloadUrl(r.file)
      a.download = r.file
      a.click()
    } catch (e) {
      set({ rendering: false })
      get().toast('Render Fehler: ' + (e as Error).message, 'err')
    }
  },
}))
