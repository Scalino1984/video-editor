import { useState, useCallback } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import { hexToAss, hexToAssBg, assToHex, assAlpha, fmt } from '../../utils/format'
import { EFFECTS_LIST } from '../../types'
import type { PropTab } from '../../types'
import './Properties.css'

export default function Properties() {
  const project = useEditorStore(s => s.project)
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

// ── Clip Properties ──
function ClipProps() {
  const project = useEditorStore(s => s.project)
  const selectedClip = useEditorStore(s => s.selectedClip)
  const updateProjectProp = useEditorStore(s => s.updateProjectProp)
  const deleteSelectedClip = useEditorStore(s => s.deleteSelectedClip)
  const splitAtPlayhead = useEditorStore(s => s.splitAtPlayhead)
  const refreshProject = useEditorStore(s => s.refreshProject)

  if (!project || !selectedClip) return null
  const clip = project.clips.find(c => c.id === selectedClip)
  if (!clip) return null
  const asset = project.assets[clip.asset_id]

  const updateClip = async (key: string, value: unknown) => {
    const newClips = project.clips.map(c =>
      c.id === selectedClip ? { ...c, [key]: value } : c
    )
    await updateProjectProp('clips', newClips)
    await refreshProject()
  }

  return (
    <div className="props-section">
      <div className="section-title">Clip: {asset?.filename || clip.id}</div>
      <div className="props-grid">
        <div className="prop-row">
          <label>Start</label>
          <input type="number" value={clip.start.toFixed(2)} step="0.1" min="0"
            onChange={e => updateClip('start', +e.target.value)} />
        </div>
        <div className="prop-row">
          <label>Dauer</label>
          <input type="number" value={clip.duration.toFixed(2)} step="0.1" min="0.1"
            onChange={e => updateClip('duration', +e.target.value)} />
        </div>
        <div className="prop-row">
          <label>In-Point</label>
          <input type="number" value={clip.in_point.toFixed(2)} step="0.1" min="0"
            onChange={e => updateClip('in_point', +e.target.value)} />
        </div>

        {clip.track === 'audio' && (
          <div className="prop-row">
            <label>Vol</label>
            <input type="range" min="0" max="2" step="0.05" value={clip.volume}
              onChange={e => updateClip('volume', +e.target.value)} />
            <span className="prop-val">{(clip.volume * 100).toFixed(0)}%</span>
          </div>
        )}

        <div className="prop-row">
          <label>Speed</label>
          <input type="range" min="0.25" max="4" step="0.25" value={clip.speed}
            onChange={e => updateClip('speed', +e.target.value)} />
          <span className="prop-val">{clip.speed}×</span>
        </div>

        <div className="prop-row">
          <label>Loop</label>
          <input type="checkbox" checked={clip.loop} style={{ width: 'auto' }}
            onChange={e => updateClip('loop', e.target.checked)} />
        </div>

        <div className="prop-row">
          <label>Z-Index</label>
          <input type="number" value={clip.z_index} min="0" max="100"
            onChange={e => updateClip('z_index', +e.target.value)} />
        </div>
      </div>

      <div className="props-actions">
        <button className="btn-s btn-sm" onClick={splitAtPlayhead} title="Split (S)">✂ Split</button>
        <button className="btn-d btn-sm" onClick={deleteSelectedClip} title="Löschen (Del)">🗑 Löschen</button>
      </div>
    </div>
  )
}

// ── Effects ──
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
      <div className="section-title">Effekte</div>

      {/* Active effects */}
      {clip.effects.map((fx, i) => (
        <div key={i} className="fx-item">
          <span className="fx-name">{fx.type}</span>
          <span className="fx-val">{fx.value}</span>
          <button className="btn-d btn-sm fx-rm" onClick={() => removeEffect(i)}>✕</button>
        </div>
      ))}

      {clip.effects.length === 0 && (
        <div className="props-empty">Keine Effekte</div>
      )}

      {/* Add effect */}
      <div className="section-title" style={{ marginTop: 12 }}>Hinzufügen</div>
      <div className="fx-grid">
        {EFFECTS_LIST.map(fx => (
          <button
            key={fx.type}
            className="btn-s btn-sm fx-add"
            onClick={() => addEffect(fx.type, fx.value)}
          >
            {fx.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Project Settings (including subtitle) ──
function ProjectProps() {
  const project = useEditorStore(s => s.project)
  const updateProjectProp = useEditorStore(s => s.updateProjectProp)

  if (!project) return <div className="props-empty">Kein Projekt geladen</div>

  const up = (key: string, val: unknown) => updateProjectProp(key, val)

  return (
    <div className="props-section props-scroll">
      {/* Format */}
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
            <option>ultrafast</option><option>superfast</option><option>fast</option>
            <option>medium</option><option>slow</option><option>veryslow</option>
          </select>
        </div>
        <div className="prop-row">
          <label>CRF</label>
          <input type="range" min="15" max="35" value={project.crf}
            onChange={e => up('crf', +e.target.value)} />
          <span className="prop-val">{project.crf}</span>
        </div>
      </div>

      {/* Format Presets */}
      <div className="props-presets">
        {[
          { l: '1080p', w: 1920, h: 1080 },
          { l: '720p', w: 1280, h: 720 },
          { l: '9:16', w: 1080, h: 1920 },
          { l: '1:1', w: 1080, h: 1080 },
        ].map(p => (
          <button key={p.l} className="btn-s btn-sm" onClick={() => { up('width', p.w); up('height', p.h) }}>
            {p.l}
          </button>
        ))}
      </div>

      {/* Subtitle Settings */}
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
          <span className="prop-val">{project.sub_outline_width}</span>
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
          <label>Hintergrund</label>
          <input type="checkbox" checked={project.sub_bg_enabled} style={{ width: 'auto' }}
            onChange={e => up('sub_bg_enabled', e.target.checked)} />
          <input type="color" value={assToHex(project.sub_bg_color)}
            onInput={e => {
              const alpha = document.getElementById('bgAlpha') as HTMLInputElement
              up('sub_bg_color', hexToAssBg((e.target as HTMLInputElement).value, +alpha.value))
            }}
            style={{ width: 30, height: 20, padding: 0, border: 'none' }} />
          <input id="bgAlpha" type="range" min="0" max="255" value={assAlpha(project.sub_bg_color)}
            style={{ flex: 1 }}
            onChange={e => {
              const bgHex = assToHex(project.sub_bg_color)
              up('sub_bg_color', hexToAssBg(bgHex, +e.target.value))
            }} />
          <span className="prop-val">{Math.round(assAlpha(project.sub_bg_color) / 255 * 100)}%</span>
        </div>
      </div>
    </div>
  )
}

// ── AI Chat ──
function AIChat() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<{ role: string; text: string }[]>([])
  const toast = useEditorStore(s => s.toast)

  const send = useCallback(async () => {
    if (!input.trim()) return
    const msg = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', text: msg }])

    // TODO: Connect to actual AI endpoint
    setMessages(prev => [...prev, { role: 'ai', text: 'AI Chat coming soon. Nachricht: ' + msg }])
    toast('AI: Feature in Entwicklung')
  }, [input, toast])

  return (
    <div className="props-section ai-chat">
      <div className="section-title">AI Assistent</div>
      <div className="ai-messages">
        {messages.length === 0 && (
          <div className="props-empty">
            Frag mich etwas über dein Projekt...
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`ai-msg ai-msg-${m.role}`}>
            <span className="ai-role">{m.role === 'user' ? '👤' : '🤖'}</span>
            <span className="ai-text">{m.text}</span>
          </div>
        ))}
      </div>
      <div className="ai-input">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send()}
          placeholder="Nachricht..."
        />
        <button className="btn btn-sm" onClick={send}>→</button>
      </div>
    </div>
  )
}
