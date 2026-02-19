import { useState, useEffect } from 'react'
import { useEditorStore } from './stores/useEditorStore'
import { usePlayback } from './hooks/usePlayback'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import Header from './components/Header/Header'
import Sidebar from './components/Sidebar/Sidebar'
import Preview from './components/Preview/Preview'
import Timeline from './components/Timeline/Timeline'
import Properties from './components/Properties/Properties'
import { NewProjectModal, OpenProjectModal, JobImportModal } from './components/Modals/Modals'
import * as api from './api/editor'

export default function App() {
  const project = useEditorStore(s => s.project)
  const toasts = useEditorStore(s => s.toasts)
  const renderResult = useEditorStore(s => s.renderResult)
  const clearRenderResult = useEditorStore(s => s.clearRenderResult)
  const loadProject = useEditorStore(s => s.loadProject)

  const { videoRef, audioRef, togglePlay, seek, stop, syncMediaSources } = usePlayback()
  const [showNewProject, setShowNewProject] = useState(false)
  const [showOpenProject, setShowOpenProject] = useState(false)
  const [showJobModal, setShowJobModal] = useState(false)

  useKeyboardShortcuts(togglePlay, stop, seek)

  // ── Auto-load last project on mount ──
  useEffect(() => {
    (async () => {
      try {
        const projects = await api.listProjects()
        if (projects.length > 0) {
          const last = projects[projects.length - 1]
          await loadProject((last as any).id)
        }
      } catch { /* no projects yet */ }
    })()
  }, []) // eslint-disable-line

  return (
    <div className="app">
      <Header
        onNewProject={() => setShowNewProject(true)}
        onOpenProject={() => setShowOpenProject(true)}
        onOpenJobModal={() => setShowJobModal(true)}
      />

      {project ? (
        <>
          <Sidebar />
          <Preview videoRef={videoRef} audioRef={audioRef}
            togglePlay={togglePlay} seek={seek} stop={stop}
            syncMediaSources={syncMediaSources} />
          <Properties />
          <Timeline seek={seek} />
        </>
      ) : (
        <div className="welcome-screen">
          <div className="welcome-card">
            <h2>🎬 Video Editor</h2>
            <p>Erstelle oder lade ein Projekt um zu starten.</p>
            <div className="welcome-actions">
              <button className="btn" onClick={() => setShowNewProject(true)}>+ Neues Projekt</button>
              <button className="btn-s" onClick={() => setShowOpenProject(true)}>📂 Projekt öffnen</button>
              <button className="btn-s" onClick={() => setShowJobModal(true)}>📥 Job importieren</button>
            </div>
          </div>
        </div>
      )}

      {/* Render Result Download Bar */}
      {renderResult && (
        <div className="render-bar">
          <span className="render-file">✅ {renderResult.file}</span>
          <span className="render-size">{renderResult.size_mb} MB</span>
          <a href={api.renderDownloadUrl(renderResult.file)} download={renderResult.file}
            className="render-dl">⬇ Download</a>
          <button className="render-close" onClick={clearRenderResult}>✕</button>
        </div>
      )}

      {/* Toasts */}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast-item ${t.type}`}>{t.msg}</div>
        ))}
      </div>

      {/* Modals */}
      <NewProjectModal open={showNewProject} onClose={() => setShowNewProject(false)} />
      <OpenProjectModal open={showOpenProject} onClose={() => setShowOpenProject(false)} />
      <JobImportModal open={showJobModal} onClose={() => setShowJobModal(false)} />
    </div>
  )
}
