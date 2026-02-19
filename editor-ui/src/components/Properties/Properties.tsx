import { useState, useCallback, useRef, useEffect } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import { hexToAss, hexToAssBg, assToHex, assAlpha } from '../../utils/format'
import { renderMd } from '../../utils/markdown'
import { EFFECTS_LIST } from '../../types'
import './Properties.css'

export default function Properties() {
  const selectedClip = useEditorStore(s => s.selectedClip)
  const propTab = useEditorStore(s => s.propTab)
  const setPropTab = useEditorStore(s => s.setPropTab)

  return (
    <div className="props">
      <div className="props-tabs">
        {selectedClip && (
          <>
            <button className={propTab === 'clip' ? 'active' : ''} onClick={() => setPropTab('clip')}>📎 Clip</button>
            <button className={propTab === 'effects' ? 'active' : ''} onClick={() => setPropTab('effects')}>✨ FX</button>
          </>
        )}
        <button className={propTab === 'project' ? 'active' : ''} onClick={() => setPropTab('project')}>⚙️ Projekt</button>
        <button className={propTab === 'ai' ? 'active' : ''} onClick={() => setPropTab('ai')}>🤖 AI</button>
      </div>
      <div className="props-content">
        {propTab === 'clip' && selectedClip && <ClipProps />}
        {propTab === 'effects' && selectedClip && <EffectsProps />}
        {propTab === 'project' && <ProjectProps />}
        {propTab === 'ai' && <AIChat />}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// CLIP PROPERTIES — uses updateClipProp (server-side via PUT /clips/:id)
// ══════════════════════════════════════════════════════════════════════════════
function ClipProps() {
  const project = useEditorStore(s => s.project)
  const selectedClip = useEditorStore(s => s.selectedClip)
  const updateClipProp = useEditorStore(s => s.updateClipProp)
  const deleteSelectedClip = useEditorStore(s => s.deleteSelectedClip)
  const splitAtPlayhead = useEditorStore(s => s.splitAtPlayhead)
  const duplicateClip = useEditorStore(s => s.duplicateClip)

  if (!project || !selectedClip) return null
  const clip = project.clips.find(c => c.id === selectedClip)
  if (!clip) return <div className="props-empty">Clip nicht gefunden</div>
  const asset = project.assets[clip.asset_id]

  return (
    <div className="props-section">
      <div className="section-title">
        {asset?.filename || clip.id}
        <span className="section-dim">{clip.track}</span>
      </div>
      <div className="props-grid">
        <div className="prop-row">
          <label>Start</label>
          <input type="number" value={clip.start.toFixed(2)} step="0.1" min="0"
            onChange={e => updateClipProp('start', +e.target.value)} />
        </div>
        <div className="prop-row">
          <label>Dauer</label>
          <input type="number" value={clip.duration.toFixed(2)} step="0.1" min="0.1"
            onChange={e => updateClipProp('duration', +e.target.value)} />
        </div>
        <div className="prop-row">
          <label>In-Point</label>
          <input type="number" value={(clip.in_point || 0).toFixed(2)} step="0.1" min="0"
            onChange={e => updateClipProp('in_point', +e.target.value)} />
        </div>
        <div className="prop-row">
          <label>Out-Point</label>
          <input type="number" value={(clip.out_point || 0).toFixed(2)} step="0.1" min="0"
            onChange={e => updateClipProp('out_point', +e.target.value)} />
        </div>

        <div className="prop-row">
          <label>Volume</label>
          <input type="range" min="0" max="2" step="0.05" value={clip.volume}
            onChange={e => updateClipProp('volume', +e.target.value)} />
          <span className="prop-val">{Math.round((clip.volume || 1) * 100)}%</span>
        </div>
        <div className="prop-row">
          <label>Speed</label>
          <input type="range" min="0.25" max="4" step="0.25" value={clip.speed}
            onChange={e => updateClipProp('speed', +e.target.value)} />
          <span className="prop-val">{clip.speed || 1}×</span>
        </div>
        <div className="prop-row">
          <label>Loop</label>
          <input type="checkbox" checked={!!clip.loop} style={{ width: 'auto' }}
            onChange={e => updateClipProp('loop', e.target.checked)} />
        </div>
        <div className="prop-row">
          <label>Z-Index</label>
          <input type="number" value={clip.z_index || 0} min="0" max="100"
            onChange={e => updateClipProp('z_index', +e.target.value)} />
        </div>
      </div>

      {/* Effect badges */}
      {clip.effects.length > 0 && (
        <div className="clip-fx-list">
          {clip.effects.map((fx, i) => (
            <span key={i} className="fx-badge">✨ {fx.type}</span>
          ))}
        </div>
      )}

      <div className="props-actions">
        <button className="btn-s btn-sm" onClick={splitAtPlayhead} title="Split (S)">✂ Split</button>
        <button className="btn-s btn-sm" onClick={duplicateClip} title="Duplizieren (D)">📋 Dup</button>
        <button className="btn-d btn-sm" onClick={deleteSelectedClip} title="Löschen (Del)">🗑 Löschen</button>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// EFFECTS — default params per type, sent as Record<string,unknown>
// ══════════════════════════════════════════════════════════════════════════════
const DEFAULT_FX_PARAMS: Record<string, Record<string, unknown>> = {
  fade_in: { duration: 1 }, fade_out: { duration: 1 }, blur: { sigma: 5 },
  brightness: { value: 0.1 }, contrast: { value: 1.2 }, saturation: { value: 1.5 },
  rotate: { angle: 90 }, zoom: { factor: 1.3 }, vignette: { angle: 0.3 },
  sharpen: { amount: 1 }, speed: { factor: 2 },
  overlay_text: { text: 'Text', size: 48, color: 'white' },
  grayscale: {}, sepia: {}, hflip: {}, vflip: {},
}

function EffectsProps() {
  const project = useEditorStore(s => s.project)
  const selectedClip = useEditorStore(s => s.selectedClip)
  const addEffect = useEditorStore(s => s.addEffect)
  const removeEffect = useEditorStore(s => s.removeEffect)

  if (!project || !selectedClip) return null
  const clip = project.clips.find(c => c.id === selectedClip)
  if (!clip) return null

  return (
    <div className="props-section">
      <div className="section-title">Effekte auf Clip</div>

      {clip.effects.length === 0 && <div className="props-empty">Keine Effekte</div>}
      {clip.effects.map((fx, i) => (
        <div key={i} className="fx-item">
          <span className="fx-name">{fx.type}</span>
          <span className="fx-params">{JSON.stringify(fx.params || {}).slice(0, 40)}</span>
          <button className="btn-d btn-sm fx-rm" onClick={() => removeEffect(i)}>✕</button>
        </div>
      ))}

      <div className="section-title" style={{ marginTop: 12 }}>Hinzufügen</div>
      <div className="fx-grid">
        {EFFECTS_LIST.map(fx => (
          <button key={fx.type} className="btn-s btn-sm fx-add"
            onClick={() => addEffect(fx.type, DEFAULT_FX_PARAMS[fx.type] || {})}>
            {fx.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// PROJECT SETTINGS + SUBTITLE
// ══════════════════════════════════════════════════════════════════════════════
function ProjectProps() {
  const project = useEditorStore(s => s.project)
  const updateProjectProp = useEditorStore(s => s.updateProjectProp)
  const renderProject = useEditorStore(s => s.renderProject)
  const rendering = useEditorStore(s => s.rendering)

  if (!project) return <div className="props-empty">Kein Projekt geladen</div>
  const up = (key: string, val: unknown) => updateProjectProp(key, val)

  return (
    <div className="props-section props-scroll">
      <div className="section-title">Format</div>
      <div className="props-grid">
        <div className="prop-row">
          <label>Breite</label>
          <input type="number" value={project.width} onChange={e => up('width', +e.target.value)} />
        </div>
        <div className="prop-row">
          <label>Höhe</label>
          <input type="number" value={project.height} onChange={e => up('height', +e.target.value)} />
        </div>
        <div className="prop-row">
          <label>FPS</label>
          <input type="number" value={project.fps} onChange={e => up('fps', +e.target.value)} />
        </div>
        <div className="prop-row">
          <label>Preset</label>
          <select value={project.preset} onChange={e => up('preset', e.target.value)}>
            <option value="youtube">YouTube (1080p)</option>
            <option value="mobile">Mobile (720p)</option>
            <option value="draft">Draft (schnell)</option>
            <option value="custom">Custom</option>
          </select>
        </div>
        <div className="prop-row">
          <label>CRF</label>
          <input type="range" min="10" max="35" value={project.crf}
            onChange={e => up('crf', +e.target.value)} />
          <span className="prop-val">{project.crf}</span>
        </div>
        <div className="prop-row">
          <label>Audio</label>
          <select value={project.audio_bitrate || '192k'} onChange={e => up('audio_bitrate', e.target.value)}>
            <option value="96k">96k</option>
            <option value="128k">128k</option>
            <option value="192k">192k</option>
            <option value="320k">320k</option>
          </select>
        </div>
      </div>

      <div className="props-presets">
        {[{ l: '16:9 HD', w: 1920, h: 1080 }, { l: '4K', w: 3840, h: 2160 },
          { l: '9:16 Vert', w: 1080, h: 1920 }, { l: '1:1 Square', w: 1080, h: 1080 }].map(p => (
          <button key={p.l} className="btn-s btn-sm" onClick={() => { up('width', p.w); up('height', p.h) }}>
            {p.l}
          </button>
        ))}
      </div>

      {/* ── Subtitle Settings ── */}
      <div className="section-title">Untertitel</div>
      <div className="props-grid">
        <div className="prop-row">
          <label>Font</label>
          <select value={project.sub_font} onChange={e => up('sub_font', e.target.value)}>
            {['Arial', 'Impact', 'Helvetica', 'Futura', 'Georgia', 'Outfit', 'JetBrains Mono'].map(f => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </div>
        <div className="prop-row">
          <label>Größe</label>
          <input type="range" min="16" max="120" value={project.sub_size}
            onChange={e => up('sub_size', +e.target.value)} />
          <span className="prop-val">{project.sub_size}px</span>
        </div>
        <div className="prop-row">
          <label>Farbe</label>
          <input type="color" value={assToHex(project.sub_color)}
            onInput={e => up('sub_color', hexToAss((e.target as HTMLInputElement).value))}
            style={{ width: 30, height: 20, padding: 0, border: 'none' }} />
        </div>
        <div className="prop-row">
          <label>Outline</label>
          <input type="color" value={assToHex(project.sub_outline_color)}
            onInput={e => up('sub_outline_color', hexToAss((e.target as HTMLInputElement).value))}
            style={{ width: 30, height: 20, padding: 0, border: 'none' }} />
          <input type="range" min="0" max="8" value={project.sub_outline_width}
            onChange={e => up('sub_outline_width', +e.target.value)} />
          <span className="prop-val">{project.sub_outline_width}px</span>
        </div>
        <div className="prop-row">
          <label>Y-Pos</label>
          <input type="range" min="0" max="100" value={project.sub_y_percent}
            onChange={e => up('sub_y_percent', +e.target.value)} />
          <span className="prop-val">{project.sub_y_percent}%</span>
        </div>
        <div className="prop-row sub-hint">← Oben &nbsp;&nbsp; Unten →</div>
        <div className="prop-row">
          <label>Zeilen</label>
          <select value={project.sub_lines} onChange={e => up('sub_lines', +e.target.value)}>
            <option value={1}>1 Zeile</option>
            <option value={2}>2 Zeilen</option>
            <option value={3}>3 Zeilen</option>
          </select>
        </div>
        <div className="prop-row">
          <label>BG</label>
          <input type="checkbox" checked={project.sub_bg_enabled} style={{ width: 'auto' }}
            onChange={e => up('sub_bg_enabled', e.target.checked)} />
          <input type="color" value={assToHex(project.sub_bg_color)}
            onInput={e => {
              const a = assAlpha(project.sub_bg_color)
              up('sub_bg_color', hexToAssBg((e.target as HTMLInputElement).value, a))
            }}
            style={{ width: 30, height: 20, padding: 0, border: 'none' }} />
          <input type="range" min="0" max="255" style={{ flex: 1 }}
            value={assAlpha(project.sub_bg_color)}
            onChange={e => {
              const bgHex = assToHex(project.sub_bg_color)
              up('sub_bg_color', hexToAssBg(bgHex, +e.target.value))
            }} />
          <span className="prop-val">{Math.round(assAlpha(project.sub_bg_color) / 255 * 100)}%</span>
        </div>
      </div>

      {/* ── Render Button (also available in header) ── */}
      <div style={{ marginTop: 16 }}>
        <button className="btn" style={{ width: '100%' }} onClick={renderProject} disabled={rendering}>
          {rendering ? '⏳ Rendering...' : '🎬 Projekt rendern'}
        </button>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// AI CHAT — real SSE streaming via store.sendAI
// ══════════════════════════════════════════════════════════════════════════════
function AIChat() {
  const [input, setInput] = useState('')
  const pid = useEditorStore(s => s.pid)
  const aiMessages = useEditorStore(s => s.aiMessages)
  const aiStreaming = useEditorStore(s => s.aiStreaming)
  const sendAI = useEditorStore(s => s.sendAI)
  const msgsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (msgsRef.current) msgsRef.current.scrollTop = msgsRef.current.scrollHeight
  }, [aiMessages])

  const send = useCallback(async () => {
    const msg = input.trim()
    if (!msg) return
    setInput('')
    await sendAI(msg)
  }, [input, sendAI])

  return (
    <div className="props-section ai-chat">
      <div className="section-title">AI Assistent</div>
      <div className="ai-messages" ref={msgsRef}>
        {aiMessages.length === 0 && (
          <div className="props-empty">
            Frag mich über dein Projekt...
            <div className="ai-suggestions">
              <button className="btn-s btn-sm" onClick={() => { setInput('Beschreibe mein Projekt'); }}>📋 Projekt-Info</button>
              <button className="btn-s btn-sm" onClick={() => { setInput('Füge einen Fade-In Effekt zum ersten Clip hinzu'); }}>✨ Effekt</button>
              <button className="btn-s btn-sm" onClick={() => { setInput('Optimiere die Timeline für ein Karaoke-Video'); }}>🎵 Optimieren</button>
            </div>
          </div>
        )}
        {aiMessages.map((m, i) => (
          <div key={i} className={`ai-msg ai-msg-${m.role}`}>
            <span className="ai-role">{m.role === 'user' ? '👤' : '🤖'}</span>
            {m.role === 'ai' ? (
              <span className="ai-text" dangerouslySetInnerHTML={{ __html: renderMd(m.text) }} />
            ) : (
              <span className="ai-text">{m.text}</span>
            )}
          </div>
        ))}
        {aiStreaming && <div className="ai-typing">⏳</div>}
      </div>
      <div className="ai-input">
        <input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder={pid ? 'Nachricht...' : 'Erst Projekt erstellen'}
          disabled={!pid || aiStreaming} />
        <button className="btn btn-sm" onClick={send} disabled={!pid || aiStreaming || !input.trim()}>→</button>
      </div>
    </div>
  )
}
