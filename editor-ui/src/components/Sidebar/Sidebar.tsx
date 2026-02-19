import { useRef, useState, useEffect, useCallback } from 'react'
import { useEditorStore } from '../../stores/useEditorStore'
import * as api from '../../api/editor'
import type { JobItem } from '../../types'
import './Sidebar.css'

const TYPE_ICONS: Record<string, string> = { video: '🎬', audio: '🎵', image: '🖼️', subtitle: '📝' }

export default function Sidebar() {
  const project = useEditorStore(s => s.project)
  const pid = useEditorStore(s => s.pid)
  const sidebarTab = useEditorStore(s => s.sidebarTab)
  const setSidebarTab = useEditorStore(s => s.setSidebarTab)
  const uploadAssets = useEditorStore(s => s.uploadAssets)
  const addToTimeline = useEditorStore(s => s.addToTimeline)
  const deleteAsset = useEditorStore(s => s.deleteAsset)
  const fileRef = useRef<HTMLInputElement>(null)
  const [selectedAsset, setSelectedAsset] = useState<string | null>(null)

  const assets = project ? Object.values(project.assets) : []
  const [dragOver, setDragOver] = useState(false)

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false)
    if (e.dataTransfer.files.length) uploadAssets(e.dataTransfer.files)
  }, [uploadAssets])

  const handleDragStart = (e: React.DragEvent, assetId: string, type: string) => {
    e.dataTransfer.setData('asset_id', assetId)
    e.dataTransfer.setData('asset_type', type)
  }

  return (
    <div className="sidebar" onDrop={handleDrop} onDragOver={e => { e.preventDefault(); setDragOver(true) }} onDragLeave={() => setDragOver(false)}>
      <div className="sb-tabs">
        <button className={sidebarTab === 'assets' ? 'active' : ''} onClick={() => setSidebarTab('assets')}>📁 Assets</button>
        <button className={sidebarTab === 'jobs' ? 'active' : ''} onClick={() => setSidebarTab('jobs')}>🎤 Jobs</button>
        <button className={sidebarTab === 'templates' ? 'active' : ''} onClick={() => setSidebarTab('templates')}>📐 Templates</button>
      </div>
      {sidebarTab === 'assets' && (
        <div className="sb-content">
          <div className={`asset-dz ${dragOver ? 'drag-active' : ''}`}
            onClick={() => fileRef.current?.click()}>
            <span className="dz-ico">📂</span>
            <b>Assets hochladen</b>
            <div className="dz-hint">Video, Audio, Bild, SRT, ASS, LRC</div>
          </div>
          <input ref={fileRef} type="file" multiple accept="video/*,audio/*,image/*,.srt,.ass,.vtt,.lrc"
            style={{ display: 'none' }} onChange={e => e.target.files && uploadAssets(e.target.files)} />
          <div className="asset-list">
            {assets.length === 0 && <div className="sb-empty">Drag &amp; Drop oder Button</div>}
            {assets.map(a => (
              <div key={a.id}
                className={`asset-item ${selectedAsset === a.id ? 'sel' : ''}`}
                draggable onDragStart={e => handleDragStart(e, a.id, a.type)}
                onClick={() => setSelectedAsset(a.id)}
                onDoubleClick={() => addToTimeline(a.id)}
                title={`${a.filename} · Doppelklick = Timeline`}>
                <div className="asset-thumb">
                  {a.thumbnail && pid ? (
                    <img src={api.assetThumbUrl(pid, a.id)} alt="" />
                  ) : (
                    <span>{TYPE_ICONS[a.type] || '📄'}</span>
                  )}
                </div>
                <div className="asset-info">
                  <span className="asset-name">{a.filename}</span>
                  <span className="asset-meta">
                    {a.type}{a.duration > 0 ? ` · ${a.duration.toFixed(1)}s` : ''}
                    {a.width > 0 ? ` · ${a.width}×${a.height}` : ''}
                  </span>
                </div>
                <span className={`asset-type at-${a.type}`}>{a.type}</span>
                <button className="btn-add-tl" onClick={e => { e.stopPropagation(); addToTimeline(a.id) }}
                  title="Zur Timeline">+</button>
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
  const importJobFromLibrary = useEditorStore(s => s.importJobFromLibrary)

  useEffect(() => {
    api.listLibrary(200).then(r => { if (r.items) setJobs(r.items) }).catch(() => {})
  }, [])

  const filtered = jobs.filter(j => {
    const q = filter.toLowerCase()
    return !q || (j.title || j.source_filename || '').toLowerCase().includes(q)
  })

  return (
    <div className="sb-content">
      <input className="sb-search" placeholder="🔍 Jobs suchen..." value={filter}
        onChange={e => setFilter(e.target.value)} />
      <div className="job-list">
        {filtered.map(j => {
          const jid = j.job_id || j.id || ''
          const name = j.title || j.source_filename || jid
          return (
            <div key={jid} className="job-item" onClick={() => importJobFromLibrary(jid, name)}>
              <span className="job-icon">🎤</span>
              <div className="job-info">
                <span className="job-name">{name}</span>
                <span className="job-meta">
                  {j.segments_count ? `${j.segments_count} Segs` : ''}{j.backend ? ` · ${j.backend}` : ''}
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
  const quickTemplate = useEditorStore(s => s.quickTemplate)

  const templates = [
    { type: 'karaoke', label: '🎵 Karaoke Video', desc: '1920×1080 — Bild + Audio + Untertitel' },
    { type: 'music_video', label: '🎬 Musik Video', desc: '1920×1080 — Vollständiges Musikvideo' },
    { type: 'vertical', label: '📱 Vertical Video', desc: '1080×1920 — 9:16 für TikTok/Reels' },
    { type: 'loop', label: '🔁 Loop Video', desc: '1920×1080 — Loop-Render' },
    { type: 'slideshow', label: '🖼️ Slideshow', desc: '1920×1080 — Bilder mit Übergängen' },
  ]

  return (
    <div className="sb-content">
      {templates.map(t => (
        <div key={t.type} className="template-item" onClick={() => quickTemplate(t.type)}>
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
