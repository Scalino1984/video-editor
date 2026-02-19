import { useState, useEffect } from 'react'
import { useEditorStore } from './stores/useEditorStore'
import { usePlayback } from './hooks/usePlayback'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import Header from './components/Header/Header'
import Sidebar from './components/Sidebar/Sidebar'
import Preview from './components/Preview/Preview'
import Timeline from './components/Timeline/Timeline'
import Properties from './components/Properties/Properties'
import { NewProjectModal, OpenProjectModal } from './components/Modals/Modals'

export default function App() {
  const project = useEditorStore(s => s.project)
  const toasts = useEditorStore(s => s.toasts)
  const { videoRef, audioRef, togglePlay, seek } = usePlayback()
  const [showNewProject, setShowNewProject] = useState(false)
  const [showOpenProject, setShowOpenProject] = useState(false)

  useKeyboardShortcuts(togglePlay)

  // Show new project dialog if no project
  useEffect(() => {
    if (!project) {
      // Small delay to let UI render first
      const t = setTimeout(() => setShowNewProject(true), 300)
      return () => clearTimeout(t)
    }
  }, []) // only on mount

  return (
    <div className="app">
      <Header />

      {project ? (
        <>
          <Sidebar />
          <Preview videoRef={videoRef} audioRef={audioRef} togglePlay={togglePlay} seek={seek} />
          <Properties />
          <Timeline seek={seek} />
        </>
      ) : (
        <div className="welcome-screen">
          <div className="welcome-card">
            <h2>🎬 Video Editor</h2>
            <p>Erstelle oder lade ein Projekt um zu starten.</p>
            <div className="welcome-actions">
              <button className="btn" onClick={() => setShowNewProject(true)}>
                + Neues Projekt
              </button>
              <button className="btn-s" onClick={() => setShowOpenProject(true)}>
                📂 Projekt öffnen
              </button>
            </div>
          </div>
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

      {/* Style for modal items */}
      <style>{`
        .modal-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 10px;
          border-radius: 6px;
          cursor: pointer;
          transition: background .12s;
        }
        .modal-item:hover { background: var(--bg4); }
        .welcome-screen {
          grid-column: 1 / -1;
          grid-row: 2 / -1;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--bg);
        }
        .welcome-card {
          text-align: center;
          padding: 48px;
          background: var(--bg2);
          border: 1px solid var(--border);
          border-radius: 16px;
        }
        .welcome-card h2 {
          font-size: 1.6rem;
          margin-bottom: 8px;
          background: linear-gradient(135deg, var(--accent), var(--accent2));
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }
        .welcome-card p {
          color: var(--dim);
          margin-bottom: 24px;
          font-size: .88rem;
        }
        .welcome-actions {
          display: flex;
          gap: 12px;
          justify-content: center;
        }
      `}</style>
    </div>
  )
}
