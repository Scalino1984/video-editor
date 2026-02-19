import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import * as api from '../../api/editor'
import { fmt, assToHex, assAlpha, parseTimeStr } from '../../utils/format'
import './Preview.css'

interface PreviewProps {
  videoRef: React.RefObject<HTMLVideoElement>
  audioRef: React.RefObject<HTMLAudioElement>
  togglePlay: () => void
  seek: (t: number) => void
  stop: () => void
  syncMediaSources: () => void
}

export default function Preview({ videoRef, audioRef, togglePlay, seek, stop, syncMediaSources }: PreviewProps) {
  const project = useEditorStore(s => s.project)
  const pid = useEditorStore(s => s.pid)
  const playbackTime = useEditorStore(s => s.playbackTime)
  const playing = useEditorStore(s => s.playing)
  const playSpeed = useEditorStore(s => s.playSpeed)
  const subtitleCues = useEditorStore(s => s.subtitleCues)
  const loopA = useEditorStore(s => s.loopA)
  const loopB = useEditorStore(s => s.loopB)
  const setLoopA = useEditorStore(s => s.setLoopA)
  const setLoopB = useEditorStore(s => s.setLoopB)
  const clearLoop = useEditorStore(s => s.clearLoop)
  const setPlaySpeed = useEditorStore(s => s.setPlaySpeed)
  const previewRef = useRef<HTMLDivElement>(null)
  const [editingTime, setEditingTime] = useState(false)
  const [timeInput, setTimeInput] = useState('')
  const [scrubbing, setScrubbing] = useState(false)

  // ── Media Sources ──
  useEffect(() => { syncMediaSources() }, [project, pid, syncMediaSources])

  // ── Current Subtitle ──
  const currentSub = useMemo(() => {
    if (!subtitleCues.length) return null
    const t = playbackTime
    const idx = subtitleCues.findIndex(c => t >= c.start && t < c.end)
    if (idx < 0) return null
    const lines = project?.sub_lines ?? 1
    return {
      current: subtitleCues[idx],
      prev: idx > 0 ? subtitleCues[idx - 1] : null,
      next: idx + 1 < subtitleCues.length ? subtitleCues[idx + 1] : null,
      lines,
    }
  }, [subtitleCues, playbackTime, project?.sub_lines])

  // ── Subtitle Style ──
  const subStyle = useMemo(() => {
    if (!project) return {} as Record<string, unknown>
    const yPct = project.sub_y_percent ?? 85
    const previewH = previewRef.current?.offsetHeight ?? 460
    const scale = previewH / 1080
    const sizePx = Math.max(10, Math.round((project.sub_size || 48) * scale))
    const ctxSizePx = Math.max(8, Math.round((project.sub_size || 48) * 0.75 * scale))
    const color = assToHex(project.sub_color || '&H00FFFFFF')
    const outColor = assToHex(project.sub_outline_color || '&H00000000')
    const outW = Math.max(1, Math.round((project.sub_outline_width || 2) * scale))
    const shadow = `${outW}px ${outW}px 0 ${outColor}, -${outW}px ${outW}px 0 ${outColor}, ${outW}px -${outW}px 0 ${outColor}, -${outW}px -${outW}px 0 ${outColor}`
    const bgOn = project.sub_bg_enabled !== false
    const bgAss = project.sub_bg_color || '&H80000000'
    const bgA = assAlpha(bgAss) / 255
    const bgHex = assToHex(bgAss)
    const r = parseInt(bgHex.slice(1, 3), 16), g = parseInt(bgHex.slice(3, 5), 16), b = parseInt(bgHex.slice(5, 7), 16)
    const bg = bgOn ? `rgba(${r},${g},${b},${bgA.toFixed(2)})` : 'transparent'
    return { yPct, sizePx, ctxSizePx, color, shadow, bg, font: project.sub_font || 'Arial',
      transform: yPct > 50 ? 'translateY(-100%)' : yPct > 20 ? 'translateY(-50%)' : '' }
  }, [project])

  // ── Scrubber bar ──
  const dur = project?.duration || 0
  const pct = dur > 0 ? Math.min(100, playbackTime / dur * 100) : 0

  const scrubStart = useCallback((e: React.MouseEvent) => {
    setScrubbing(true)
    scrubSeek(e)
  }, [dur]) // eslint-disable-line

  const scrubSeek = useCallback((e: React.MouseEvent | MouseEvent) => {
    const bar = (e.currentTarget || e.target) as HTMLElement
    const rect = bar.closest('.scrubber')?.getBoundingClientRect()
    if (!rect) return
    const p = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    seek(p * (dur || 0))
  }, [seek, dur])

  useEffect(() => {
    if (!scrubbing) return
    const move = (e: MouseEvent) => {
      const bar = document.querySelector('.scrubber')
      if (!bar) return
      const rect = bar.getBoundingClientRect()
      const p = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
      seek(p * (dur || 0))
    }
    const up = () => setScrubbing(false)
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
  }, [scrubbing, seek, dur])

  // ── Jump to time ──
  const jumpToTime = () => {
    const t = parseTimeStr(timeInput)
    seek(Math.max(0, Math.min(dur || 9999, t)))
    setEditingTime(false)
    useEditorStore.getState().toast('→ ' + fmt(t))
  }

  return (
    <div className="center">
      <div className="preview-area" ref={previewRef}>
        <video ref={videoRef} playsInline />
        <audio ref={audioRef} />

        {/* Subtitle Overlay */}
        {currentSub && (
          <div className="sub-overlay" style={{ top: (subStyle as any).yPct + '%', transform: (subStyle as any).transform }}>
            {currentSub.lines >= 3 && currentSub.prev && (
              <span className="sub-context" style={{
                fontFamily: (subStyle as any).font, fontSize: (subStyle as any).ctxSizePx + 'px',
                color: (subStyle as any).color, textShadow: (subStyle as any).shadow, background: (subStyle as any).bg,
              }}>{currentSub.prev.text}</span>
            )}
            <span className="sub-current" style={{
              fontFamily: (subStyle as any).font, fontSize: (subStyle as any).sizePx + 'px',
              color: (subStyle as any).color, fontWeight: 700, textShadow: (subStyle as any).shadow, background: (subStyle as any).bg,
            }}>{currentSub.current.text}</span>
            {currentSub.lines >= 2 && currentSub.next && (
              <span className="sub-context" style={{
                fontFamily: (subStyle as any).font, fontSize: (subStyle as any).ctxSizePx + 'px',
                color: (subStyle as any).color, textShadow: (subStyle as any).shadow, background: (subStyle as any).bg, opacity: 0.55,
              }}>{currentSub.next.text}</span>
            )}
          </div>
        )}
        {!project && <div className="preview-placeholder">🎬 Projekt erstellen oder laden</div>}
      </div>

      {/* Scrubber Bar */}
      <div className="scrubber" onMouseDown={scrubStart}>
        <div className="scrub-fill" style={{ width: pct + '%' }} />
        <div className="scrub-handle" style={{ left: pct + '%' }} />
        {/* A/B loop region on scrubber */}
        {loopA !== null && loopB !== null && dur > 0 && (
          <div className="scrub-loop" style={{
            left: (loopA / dur * 100) + '%',
            width: ((loopB - loopA) / dur * 100) + '%',
          }} />
        )}
      </div>

      {/* Transport Controls */}
      <div className="transport">
        <button className="btn-s btn-sm" onClick={stop} title="Stop (Esc)">⏹</button>
        <button className="btn-s btn-sm" onClick={() => seek(0)} title="Anfang (Home)">⏮</button>
        <button className="btn-s btn-sm" onClick={() => seek(Math.max(0, playbackTime - 2))}>-2s</button>
        <button className="btn btn-sm transport-play" onClick={togglePlay}>
          {playing ? '⏸' : '▶'}
        </button>
        <button className="btn-s btn-sm" onClick={() => seek(playbackTime + 2)}>+2s</button>
        <button className="btn-s btn-sm" onClick={() => seek(dur)} title="Ende (End)">⏭</button>

        <span className="transport-sep">|</span>

        {/* Time display / jump input */}
        {editingTime ? (
          <input className="transport-time-input" value={timeInput}
            onChange={e => setTimeInput(e.target.value)}
            onBlur={() => setEditingTime(false)}
            onKeyDown={e => { if (e.key === 'Enter') jumpToTime(); if (e.key === 'Escape') setEditingTime(false) }}
            autoFocus placeholder="M:SS.s" />
        ) : (
          <span className="transport-time" onClick={() => { setTimeInput(fmt(playbackTime)); setEditingTime(true) }}
            title="Klick zum Springen">{fmt(playbackTime)}</span>
        )}
        <span className="transport-dim">/ {fmt(dur)}</span>

        <div className="transport-spacer" />

        {/* Play Speed */}
        <select className="speed-select" value={playSpeed} onChange={e => setPlaySpeed(+e.target.value)}
          title="Wiedergabegeschwindigkeit">
          {[0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4].map(v => (
            <option key={v} value={v}>{v}×</option>
          ))}
        </select>

        <span className="transport-sep">|</span>

        {/* A/B Loop */}
        <button className={`btn-s btn-sm ${loopA !== null ? 'loop-active' : ''}`}
          onClick={setLoopA} title="Loop Start (Alt+A)">A{loopA !== null ? ` ${fmt(loopA)}` : ''}</button>
        <button className={`btn-s btn-sm ${loopB !== null ? 'loop-active' : ''}`}
          onClick={setLoopB} title="Loop Ende (Alt+B)">B{loopB !== null ? ` ${fmt(loopB)}` : ''}</button>
        {loopA !== null && loopB !== null && (
          <button className="btn-s btn-sm" onClick={clearLoop} title="Loop löschen (Alt+C)">✕</button>
        )}
      </div>
    </div>
  )
}
