import { useState, useEffect } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import * as api from '../../api/editor'
import type { SavedProject, Project } from '../../types'

interface ModalProps {
  open: boolean
  onClose: () => void
}

// ── New Project Modal ──
export function NewProjectModal({ open, onClose }: ModalProps) {
  const [name, setName] = useState('Mein Projekt')
  const createProject = useEditorStore(s => s.createProject)

  const submit = async () => {
    if (!name.trim()) return
    await createProject(name.trim())
    onClose()
  }

  if (!open) return null
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <h3>🎬 Neues Projekt</h3>
        <div style={{ marginBottom: 12 }}>
          <label>Projektname</label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submit()}
            autoFocus
          />
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn-s" onClick={onClose}>Abbrechen</button>
          <button className="btn" onClick={submit}>Erstellen</button>
        </div>
      </div>
    </div>
  )
}

// ── Open Project Modal ──
export function OpenProjectModal({ open, onClose }: ModalProps) {
  const [saved, setSaved] = useState<SavedProject[]>([])
  const [memProjects, setMemProjects] = useState<Project[]>([])
  const loadProject = useEditorStore(s => s.loadProject)
  const toast = useEditorStore(s => s.toast)

  useEffect(() => {
    if (!open) return
    // Load in-memory projects
    api.getProject('').catch(() => null)
    fetch(window.location.origin + '/api/editor/projects')
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data)) setMemProjects(data)
      }).catch(() => {})

    // Load saved projects
    api.listSavedProjects()
      .then(setSaved)
      .catch(() => {})
  }, [open])

  const openMem = async (pid: string) => {
    await loadProject(pid)
    onClose()
  }

  const openSaved = async (filename: string) => {
    try {
      const proj = await api.loadSavedProject(filename)
      await loadProject(proj.id)
      onClose()
    } catch (e) {
      toast('Laden fehlgeschlagen', 'err')
    }
  }

  if (!open) return null
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <h3>📂 Projekt öffnen</h3>

        {memProjects.length > 0 && (
          <>
            <div style={{ fontSize: '.72rem', color: 'var(--dim)', fontWeight: 600, margin: '8px 0 4px', textTransform: 'uppercase' }}>
              Aktive Projekte
            </div>
            {memProjects.map((p: any) => (
              <div
                key={p.id}
                className="modal-item"
                onClick={() => openMem(p.id)}
              >
                <span>🎬</span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '.82rem' }}>{p.name}</div>
                  <div style={{ fontSize: '.65rem', color: 'var(--dim)' }}>
                    {p.clips?.length || 0} Clips · {p.width}×{p.height}
                  </div>
                </div>
              </div>
            ))}
          </>
        )}

        {saved.length > 0 && (
          <>
            <div style={{ fontSize: '.72rem', color: 'var(--dim)', fontWeight: 600, margin: '12px 0 4px', textTransform: 'uppercase' }}>
              Gespeicherte Projekte
            </div>
            {saved.map(s => (
              <div
                key={s.filename}
                className="modal-item"
                onClick={() => openSaved(s.filename)}
              >
                <span>💾</span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '.82rem' }}>{s.filename}</div>
                  <div style={{ fontSize: '.65rem', color: 'var(--dim)' }}>
                    {(s.size / 1024).toFixed(1)} KB · {new Date(s.modified).toLocaleDateString('de')}
                  </div>
                </div>
              </div>
            ))}
          </>
        )}

        {memProjects.length === 0 && saved.length === 0 && (
          <div style={{ textAlign: 'center', color: 'var(--dim)', padding: 24 }}>
            Keine Projekte vorhanden
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
          <button className="btn-s" onClick={onClose}>Schließen</button>
        </div>
      </div>
    </div>
  )
}
