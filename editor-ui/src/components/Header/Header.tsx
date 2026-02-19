import { useState, useEffect } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import type { Theme } from '../../types'
import './Header.css'

const THEMES: { key: Theme; cls: string }[] = [
  { key: 'default', cls: 'tsw-dark' },
  { key: 'neon', cls: 'tsw-neon' },
  { key: 'light', cls: 'tsw-light' },
  { key: 'warm', cls: 'tsw-warm' },
]

interface HeaderProps {
  onNewProject: () => void
  onOpenProject: () => void
  onOpenJobModal: () => void
}

export default function Header({ onNewProject, onOpenProject, onOpenJobModal }: HeaderProps) {
  const project = useEditorStore(s => s.project)
  const theme = useEditorStore(s => s.theme)
  const rendering = useEditorStore(s => s.rendering)
  const setTheme = useEditorStore(s => s.setTheme)
  const undoAction = useEditorStore(s => s.undoAction)
  const redoAction = useEditorStore(s => s.redoAction)
  const saveProject = useEditorStore(s => s.saveProject)
  const renderProject = useEditorStore(s => s.renderProject)
  const updateProjectProp = useEditorStore(s => s.updateProjectProp)
  const [editing, setEditing] = useState(false)
  const [nameVal, setNameVal] = useState('')

  // ── Theme persistence ──
  useEffect(() => {
    try {
      const saved = localStorage.getItem('kst-editor-theme') as Theme | null
      if (saved && saved !== 'default') setTheme(saved)
    } catch { /* noop */ }
  }, []) // eslint-disable-line

  const handleTheme = (t: Theme) => {
    setTheme(t)
    try { localStorage.setItem('kst-editor-theme', t) } catch { /* noop */ }
  }

  // ── Loop Render ──
  const handleRenderLoop = async () => {
    if (!project) return
    const assets = Object.values(project.assets).filter(a => a.type === 'video' || a.type === 'image')
    if (!assets.length) { useEditorStore.getState().toast('Kein Video/Bild-Asset für Loop', 'err'); return }
    const loopStr = prompt('Loop-Anzahl:', '3')
    if (!loopStr) return
    const loops = parseInt(loopStr) || 3
    const durStr = prompt('Dauer (0=auto):', '0')
    const dur = parseFloat(durStr || '0') || 0
    useEditorStore.getState().renderLoop(assets[0].id, loops, dur)
  }

  const startEditName = () => {
    if (!project) return
    setNameVal(project.name)
    setEditing(true)
  }
  const saveName = () => {
    setEditing(false)
    if (nameVal.trim() && nameVal !== project?.name)
      updateProjectProp('name', nameVal.trim())
  }

  return (
    <header className="hdr">
      <a href="/" className="hdr-logo" title="Zurück zum Karaoke Tool">
        <span>♪</span><span className="hdr-logo-text">KST</span>
      </a>
      <h1>🎬 Video Editor</h1>
      <span className="v">v4.0</span>

      <span className="hdr-sep" />

      {/* Undo/Redo */}
      <div className="hdr-group">
        <button className="btn-s btn-sm" onClick={undoAction} title="Undo (Ctrl+Z)">↩ Undo</button>
        <button className="btn-s btn-sm" onClick={redoAction} title="Redo (Ctrl+Y)">↪ Redo</button>
      </div>

      <span className="hdr-sep" />

      {/* Project Actions */}
      <div className="hdr-group">
        <button className="btn-s btn-sm" onClick={onNewProject}>📄 Neu</button>
        <button className="btn-s btn-sm" onClick={onOpenProject}>📂 Projekte</button>
        <button className="btn-s btn-sm" onClick={saveProject}>💾 Save</button>
        <button className="btn-s btn-sm" onClick={onOpenJobModal}>📥 Import Job</button>
      </div>

      <span className="hdr-sep" />

      {/* Render */}
      <div className="hdr-group">
        <button className="btn btn-sm" onClick={renderProject} disabled={rendering}>
          {rendering ? '⏳ Rendering...' : '🎬 Render'}
        </button>
        <button className="btn-s btn-sm" onClick={handleRenderLoop} title="Loop Video rendern">🔁 Loop</button>
      </div>

      {/* Right side */}
      <div className="hdr-spacer" />

      {/* Theme Switcher */}
      <div className="hdr-themes">
        {THEMES.map(t => (
          <button key={t.key} className={`${t.cls} ${theme === t.key ? 'on' : ''}`}
            onClick={() => handleTheme(t.key)} />
        ))}
      </div>

      <a href="/" className="btn-s btn-sm hdr-kst-link">🎤 Karaoke Tool</a>

      {/* Project Name */}
      {project && (
        editing ? (
          <input className="hdr-name-input" value={nameVal}
            onChange={e => setNameVal(e.target.value)}
            onBlur={saveName} onKeyDown={e => e.key === 'Enter' && saveName()} autoFocus />
        ) : (
          <span className="hdr-name" onDoubleClick={startEditName} title="Doppelklick zum Umbenennen">
            {project.name}
          </span>
        )
      )}
    </header>
  )
}
