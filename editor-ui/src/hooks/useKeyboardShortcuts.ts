import { useEffect } from 'react'
import { useEditorStore } from '../stores/useEditorStore'

export function useKeyboardShortcuts(togglePlay: () => void, stop: () => void, seek: (t: number) => void) {
  useEffect(() => {
    const handle = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      const s = useEditorStore.getState()
      if (!s.pid) return

      // Space = play/pause
      if (ev.code === 'Space') { ev.preventDefault(); togglePlay() }

      // Ctrl+Z / Ctrl+Y / Ctrl+S
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 'z') { ev.preventDefault(); s.undoAction() }
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 'y') { ev.preventDefault(); s.redoAction() }
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 's') { ev.preventDefault(); s.saveProject() }

      // Delete / Backspace
      if (ev.key === 'Delete' || ev.key === 'Backspace') { ev.preventDefault(); s.deleteSelectedClip() }

      // S = split, D = duplicate
      if (ev.key === 's' && !ev.ctrlKey && !ev.metaKey) { ev.preventDefault(); s.splitAtPlayhead() }
      if (ev.key === 'd' && !ev.ctrlKey && !ev.metaKey) { ev.preventDefault(); s.duplicateClip() }

      // Arrow keys = ±2s
      if (ev.key === 'ArrowLeft') { ev.preventDefault(); seek(Math.max(0, s.playbackTime - 2)) }
      if (ev.key === 'ArrowRight') { ev.preventDefault(); seek(Math.min(s.project?.duration || 9999, s.playbackTime + 2)) }

      // Home = start, End = end
      if (ev.key === 'Home') { ev.preventDefault(); seek(0) }
      if (ev.key === 'End' && s.project) { ev.preventDefault(); seek(s.project.duration || 0) }

      // Escape = stop
      if (ev.key === 'Escape') { stop() }

      // Alt+A/B/C = loop
      if (ev.altKey && ev.key.toLowerCase() === 'a') { ev.preventDefault(); s.setLoopA() }
      if (ev.altKey && ev.key.toLowerCase() === 'b') { ev.preventDefault(); s.setLoopB() }
      if (ev.altKey && ev.key.toLowerCase() === 'c') { ev.preventDefault(); s.clearLoop() }
    }

    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [togglePlay, stop, seek])
}
