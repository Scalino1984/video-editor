import { useRef, useEffect, useCallback, useState } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import { useWaveform } from '../../hooks/useWaveform'
import { fmt } from '../../utils/format'
import { TRACK_COLORS, TRACK_ORDER } from '../../types'
import * as api from '../../api/editor'
import './Timeline.css'

interface TimelineProps { seek: (t: number) => void }

interface DragState {
  clipId: string; mode: 'move' | 'resize-left' | 'resize-right'
  origStart: number; origDur: number; mouseX0: number
}

const TYPE_ICONS: Record<string, string> = { video: '🎬', audio: '🎵', subtitle: '💬', overlay: '🎨' }

export default function Timeline({ seek }: TimelineProps) {
  const project = useEditorStore(s => s.project)
  const pid = useEditorStore(s => s.pid)
  const playbackTime = useEditorStore(s => s.playbackTime)
  const zoom = useEditorStore(s => s.zoom)
  const snap = useEditorStore(s => s.snap)
  const selectedClip = useEditorStore(s => s.selectedClip)
  const loopA = useEditorStore(s => s.loopA)
  const loopB = useEditorStore(s => s.loopB)
  const selectClip = useEditorStore(s => s.selectClip)
  const setZoom = useEditorStore(s => s.setZoom)
  const toggleSnap = useEditorStore(s => s.toggleSnap)
  const refreshProject = useEditorStore(s => s.refreshProject)

  const undoAction = useEditorStore(s => s.undoAction)
  const redoAction = useEditorStore(s => s.redoAction)
  const splitAtPlayhead = useEditorStore(s => s.splitAtPlayhead)
  const deleteSelectedClip = useEditorStore(s => s.deleteSelectedClip)

  const rulerRef = useRef<HTMLCanvasElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<DragState | null>(null)
  const [scrubbing, setScrubbing] = useState(false)
  const { drawWaveform } = useWaveform()
  const waveformRefs = useRef<Map<string, HTMLCanvasElement>>(new Map())

  const clips = project?.clips || []
  const duration = project?.duration || 60

  // Group clips by track (show all 4 tracks always if project exists)
  const tracks = TRACK_ORDER.map(track => ({
    track,
    clips: clips.filter(c => c.track === track),
  }))
  const activeTracks = project ? tracks.filter(t => t.clips.length > 0) : []
  // Always show at least video+audio+subtitle if project has clips
  const visibleTracks = project
    ? tracks.filter(t => t.clips.length > 0 || t.track === 'video' || t.track === 'audio')
    : []

  // ── Draw Ruler ──
  useEffect(() => {
    const cv = rulerRef.current
    if (!cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return
    const w = Math.max(cv.parentElement!.scrollWidth, (duration + 10) * zoom)
    cv.width = w; cv.height = 28

    const styles = getComputedStyle(document.documentElement)
    const bg3 = styles.getPropertyValue('--bg3').trim() || '#191d29'
    const accent = styles.getPropertyValue('--accent').trim() || '#00e5a0'
    const dim = styles.getPropertyValue('--dim').trim() || '#7a7f94'

    ctx.fillStyle = bg3; ctx.fillRect(0, 0, w, 28)

    // Major and minor ticks like original
    let step = 1
    if (zoom < 10) step = 10; else if (zoom < 25) step = 5; else if (zoom < 60) step = 2; else step = 1
    const subStep = step / 5
    const border = styles.getPropertyValue('--border').trim() || '#262b3d'

    for (let t = 0; t <= duration + 10; t += subStep) {
      const x = t * zoom
      const isMajor = Math.abs(t % step) < 0.001 || Math.abs(t % step - step) < 0.001
      ctx.strokeStyle = isMajor ? dim : border; ctx.lineWidth = isMajor ? 0.8 : 0.5
      ctx.beginPath(); ctx.moveTo(x, isMajor ? 8 : 18); ctx.lineTo(x, 28); ctx.stroke()
      if (isMajor) {
        ctx.fillStyle = dim; ctx.font = '9px "JetBrains Mono", monospace'
        ctx.fillText(fmt(t), x + 2, 14)
      }
    }

    // A/B loop region
    if (loopA !== null && loopB !== null && loopA < loopB) {
      const la = loopA * zoom, lb = loopB * zoom
      ctx.fillStyle = 'rgba(0,230,150,.15)'; ctx.fillRect(la, 0, lb - la, 28)
      ctx.strokeStyle = accent; ctx.lineWidth = 2
      ctx.beginPath(); ctx.moveTo(la, 0); ctx.lineTo(la, 28); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(lb, 0); ctx.lineTo(lb, 28); ctx.stroke()
      ctx.font = 'bold 10px sans-serif'; ctx.fillStyle = accent
      ctx.fillText('A', la + 3, 10); ctx.fillText('B', lb + 3, 10)
    }

    // Playhead
    const px = playbackTime * zoom
    ctx.strokeStyle = accent; ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, 28); ctx.stroke()
    ctx.fillStyle = accent; ctx.beginPath()
    ctx.moveTo(px - 5, 0); ctx.lineTo(px + 5, 0); ctx.lineTo(px, 6); ctx.closePath(); ctx.fill()
  }, [playbackTime, zoom, duration, loopA, loopB])

  // ── Draw waveforms for audio clips ──
  useEffect(() => {
    if (!project) return
    project.clips.forEach(clip => {
      if (clip.track === 'audio') {
        const cv = waveformRefs.current.get(clip.id)
        if (cv) drawWaveform(cv, clip.asset_id)
      }
    })
  }, [project, zoom, drawWaveform])

  // ── Ruler click → seek ──
  const handleRulerClick = useCallback((e: React.MouseEvent) => {
    const rect = rulerRef.current?.getBoundingClientRect()
    if (!rect) return
    const scrollLeft = scrollRef.current?.scrollLeft || 0
    seek(Math.max(0, (e.clientX - rect.left + scrollLeft) / zoom))
  }, [zoom, seek])

  const handleScrubStart = useCallback((e: React.MouseEvent) => {
    setScrubbing(true); handleRulerClick(e)
  }, [handleRulerClick])

  useEffect(() => {
    if (!scrubbing) return
    const move = (e: MouseEvent) => {
      const rect = rulerRef.current?.getBoundingClientRect()
      if (!rect) return
      const scrollLeft = scrollRef.current?.scrollLeft || 0
      seek(Math.max(0, (e.clientX - rect.left + scrollLeft) / zoom))
    }
    const up = () => setScrubbing(false)
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
  }, [scrubbing, zoom, seek])

  // ── Clip Drag ──
  const startDrag = useCallback((e: React.MouseEvent, clipId: string) => {
    e.preventDefault()
    const clip = clips.find(c => c.id === clipId)
    if (!clip) return
    selectClip(clipId)
    setDrag({ clipId, mode: 'move', origStart: clip.start, origDur: clip.duration, mouseX0: e.clientX })
  }, [clips, selectClip])

  const startResize = useCallback((e: React.MouseEvent, clipId: string, side: 'left' | 'right') => {
    e.stopPropagation(); e.preventDefault()
    const clip = clips.find(c => c.id === clipId)
    if (!clip) return
    selectClip(clipId)
    setDrag({ clipId, mode: side === 'left' ? 'resize-left' : 'resize-right', origStart: clip.start, origDur: clip.duration, mouseX0: e.clientX })
  }, [clips, selectClip])

  useEffect(() => {
    if (!drag || !pid) return
    const move = (e: MouseEvent) => {
      const dx = (e.clientX - drag.mouseX0) / zoom
      if (drag.mode === 'move') {
        const newStart = Math.max(0, drag.origStart + dx)
        useEditorStore.setState(s => ({
          project: s.project ? {
            ...s.project,
            clips: s.project.clips.map(c => c.id === drag.clipId ? { ...c, start: newStart, end: newStart + c.duration } : c)
          } : s.project
        }))
      } else if (drag.mode === 'resize-right') {
        const newDur = Math.max(0.1, drag.origDur + dx)
        useEditorStore.setState(s => ({
          project: s.project ? {
            ...s.project,
            clips: s.project.clips.map(c => c.id === drag.clipId ? { ...c, duration: newDur, end: c.start + newDur } : c)
          } : s.project
        }))
      } else if (drag.mode === 'resize-left') {
        const delta = Math.min(dx, drag.origDur - 0.1)
        const newStart = Math.max(0, drag.origStart + delta)
        const newDur = drag.origDur - delta
        useEditorStore.setState(s => ({
          project: s.project ? {
            ...s.project,
            clips: s.project.clips.map(c => c.id === drag.clipId ? { ...c, start: newStart, duration: newDur, end: newStart + newDur } : c)
          } : s.project
        }))
      }
    }
    const up = async () => {
      // Persist the drag result to server
      const clip = useEditorStore.getState().project?.clips.find(c => c.id === drag.clipId)
      if (clip && pid) {
        try { await api.updateClip(pid, drag.clipId, { start: clip.start, duration: clip.duration } as any) }
        catch { /* noop */ }
      }
      setDrag(null)
      await refreshProject()
    }
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
  }, [drag, zoom, pid, refreshProject])

  // ── Drop from sidebar (at position) ──
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const assetId = e.dataTransfer.getData('asset_id')
    if (!assetId || !pid || !project) return
    const asset = project.assets[assetId]
    if (!asset) return
    // Calculate start time from drop x position
    const rect = scrollRef.current?.getBoundingClientRect()
    const scrollLeft = scrollRef.current?.scrollLeft || 0
    const x = e.clientX - (rect?.left || 0) + scrollLeft
    const startTime = Math.max(0, x / zoom)
    const trackMap: Record<string, string> = { video: 'video', audio: 'audio', image: 'video', subtitle: 'subtitle' }
    const track = trackMap[asset.type] || 'video'
    api.addClip(pid, assetId, track, startTime, 0).then(() => refreshProject())
  }, [pid, project, zoom, refreshProject])

  // ── Scroll wheel zoom ──
  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) { e.preventDefault(); setZoom(zoom + (e.deltaY < 0 ? 5 : -5)) }
  }, [zoom, setZoom])

  const totalWidth = Math.max(800, (duration + 10) * zoom)

  return (
    <div className="timeline-area" onWheel={handleWheel}>
      <div className="tl-toolbar">
        <button className="btn-s btn-sm" onClick={undoAction} title="Undo">↩</button>
        <button className="btn-s btn-sm" onClick={redoAction} title="Redo">↪</button>
        <span className="tl-sep" />
        <button className="btn-s btn-sm" onClick={splitAtPlayhead} title="Split am Playhead (S)">✂️ Split</button>
        <button className="btn-s btn-sm" onClick={deleteSelectedClip} title="Clip löschen (Del)">🗑️</button>
        <button className={`btn-s btn-sm ${snap ? '' : 'snap-off'}`} onClick={toggleSnap}>
          🧲 Snap {snap ? 'An' : 'Aus'}
        </button>
        <div className="tl-spacer" />
        <div className="tl-zoom">
          <span className="tl-dim">🔍</span>
          <input type="range" min="5" max="200" value={zoom} onChange={e => setZoom(+e.target.value)} />
          <span className="tl-dim">{zoom}px/s</span>
        </div>
      </div>
      <div className="tl-scroll" ref={scrollRef} onDrop={handleDrop} onDragOver={e => e.preventDefault()}>
        <div className="tl-ruler" onMouseDown={handleScrubStart}>
          <canvas ref={rulerRef} height={28} />
        </div>
        <div className="tl-tracks" style={{ width: totalWidth }}>
          {visibleTracks.map(({ track, clips: trackClips }) => (
            <div key={track} className="tl-track">
              <div className="tl-track-label" style={{ borderLeftColor: TRACK_COLORS[track] }}>
                {TYPE_ICONS[track]} {track}
              </div>
              <div className="tl-track-lane" style={{ width: totalWidth }}>
                {trackClips.map(clip => {
                  const asset = project?.assets[clip.asset_id]
                  const left = clip.start * zoom
                  const width = Math.max(clip.duration * zoom, 8)
                  const sel = clip.id === selectedClip
                  return (
                    <div key={clip.id} className={`tl-clip ${sel ? 'selected' : ''}`}
                      style={{
                        left, width: Math.max(width, 8),
                        background: sel ? TRACK_COLORS[track] : TRACK_COLORS[track] + '40',
                        borderColor: TRACK_COLORS[track],
                      }}
                      onMouseDown={e => { if (!(e.target as HTMLElement).classList.contains('tl-resize')) startDrag(e, clip.id) }}
                      onClick={e => { e.stopPropagation(); selectClip(clip.id) }}
                      title={`${asset?.filename || clip.id}\n${fmt(clip.start)} → ${fmt(clip.end)}`}>
                      <div className="tl-resize tl-resize-left" onMouseDown={e => startResize(e, clip.id, 'left')} />
                      <span className="tl-clip-name">
                        {TYPE_ICONS[track]} {asset?.filename || clip.id}
                      </span>
                      {clip.effects.length > 0 && <span className="tl-clip-fx">✨{clip.effects.length}</span>}
                      {clip.loop && <span className="tl-clip-loop">🔁</span>}
                      {/* Audio waveform */}
                      {track === 'audio' && (
                        <canvas className="clip-waveform"
                          ref={el => { if (el) waveformRefs.current.set(clip.id, el) }}
                          width={Math.max(20, Math.round(clip.duration * zoom))} height={44} />
                      )}
                      {/* Video film-strip pattern */}
                      {track === 'video' && <div className="clip-bars video-bars">
                        {Array.from({ length: Math.min(40, Math.max(3, Math.floor(width / 8))) }).map((_, i) => (
                          <span key={i} style={{ height: '100%', background: i % 2 === 0 ? 'rgba(255,255,255,.2)' : 'rgba(255,255,255,.08)' }} />
                        ))}
                      </div>}
                      {/* Subtitle text-line pattern */}
                      {track === 'subtitle' && <div className="clip-bars sub-bars">
                        {Array.from({ length: Math.min(30, Math.max(3, Math.floor(width / 8))) }).map((_, i) => (
                          <span key={i} style={{ height: (20 + Math.random() * 60) + '%' }} />
                        ))}
                      </div>}
                      {/* Overlay dotted pattern */}
                      {track === 'overlay' && <div className="clip-bars overlay-bars">
                        {Array.from({ length: Math.min(20, Math.max(2, Math.floor(width / 12))) }).map((_, i) => (
                          <span key={i} style={{ height: (30 + Math.random() * 50) + '%' }} />
                        ))}
                      </div>}
                      <div className="tl-resize tl-resize-right" onMouseDown={e => startResize(e, clip.id, 'right')} />
                    </div>
                  )
                })}
                {/* A/B loop visualization on track */}
                {loopA !== null && loopB !== null && loopA < loopB && (
                  <div className="tl-loop-region" style={{ left: loopA * zoom, width: (loopB - loopA) * zoom }} />
                )}
              </div>
            </div>
          ))}
          {visibleTracks.length === 0 && (
            <div className="tl-empty">Assets aus der Sidebar hierher ziehen</div>
          )}
        </div>
        <div className="tl-playhead" style={{ left: playbackTime * zoom }} />
      </div>
    </div>
  )
}
