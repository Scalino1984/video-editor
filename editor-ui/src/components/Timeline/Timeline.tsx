import { useRef, useEffect, useCallback, useState } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import { fmt } from '../../utils/format'
import { TRACK_COLORS, TRACK_ORDER } from '../../types'
import './Timeline.css'

interface TimelineProps {
  seek: (t: number) => void
}

interface DragState {
  clipId: string
  mode: 'move' | 'resize-left' | 'resize-right'
  origStart: number
  origDur: number
  mouseX0: number
}

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
  const updateProjectProp = useEditorStore(s => s.updateProjectProp)
  const refreshProject = useEditorStore(s => s.refreshProject)
  const addToTimeline = useEditorStore(s => s.addToTimeline)

  const rulerRef = useRef<HTMLCanvasElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<DragState | null>(null)
  const [scrubbing, setScrubbing] = useState(false)

  const clips = project?.clips || []
  const duration = project?.duration || 60

  // ── Group clips by track ──
  const tracks = TRACK_ORDER.map(track => ({
    track,
    clips: clips.filter(c => c.track === track),
  })).filter(t => t.clips.length > 0)

  // ── Draw Ruler ──
  useEffect(() => {
    const cv = rulerRef.current
    if (!cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return
    const w = Math.max(cv.parentElement!.scrollWidth, (duration + 10) * zoom)
    cv.width = w
    cv.height = 28

    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--bg3').trim() || '#191d29'
    ctx.fillRect(0, 0, w, 28)

    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#00e5a0'
    const dim = getComputedStyle(document.documentElement).getPropertyValue('--dim').trim() || '#7a7f94'

    // Grid lines
    const step = zoom >= 80 ? 1 : zoom >= 30 ? 5 : 10
    for (let t = 0; t <= duration + 10; t += step) {
      const x = t * zoom
      ctx.strokeStyle = dim
      ctx.lineWidth = 0.5
      ctx.beginPath()
      ctx.moveTo(x, 18)
      ctx.lineTo(x, 28)
      ctx.stroke()
      ctx.fillStyle = dim
      ctx.font = '9px "JetBrains Mono", monospace'
      ctx.fillText(fmt(t), x + 3, 14)
    }

    // A/B loop region
    if (loopA !== null && loopB !== null && loopA < loopB) {
      const la = loopA * zoom
      const lb = loopB * zoom
      ctx.fillStyle = 'rgba(0,230,150,.15)'
      ctx.fillRect(la, 0, lb - la, 28)
      ctx.strokeStyle = accent
      ctx.lineWidth = 2
      ctx.beginPath(); ctx.moveTo(la, 0); ctx.lineTo(la, 28); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(lb, 0); ctx.lineTo(lb, 28); ctx.stroke()
      ctx.font = 'bold 10px sans-serif'
      ctx.fillStyle = accent
      ctx.fillText('A', la + 3, 10)
      ctx.fillText('B', lb + 3, 10)
    }

    // Playhead
    const px = playbackTime * zoom
    ctx.strokeStyle = accent
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(px, 0)
    ctx.lineTo(px, 28)
    ctx.stroke()
    ctx.fillStyle = accent
    ctx.beginPath()
    ctx.moveTo(px - 5, 0)
    ctx.lineTo(px + 5, 0)
    ctx.lineTo(px, 6)
    ctx.closePath()
    ctx.fill()
  }, [playbackTime, zoom, duration, loopA, loopB])

  // ── Ruler click → seek ──
  const handleRulerClick = useCallback((e: React.MouseEvent) => {
    const rect = rulerRef.current?.getBoundingClientRect()
    if (!rect) return
    const scrollLeft = scrollRef.current?.scrollLeft || 0
    const x = e.clientX - rect.left + scrollLeft
    const t = Math.max(0, x / zoom)
    seek(t)
  }, [zoom, seek])

  // ── Scrub ──
  const handleScrubStart = useCallback((e: React.MouseEvent) => {
    setScrubbing(true)
    handleRulerClick(e)
  }, [handleRulerClick])

  useEffect(() => {
    if (!scrubbing) return
    const move = (e: MouseEvent) => {
      const rect = rulerRef.current?.getBoundingClientRect()
      if (!rect) return
      const scrollLeft = scrollRef.current?.scrollLeft || 0
      const x = e.clientX - rect.left + scrollLeft
      seek(Math.max(0, x / zoom))
    }
    const up = () => setScrubbing(false)
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
  }, [scrubbing, zoom, seek])

  // ── Clip Drag ──
  const startDrag = useCallback((e: React.MouseEvent, clipId: string) => {
    const clip = clips.find(c => c.id === clipId)
    if (!clip) return
    selectClip(clipId)
    setDrag({
      clipId,
      mode: 'move',
      origStart: clip.start,
      origDur: clip.duration,
      mouseX0: e.clientX,
    })
  }, [clips, selectClip])

  const startResize = useCallback((e: React.MouseEvent, clipId: string, side: 'left' | 'right') => {
    e.stopPropagation()
    const clip = clips.find(c => c.id === clipId)
    if (!clip) return
    selectClip(clipId)
    setDrag({
      clipId,
      mode: side === 'left' ? 'resize-left' : 'resize-right',
      origStart: clip.start,
      origDur: clip.duration,
      mouseX0: e.clientX,
    })
  }, [clips, selectClip])

  useEffect(() => {
    if (!drag || !pid) return
    const move = (e: MouseEvent) => {
      const dx = (e.clientX - drag.mouseX0) / zoom
      const clip = clips.find(c => c.id === drag.clipId)
      if (!clip) return

      if (drag.mode === 'move') {
        const newStart = Math.max(0, drag.origStart + dx)
        updateProjectProp('clips', clips.map(c =>
          c.id === drag.clipId ? { ...c, start: newStart, end: newStart + c.duration } : c
        ))
      } else if (drag.mode === 'resize-right') {
        const newDur = Math.max(0.1, drag.origDur + dx)
        updateProjectProp('clips', clips.map(c =>
          c.id === drag.clipId ? { ...c, duration: newDur, end: c.start + newDur } : c
        ))
      } else if (drag.mode === 'resize-left') {
        const delta = Math.min(dx, drag.origDur - 0.1)
        const newStart = drag.origStart + delta
        const newDur = drag.origDur - delta
        updateProjectProp('clips', clips.map(c =>
          c.id === drag.clipId ? { ...c, start: Math.max(0, newStart), duration: newDur, end: Math.max(0, newStart) + newDur } : c
        ))
      }
    }
    const up = async () => {
      setDrag(null)
      await refreshProject()
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
  }, [drag, clips, zoom, pid, updateProjectProp, refreshProject])

  // ── Drop from sidebar ──
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const assetId = e.dataTransfer.getData('asset_id')
    if (assetId) addToTimeline(assetId)
  }, [addToTimeline])

  // ── Scroll wheel zoom ──
  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault()
      setZoom(zoom + (e.deltaY < 0 ? 5 : -5))
    }
  }, [zoom, setZoom])

  const totalWidth = Math.max(800, (duration + 10) * zoom)

  return (
    <div className="timeline-area" onWheel={handleWheel}>
      {/* Toolbar */}
      <div className="tl-toolbar">
        <span className="tl-label">Timeline</span>
        <div className="tl-zoom">
          <span className="tl-dim">Zoom</span>
          <input
            type="range"
            min="5"
            max="200"
            value={zoom}
            onChange={e => setZoom(+e.target.value)}
          />
          <span className="tl-dim">{zoom}px/s</span>
        </div>
        <button
          className={`btn-s btn-sm ${snap ? '' : 'snap-off'}`}
          onClick={toggleSnap}
        >
          🧲 Snap {snap ? 'An' : 'Aus'}
        </button>
      </div>

      {/* Scrollable content */}
      <div className="tl-scroll" ref={scrollRef} onDrop={handleDrop} onDragOver={e => e.preventDefault()}>
        {/* Ruler */}
        <div className="tl-ruler" onMouseDown={handleScrubStart}>
          <canvas ref={rulerRef} height={28} />
        </div>

        {/* Tracks */}
        <div className="tl-tracks" style={{ width: totalWidth }}>
          {tracks.map(({ track, clips: trackClips }) => (
            <div key={track} className="tl-track">
              <div className="tl-track-label" style={{ borderLeftColor: TRACK_COLORS[track] }}>
                {track}
              </div>
              <div className="tl-track-lane" style={{ width: totalWidth }}>
                {trackClips.map(clip => {
                  const asset = project?.assets[clip.asset_id]
                  const left = clip.start * zoom
                  const width = clip.duration * zoom
                  const sel = clip.id === selectedClip

                  return (
                    <div
                      key={clip.id}
                      className={`tl-clip ${sel ? 'selected' : ''}`}
                      style={{
                        left,
                        width: Math.max(width, 8),
                        background: sel
                          ? TRACK_COLORS[track]
                          : TRACK_COLORS[track] + '40',
                        borderColor: TRACK_COLORS[track],
                      }}
                      onMouseDown={e => startDrag(e, clip.id)}
                      title={`${asset?.filename || clip.id}\n${fmt(clip.start)} → ${fmt(clip.end)}`}
                    >
                      {/* Resize handles */}
                      <div
                        className="tl-resize tl-resize-left"
                        onMouseDown={e => startResize(e, clip.id, 'left')}
                      />
                      <span className="tl-clip-name">
                        {asset?.filename || clip.id}
                      </span>
                      {clip.effects.length > 0 && (
                        <span className="tl-clip-fx">fx{clip.effects.length}</span>
                      )}
                      <div
                        className="tl-resize tl-resize-right"
                        onMouseDown={e => startResize(e, clip.id, 'right')}
                      />
                    </div>
                  )
                })}
              </div>
            </div>
          ))}

          {tracks.length === 0 && (
            <div className="tl-empty">
              Assets aus der Sidebar ziehen oder Doppelklick auf Asset
            </div>
          )}
        </div>

        {/* Playhead line */}
        <div
          className="tl-playhead"
          style={{ left: playbackTime * zoom }}
        />
      </div>
    </div>
  )
}
