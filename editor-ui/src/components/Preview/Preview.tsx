import { useEffect, useMemo, useRef, useCallback } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import * as api from '../../api/editor'
import { fmt, assToHex, assAlpha } from '../../utils/format'
import './Preview.css'

interface PreviewProps {
  videoRef: React.RefObject<HTMLVideoElement>
  audioRef: React.RefObject<HTMLAudioElement>
  togglePlay: () => void
  seek: (t: number) => void
}

export default function Preview({ videoRef, audioRef, togglePlay, seek }: PreviewProps) {
  const project = useEditorStore(s => s.project)
  const pid = useEditorStore(s => s.pid)
  const playbackTime = useEditorStore(s => s.playbackTime)
  const playing = useEditorStore(s => s.playing)
  const subtitleCues = useEditorStore(s => s.subtitleCues)
  const loopA = useEditorStore(s => s.loopA)
  const loopB = useEditorStore(s => s.loopB)
  const setLoopA = useEditorStore(s => s.setLoopA)
  const setLoopB = useEditorStore(s => s.setLoopB)
  const clearLoop = useEditorStore(s => s.clearLoop)
  const previewRef = useRef<HTMLDivElement>(null)

  // ── Media Sources ──
  useEffect(() => {
    if (!project || !pid) return
    const vid = videoRef.current
    const au = audioRef.current

    const videoClip = project.clips.find(c => c.track === 'video' || c.track === 'overlay')
    const audioClip = project.clips.find(c => c.track === 'audio')

    if (vid && videoClip) {
      const url = api.assetFileUrl(pid, videoClip.asset_id)
      if (vid.src !== url) {
        vid.src = url
        vid.loop = true
        vid.muted = !!audioClip
      }
    } else if (vid) {
      vid.src = ''
    }

    if (au && audioClip) {
      const url = api.assetFileUrl(pid, audioClip.asset_id)
      if (au.src !== url) {
        au.src = url
      }
    } else if (au) {
      au.src = ''
    }
  }, [project, pid, videoRef, audioRef])

  // ── Current Subtitle ──
  const currentSub = useMemo(() => {
    if (!subtitleCues.length) return null
    const t = playbackTime
    const idx = subtitleCues.findIndex(c => t >= c.start && t < c.end)
    if (idx < 0) return null
    const lines = project?.sub_lines ?? 1
    const cue = subtitleCues[idx]
    const prev = idx > 0 ? subtitleCues[idx - 1] : null
    const next = idx + 1 < subtitleCues.length ? subtitleCues[idx + 1] : null
    return { current: cue, prev, next, lines }
  }, [subtitleCues, playbackTime, project?.sub_lines])

  // ── Subtitle Style ──
  const subStyle = useMemo(() => {
    if (!project) return {}
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
    const r = parseInt(bgHex.slice(1, 3), 16)
    const g = parseInt(bgHex.slice(3, 5), 16)
    const b = parseInt(bgHex.slice(5, 7), 16)
    const bg = bgOn ? `rgba(${r},${g},${b},${bgA.toFixed(2)})` : 'transparent'

    return {
      yPct, sizePx, ctxSizePx, color, shadow, bg,
      font: project.sub_font || 'Arial',
      transform: yPct > 50 ? 'translateY(-100%)' : yPct > 20 ? 'translateY(-50%)' : '',
    }
  }, [project])

  return (
    <div className="center">
      <div className="preview-area" ref={previewRef}>
        <video ref={videoRef} playsInline />
        <audio ref={audioRef} />

        {/* Subtitle Overlay */}
        {currentSub && (
          <div
            className="sub-overlay"
            style={{
              top: subStyle.yPct + '%',
              transform: subStyle.transform,
            }}
          >
            {currentSub.lines >= 3 && currentSub.prev && (
              <span
                className="sub-context"
                style={{
                  fontFamily: subStyle.font,
                  fontSize: subStyle.ctxSizePx + 'px',
                  color: subStyle.color,
                  textShadow: subStyle.shadow,
                  background: subStyle.bg,
                }}
              >
                {currentSub.prev.text}
              </span>
            )}
            <span
              className="sub-current"
              style={{
                fontFamily: subStyle.font,
                fontSize: subStyle.sizePx + 'px',
                color: subStyle.color,
                fontWeight: 700,
                textShadow: subStyle.shadow,
                background: subStyle.bg,
              }}
            >
              {currentSub.current.text}
            </span>
            {currentSub.lines >= 2 && currentSub.next && (
              <span
                className="sub-context"
                style={{
                  fontFamily: subStyle.font,
                  fontSize: subStyle.ctxSizePx + 'px',
                  color: subStyle.color,
                  textShadow: subStyle.shadow,
                  background: subStyle.bg,
                  opacity: 0.55,
                }}
              >
                {currentSub.next.text}
              </span>
            )}
          </div>
        )}

        {/* No project placeholder */}
        {!project && (
          <div className="preview-placeholder">
            🎬 Projekt erstellen oder laden
          </div>
        )}
      </div>

      {/* Transport Controls */}
      <div className="transport">
        <button className="btn-s btn-sm" onClick={() => seek(0)} title="Anfang">⏮</button>
        <button className="btn-s btn-sm" onClick={() => seek(Math.max(0, playbackTime - 5))}>-5s</button>
        <button className="btn btn-sm transport-play" onClick={togglePlay}>
          {playing ? '⏸' : '▶'}
        </button>
        <button className="btn-s btn-sm" onClick={() => seek(playbackTime + 5)}>+5s</button>
        <button className="btn-s btn-sm" onClick={() => seek(project?.duration || 0)} title="Ende">⏭</button>

        <span className="transport-sep">|</span>

        <span className="transport-time">{fmt(playbackTime)}</span>
        <span className="transport-dim">/ {fmt(project?.duration || 0)}</span>

        <div className="transport-spacer" />

        {/* A/B Loop */}
        <button
          className={`btn-s btn-sm ${loopA !== null ? 'loop-active' : ''}`}
          onClick={setLoopA}
          title="Loop Start (Alt+A)"
        >
          A{loopA !== null ? ` ${fmt(loopA)}` : ''}
        </button>
        <button
          className={`btn-s btn-sm ${loopB !== null ? 'loop-active' : ''}`}
          onClick={setLoopB}
          title="Loop Ende (Alt+B)"
        >
          B{loopB !== null ? ` ${fmt(loopB)}` : ''}
        </button>
        {loopA !== null && loopB !== null && (
          <button className="btn-s btn-sm" onClick={clearLoop} title="Loop löschen">✕</button>
        )}
      </div>
    </div>
  )
}
