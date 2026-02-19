import { useEffect } from 'react'
import { useEditorStore } from '../stores/useEditorStore'

export function useKeyboardShortcuts(togglePlay: () => void) {
  useEffect(() => {
    const handle = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      const { pid, undoAction, redoAction, deleteSelectedClip, splitAtPlayhead,
        saveProject, setLoopA, setLoopB, clearLoop } = useEditorStore.getState()

      if (!pid) return

      // Space = play/pause
      if (ev.code === 'Space') { ev.preventDefault(); togglePlay() }

      // Ctrl+Z / Ctrl+Y
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 'z') { ev.preventDefault(); undoAction() }
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 'y') { ev.preventDefault(); redoAction() }
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 's') { ev.preventDefault(); saveProject() }

      // Delete
      if (ev.key === 'Delete' || ev.key === 'Backspace') { deleteSelectedClip() }

      // S = split
      if (ev.key === 's' && !ev.ctrlKey && !ev.metaKey) { splitAtPlayhead() }

      // Alt+A/B/C = loop
      if (ev.altKey && ev.key.toLowerCase() === 'a') { ev.preventDefault(); setLoopA() }
      if (ev.altKey && ev.key.toLowerCase() === 'b') { ev.preventDefault(); setLoopB() }
      if (ev.altKey && ev.key.toLowerCase() === 'c') { ev.preventDefault(); clearLoop() }

      // Arrow keys = scrub ±1s
      if (ev.key === 'ArrowLeft') {
        ev.preventDefault()
        const t = Math.max(0, useEditorStore.getState().playbackTime - 1)
        useEditorStore.getState().setPlaybackTime(t)
      }
      if (ev.key === 'ArrowRight') {
        ev.preventDefault()
        const t = useEditorStore.getState().playbackTime + 1
        useEditorStore.getState().setPlaybackTime(t)
      }
    }

    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [togglePlay])
}
