import { create } from 'zustand'
import type { Project, Clip, SubtitleCue, Theme, PropTab, RenderResult } from '../types'
import * as api from '../api/editor'
import { parseSRT, parseASS } from '../utils/format'

interface Toast { id: number; msg: string; type: 'ok' | 'err' }
interface ChatMsg { role: 'user' | 'ai'; text: string }

interface EditorState {
  // ── Project ──
  pid: string | null
  project: Project | null
  selectedClip: string | null
  // ── Playback ──
  playbackTime: number
  playing: boolean
  playSpeed: number
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
  // ── AI ──
  aiHistory: { role: string; content: string }[]
  aiMessages: ChatMsg[]
  aiStreaming: boolean

  // ── UI Actions ──
  toast: (msg: string, type?: 'ok' | 'err') => void
  setTheme: (t: Theme) => void
  setPropTab: (t: PropTab) => void
  setSidebarTab: (t: 'assets' | 'jobs' | 'templates') => void
  setZoom: (z: number) => void
  toggleSnap: () => void
  setPlaybackTime: (t: number) => void
  setPlaying: (p: boolean) => void
  setPlaySpeed: (s: number) => void
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

  // ── Asset actions ──
  uploadAssets: (files: FileList) => Promise<void>
  deleteAsset: (assetId: string) => Promise<void>

  // ── Clip actions ──
  addToTimeline: (assetId: string) => Promise<void>
  updateClipProp: (prop: string, val: unknown) => Promise<void>
  deleteSelectedClip: () => Promise<void>
  splitAtPlayhead: () => Promise<void>
  duplicateClip: () => Promise<void>

  // ── Effect actions ──
  addEffect: (type: string, params?: Record<string, unknown>) => Promise<void>
  removeEffect: (idx: number) => Promise<void>

  // ── Subtitles ──
  loadSubtitleCues: () => Promise<void>

  // ── Render ──
  renderProject: () => Promise<void>
  renderLoop: (assetId: string, loopCount: number, duration: number) => Promise<void>
  clearRenderResult: () => void

  // ── AI Chat ──
  sendAI: (msg: string) => Promise<void>

  // ── Templates ──
  quickTemplate: (type: string) => Promise<void>

  // ── Job Import (auto-create project if needed) ──
  importJobFromLibrary: (jobId: string, name: string) => Promise<void>
}

let _toastId = 0

const DEFAULT_EFFECT_PARAMS: Record<string, Record<string, unknown>> = {
  fade_in: { duration: 1 }, fade_out: { duration: 1 }, blur: { sigma: 5 },
  brightness: { value: 0.1 }, contrast: { value: 1.2 }, saturation: { value: 1.5 },
  rotate: { angle: 90 }, zoom: { factor: 1.3 },
  overlay_text: { text: 'Text', size: 48, color: 'white' },
}

export const useEditorStore = create<EditorState>((set, get) => ({
  // ── Initial State ──
  pid: null, project: null, selectedClip: null,
  playbackTime: 0, playing: false, playSpeed: 1,
  loopA: null, loopB: null, subtitleCues: [],
  zoom: 40, snap: true, theme: 'default',
  propTab: 'project', sidebarTab: 'assets',
  toasts: [], rendering: false, renderResult: null,
  aiHistory: [], aiMessages: [], aiStreaming: false,

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
  setPlaySpeed: (playSpeed) => set({ playSpeed }),
  setLoopA: () => { set({ loopA: get().playbackTime }); get().toast('Loop A: ' + get().playbackTime.toFixed(1) + 's') },
  setLoopB: () => { set({ loopB: get().playbackTime }); get().toast('Loop B: ' + get().playbackTime.toFixed(1) + 's') },
  clearLoop: () => { set({ loopA: null, loopB: null }); get().toast('Loop gelöscht') },
  selectClip: (selectedClip) => set({ selectedClip, propTab: selectedClip ? 'clip' : 'project' }),

  // ── Project Actions ──
  createProject: async (name) => {
    try {
      const project = await api.createProject(name)
      set({ pid: project.id, project, selectedClip: null })
      get().toast('Projekt erstellt: ' + name)
    } catch (e) { get().toast('Fehler: ' + (e as Error).message, 'err') }
  },
  loadProject: async (pid) => {
    try {
      const project = await api.getProject(pid)
      set({ pid, project, selectedClip: null })
      get().loadSubtitleCues()
    } catch { get().toast('Laden fehlgeschlagen', 'err') }
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
    // Optimistic local update
    set({ project: { ...project, [key]: value } as Project })
    try { await api.updateProject(pid, { [key]: value } as Partial<Project>) }
    catch { /* noop */ }
  },
  saveProject: async () => {
    const { pid } = get()
    if (!pid) return
    try {
      const r = await api.saveProject(pid)
      get().toast('Gespeichert: ' + r.saved)
    } catch { get().toast('Speichern fehlgeschlagen', 'err') }
  },
  undoAction: async () => {
    const { pid } = get()
    if (!pid) return
    try {
      const r = await api.undo(pid)
      if (r.success) { set({ project: r.project }); get().toast('↩ Undo') }
    } catch { /* noop */ }
  },
  redoAction: async () => {
    const { pid } = get()
    if (!pid) return
    try {
      const r = await api.redo(pid)
      if (r.success) { set({ project: r.project }); get().toast('↪ Redo') }
    } catch { /* noop */ }
  },

  // ── Asset Actions ──
  uploadAssets: async (files) => {
    const { pid } = get()
    if (!pid) { get().toast('Erst Projekt erstellen', 'err'); return }
    for (const f of Array.from(files)) {
      try {
        const r = await api.uploadAsset(pid, f)
        get().toast('Asset: ' + r.filename)
      } catch (e) { get().toast('Upload: ' + (e as Error).message, 'err') }
    }
    await get().refreshProject()
  },
  deleteAsset: async (assetId) => {
    const { pid } = get()
    if (!pid) return
    try {
      await api.deleteAsset(pid, assetId)
      await get().refreshProject()
      get().toast('Asset entfernt')
    } catch { get().toast('Entfernen fehlgeschlagen', 'err') }
  },

  // ── Clip Actions ──
  addToTimeline: async (assetId) => {
    const { pid, project } = get()
    if (!pid || !project) return
    const asset = project.assets[assetId]
    if (!asset) return
    const trackMap: Record<string, string> = { video: 'video', audio: 'audio', image: 'video', subtitle: 'subtitle' }
    const track = trackMap[asset.type] || 'video'
    let dur = 0
    if (asset.type === 'subtitle') {
      const audioClip = project.clips.find(c => c.track === 'audio')
      dur = audioClip?.duration || project.duration || asset.duration || 300
    }
    try {
      await api.addClip(pid, assetId, track, -1, dur)
      await get().refreshProject()
      get().toast('Clip: ' + asset.filename)
    } catch (e) { get().toast('Clip: ' + (e as Error).message, 'err') }
  },
  updateClipProp: async (prop, val) => {
    const { pid, selectedClip } = get()
    if (!pid || !selectedClip) return
    try {
      await api.updateClip(pid, selectedClip, { [prop]: val } as Partial<Clip>)
      await get().refreshProject()
    } catch (e) { get().toast('Update: ' + (e as Error).message, 'err') }
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
    const { pid, project, selectedClip, playbackTime } = get()
    if (!pid || !project) return
    // Find clip at playhead if none selected, or use selected
    let clipId = selectedClip
    if (!clipId) {
      const clip = project.clips.find(c => playbackTime >= c.start && playbackTime < c.end)
      if (!clip) { get().toast('Kein Clip bei Playhead', 'err'); return }
      clipId = clip.id
    }
    try {
      await api.splitClip(pid, clipId, playbackTime)
      await get().refreshProject()
      get().toast('Split ✂')
    } catch { get().toast('Split fehlgeschlagen', 'err') }
  },
  duplicateClip: async () => {
    const { pid, selectedClip, project } = get()
    if (!pid || !selectedClip || !project) return
    const clip = project.clips.find(c => c.id === selectedClip)
    if (!clip) return
    try {
      await api.addClip(pid, clip.asset_id, clip.track, clip.end + 0.1, clip.duration, {
        loop: clip.loop, volume: clip.volume, speed: clip.speed,
      })
      await get().refreshProject()
      get().toast('Clip dupliziert')
    } catch (e) { get().toast('Dup: ' + (e as Error).message, 'err') }
  },

  // ── Effect Actions ──
  addEffect: async (type, params) => {
    const { pid, selectedClip } = get()
    if (!pid || !selectedClip) return
    const p = params || DEFAULT_EFFECT_PARAMS[type] || {}
    try {
      await api.addEffect(pid, selectedClip, type, p)
      await get().refreshProject()
      get().toast('Effekt: ' + type)
    } catch { /* noop */ }
  },
  removeEffect: async (idx) => {
    const { pid, selectedClip } = get()
    if (!pid || !selectedClip) return
    try {
      await api.removeEffect(pid, selectedClip, idx)
      await get().refreshProject()
      get().toast('Effekt entfernt')
    } catch { /* noop */ }
  },

  // ── Subtitles ──
  loadSubtitleCues: async () => {
    const { pid, project } = get()
    if (!pid || !project) return
    const subClip = project.clips.find(c => c.track === 'subtitle')
    if (!subClip) { set({ subtitleCues: [] }); return }
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
    const { pid, project } = get()
    if (!pid || !project?.clips.length) { get().toast('Keine Clips zum Rendern', 'err'); return }
    set({ rendering: true, renderResult: null })
    try {
      const r = await api.renderProject(pid)
      set({ renderResult: r, rendering: false })
      get().toast(`✅ Gerendert: ${r.file} (${r.size_mb} MB)`)
      const a = document.createElement('a')
      a.href = api.renderDownloadUrl(r.file); a.download = r.file; a.click()
    } catch (e) {
      set({ rendering: false })
      get().toast('Render: ' + (e as Error).message, 'err')
    }
  },
  renderLoop: async (assetId, loopCount, duration) => {
    const { pid, project } = get()
    if (!pid || !project) return
    set({ rendering: true })
    try {
      const r = await api.renderLoop(pid, assetId, loopCount, duration, project.width, project.height)
      set({ renderResult: r, rendering: false })
      get().toast(`Loop gerendert: ${r.file} (${r.size_mb} MB)`)
      window.open(api.renderDownloadUrl(r.file), '_blank')
    } catch (e) {
      set({ rendering: false })
      get().toast('Loop: ' + (e as Error).message, 'err')
    }
  },
  clearRenderResult: () => set({ renderResult: null }),

  // ── AI Chat ──
  sendAI: async (msg) => {
    const { pid, aiHistory } = get()
    if (!pid) { get().toast('Erst Projekt erstellen', 'err'); return }
    const newHistory = [...aiHistory, { role: 'user', content: msg }]
    set({
      aiHistory: newHistory,
      aiMessages: [...get().aiMessages, { role: 'user', text: msg }, { role: 'ai', text: '⏳ Denke nach...' }],
      aiStreaming: true,
    })
    let full = ''
    try {
      for await (const chunk of api.streamAIChat(pid, msg, newHistory)) {
        full += chunk
        set(s => {
          const msgs = [...s.aiMessages]
          msgs[msgs.length - 1] = { role: 'ai', text: full }
          return { aiMessages: msgs }
        })
      }
      set(s => ({
        aiHistory: [...s.aiHistory, { role: 'assistant', content: full }],
        aiStreaming: false,
      }))
      // AI might have changed project
      await get().refreshProject()
    } catch (e) {
      set(s => {
        const msgs = [...s.aiMessages]
        msgs[msgs.length - 1] = { role: 'ai', text: '❌ Fehler: ' + (e as Error).message }
        return { aiMessages: msgs, aiStreaming: false }
      })
    }
  },

  // ── Templates ──
  quickTemplate: async (type) => {
    const { pid, createProject, updateProjectProp, setSidebarTab, toast } = get()
    if (!pid) {
      const nameMap: Record<string, string> = {
        loop: 'Loop Video', karaoke: 'Karaoke Video', slideshow: 'Slideshow',
        music_video: 'Musik Video', vertical: 'Vertical Video',
      }
      await createProject(nameMap[type] || 'Video')
    }
    const formats: Record<string, [number, number, number]> = {
      vertical: [1080, 1920, 30], karaoke: [1920, 1080, 30],
      music_video: [1920, 1080, 30], loop: [1920, 1080, 30],
      slideshow: [1920, 1080, 30],
    }
    const [w, h, fps] = formats[type] || [1920, 1080, 30]
    await updateProjectProp('width', w)
    await updateProjectProp('height', h)
    await updateProjectProp('fps', fps)
    setSidebarTab('assets')
    toast('Vorlage: ' + type + ' — lade jetzt Assets hoch')
  },

  // ── Job Import (auto-creates project if none exists, like original) ──
  importJobFromLibrary: async (jobId, name) => {
    let { pid, toast, refreshProject } = get()
    if (!pid) {
      // Auto-create project with job name
      try {
        const project = await api.createProject(name || jobId)
        set({ pid: project.id, project, selectedClip: null })
        pid = project.id
        toast('Projekt erstellt: ' + (name || jobId))
      } catch (e) { toast('Projekt erstellen: ' + (e as Error).message, 'err'); return }
    }
    try {
      await api.importJob(pid, jobId)
      await refreshProject()
      toast(`Assets aus Job importiert: ${name}`)
    } catch (e) { toast('Import: ' + (e as Error).message, 'err') }
  },
}))
