import { useRef, useState, useEffect, useCallback } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import * as api from '../../api/editor'
import type { JobItem } from '../../types'
import './Sidebar.css'

const TYPE_ICONS: Record<string, string> = {
  video: '🎬', audio: '🎵', image: '🖼️', subtitle: '📝',
}

export default function Sidebar() {
  const project = useEditorStore(s => s.project)
  const pid = useEditorStore(s => s.pid)
  const sidebarTab = useEditorStore(s => s.sidebarTab)
  const setSidebarTab = useEditorStore(s => s.setSidebarTab)
  const uploadAssets = useEditorStore(s => s.uploadAssets)
  const addToTimeline = useEditorStore(s => s.addToTimeline)
  const selectClip = useEditorStore(s => s.selectClip)
  const fileRef = useRef<HTMLInputElement>(null)

  const assets = project ? Object.values(project.assets) : []

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.files.length) uploadAssets(e.dataTransfer.files)
  }, [uploadAssets])

  const handleDragStart = (e: React.DragEvent, assetId: string, type: string) => {
    e.dataTransfer.setData('asset_id', assetId)
    e.dataTransfer.setData('asset_type', type)
  }

  return (
    <div className="sidebar" onDrop={handleDrop} onDragOver={e => e.preventDefault()}>
      <div className="sb-tabs">
        <button className={sidebarTab === 'assets' ? 'active' : ''} onClick={() => setSidebarTab('assets')}>📁 Assets</button>
        <button className={sidebarTab === 'jobs' ? 'active' : ''} onClick={() => setSidebarTab('jobs')}>🎤 Jobs</button>
        <button className={sidebarTab === 'templates' ? 'active' : ''} onClick={() => setSidebarTab('templates')}>📐 Templates</button>
      </div>

      {sidebarTab === 'assets' && (
        <div className="sb-content">
          <div className="sb-actions">
            <button className="btn btn-sm" onClick={() => fileRef.current?.click()}>
              + Asset hochladen
            </button>
            <input
              ref={fileRef}
              type="file"
              multiple
              accept="video/*,audio/*,image/*,.srt,.ass,.vtt"
              style={{ display: 'none' }}
              onChange={e => e.target.files && uploadAssets(e.target.files)}
            />
          </div>
          <div className="asset-list">
            {assets.length === 0 && (
              <div className="sb-empty">Drag & Drop oder Button zum Hochladen</div>
            )}
            {assets.map(a => (
              <div
                key={a.id}
                className="asset-item"
                draggable
                onDragStart={e => handleDragStart(e, a.id, a.type)}
                onDoubleClick={() => addToTimeline(a.id)}
                title={`${a.filename} · Doppelklick = Timeline`}
              >
                <span className="asset-icon">{TYPE_ICONS[a.type] || '📄'}</span>
                <div className="asset-info">
                  <span className="asset-name">{a.filename}</span>
                  <span className="asset-meta">
                    {a.type}{a.duration > 0 ? ` · ${a.duration.toFixed(1)}s` : ''}
                  </span>
                </div>
                <button
                  className="btn-add-tl"
                  onClick={e => { e.stopPropagation(); addToTimeline(a.id) }}
                  title="Zur Timeline hinzufügen"
                >
                  +
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {sidebarTab === 'jobs' && <JobsPanel />}
      {sidebarTab === 'templates' && <TemplatesPanel />}
    </div>
  )
}

function JobsPanel() {
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [filter, setFilter] = useState('')
  const pid = useEditorStore(s => s.pid)
  const refreshProject = useEditorStore(s => s.refreshProject)
  const toast = useEditorStore(s => s.toast)

  useEffect(() => {
    api.listLibrary(200).then(r => {
      if (r.items) setJobs(r.items)
    }).catch(() => {})
  }, [])

  const doImport = async (jobId: string, name: string) => {
    if (!pid) return
    try {
      await api.importJob(pid, jobId)
      await refreshProject()
      toast('Importiert: ' + name)
    } catch {
      toast('Import Fehler', 'err')
    }
  }

  const filtered = jobs.filter(j => {
    const q = filter.toLowerCase()
    const n = (j.title || j.source_filename || '').toLowerCase()
    return !q || n.includes(q)
  })

  return (
    <div className="sb-content">
      <input
        className="sb-search"
        placeholder="🔍 Jobs suchen..."
        value={filter}
        onChange={e => setFilter(e.target.value)}
      />
      <div className="job-list">
        {filtered.map(j => {
          const jid = j.job_id || j.id || ''
          const name = j.title || j.source_filename || jid
          return (
            <div key={jid} className="job-item" onClick={() => doImport(jid, name)}>
              <span className="job-icon">🎤</span>
              <div className="job-info">
                <span className="job-name">{name}</span>
                <span className="job-meta">
                  {j.segments_count ? `${j.segments_count} Segs` : ''}
                  {j.backend ? ` · ${j.backend}` : ''}
                </span>
              </div>
              <span className="job-import">→</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function TemplatesPanel() {
  const pid = useEditorStore(s => s.pid)
  const refreshProject = useEditorStore(s => s.refreshProject)
  const toast = useEditorStore(s => s.toast)

  const templates = [
    { type: 'lyric_video', label: '🎵 Lyric Video', desc: 'Bild + Audio + Untertitel' },
    { type: 'slideshow', label: '🖼️ Slideshow', desc: 'Bilder mit Übergängen' },
    { type: 'podcast', label: '🎙️ Podcast', desc: 'Audio mit Waveform' },
  ]

  const apply = async (type: string) => {
    if (!pid) return
    toast('Template: ' + type + ' (coming soon)')
  }

  return (
    <div className="sb-content">
      {templates.map(t => (
        <div key={t.type} className="template-item" onClick={() => apply(t.type)}>
          <span className="template-icon">{t.label.split(' ')[0]}</span>
          <div className="template-info">
            <span className="template-name">{t.label.split(' ').slice(1).join(' ')}</span>
            <span className="template-desc">{t.desc}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
