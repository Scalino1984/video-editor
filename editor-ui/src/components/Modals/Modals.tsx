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
    api.listProjects()
      .then(data => { if (Array.isArray(data)) setMemProjects(data) })
      .catch(() => {})

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
                  <div style={{ fontWeight: 600, fontSize: '.82rem' }}>{s.name || s.filename}</div>
                  <div style={{ fontSize: '.65rem', color: 'var(--dim)' }}>
                    {s.filename} · {s.size_kb}KB · {s.date}
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

// ── Job Import Modal (full modal with search like original) ──
export function JobImportModal({ open, onClose }: ModalProps) {
  const [jobs, setJobs] = useState<any[]>([])
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const importJobFromLibrary = useEditorStore(s => s.importJobFromLibrary)
  const toast = useEditorStore(s => s.toast)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    api.listLibrary(200)
      .then(r => { setJobs(r.items || []); setLoading(false) })
      .catch(e => { toast(e.message, 'err'); setLoading(false) })
  }, [open]) // eslint-disable-line

  const filtered = jobs.filter(j => {
    const q = filter.toLowerCase()
    const name = (j.title || j.source_filename || j.id || '').toLowerCase()
    const backend = (j.backend || '').toLowerCase()
    return !q || name.includes(q) || backend.includes(q)
  })

  const doImport = async (jobId: string, name: string) => {
    onClose()
    await importJobFromLibrary(jobId, name)
  }

  const fmtTime = (s: number) => { if (!s || s <= 0) return ''; const m = Math.floor(s / 60); return m + ':' + String(Math.floor(s % 60)).padStart(2, '0') }

  if (!open) return null
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-wide" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>📥 Job importieren</h3>
          <input type="text" placeholder="Suchen..." value={filter}
            onChange={e => setFilter(e.target.value)}
            style={{ width: 160, fontSize: '.72rem' }} />
          <button className="btn-s btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {loading && <div style={{ color: 'var(--dim)', textAlign: 'center', padding: 30 }}>⏳ Lade Library...</div>}
          {!loading && filtered.length === 0 && (
            <div style={{ color: 'var(--dim)', textAlign: 'center', padding: 30 }}>Keine passenden Einträge</div>
          )}
          {filtered.map(j => {
            const jid = j.job_id || j.id || ''
            const name = j.title || j.source_filename || '?'
            const segs = j.segments_count || 0
            const dur = fmtTime(j.duration_sec)
            const conf = j.avg_confidence > 0 ? Math.round(j.avg_confidence * 100) + '%' : ''
            const date = j.updated_at || j.created_at || ''
            const dateStr = date ? new Date(date).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
            return (
              <div key={jid} className="modal-item" onClick={() => doImport(jid, name)}>
                <span style={{ fontSize: '1.2rem', width: 32, height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg4)', borderRadius: 6 }}>🎤</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '.8rem' }}>{name}</div>
                  <div style={{ fontSize: '.6rem', color: 'var(--dim)', fontFamily: 'var(--mono)' }}>
                    {j.backend || '?'} · {dur} · {segs} Seg{conf ? ' · ' + conf : ''} · {dateStr}
                  </div>
                </div>
                <span style={{ fontSize: '.55rem', padding: '2px 6px', borderRadius: 3, background: 'rgba(0,229,160,.12)', color: 'var(--accent)', fontWeight: 600 }}>
                  {j.language || 'auto'}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
