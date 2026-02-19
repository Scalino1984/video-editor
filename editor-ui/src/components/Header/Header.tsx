import { useState } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import type { Theme } from '../../types'
import './Header.css'

const THEMES: { key: Theme; label: string }[] = [
  { key: 'default', label: '🌙' },
  { key: 'neon', label: '💜' },
  { key: 'light', label: '☀️' },
  { key: 'warm', label: '🔥' },
]

export default function Header() {
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

  const startEditName = () => {
    if (!project) return
    setNameVal(project.name)
    setEditing(true)
  }

  const saveName = () => {
    setEditing(false)
    if (nameVal.trim() && nameVal !== project?.name) {
      updateProjectProp('name', nameVal.trim())
    }
  }

  return (
    <header className="hdr">
      <h1>🎬 Video Editor</h1>
      <span className="v">v4.0</span>

      {project && (
        <>
          <span className="hdr-sep">|</span>
          {editing ? (
            <input
              className="hdr-name-input"
              value={nameVal}
              onChange={e => setNameVal(e.target.value)}
              onBlur={saveName}
              onKeyDown={e => e.key === 'Enter' && saveName()}
              autoFocus
            />
          ) : (
            <span className="hdr-name" onDoubleClick={startEditName} title="Doppelklick zum Umbenennen">
              {project.name}
            </span>
          )}
          <span className="hdr-dim">
            {project.width}×{project.height} · {project.clips.length} Clips
          </span>
        </>
      )}

      <div className="hdr-spacer" />

      {/* Theme Switcher */}
      <div className="hdr-themes">
        {THEMES.map(t => (
          <button
            key={t.key}
            className={`btn-sm btn-s ${theme === t.key ? 'active' : ''}`}
            onClick={() => setTheme(t.key)}
            title={t.key}
          >
            {t.label}
          </button>
        ))}
      </div>

      {project && (
        <>
          <button className="btn-s btn-sm" onClick={undoAction} title="Undo (Ctrl+Z)">↩</button>
          <button className="btn-s btn-sm" onClick={redoAction} title="Redo (Ctrl+Y)">↪</button>
          <button className="btn-s btn-sm" onClick={saveProject} title="Speichern (Ctrl+S)">💾</button>
          <button
            className="btn btn-sm"
            onClick={renderProject}
            disabled={rendering}
          >
            {rendering ? '⏳ Rendering...' : '🎬 Render'}
          </button>
        </>
      )}
    </header>
  )
}
