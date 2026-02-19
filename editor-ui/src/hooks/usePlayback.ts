import { useEffect, useRef, useCallback } from 'react'
import { useEditorStore } from '../stores/useEditorStore'

export function usePlayback() {
  const rafRef = useRef<number>(0)
  const startRef = useRef<number>(0)
  const videoRef = useRef<HTMLVideoElement>(null!)
  const audioRef = useRef<HTMLAudioElement>(null!)

  const playing = useEditorStore(s => s.playing)
  const playbackTime = useEditorStore(s => s.playbackTime)
  const project = useEditorStore(s => s.project)
  const loopA = useEditorStore(s => s.loopA)
  const loopB = useEditorStore(s => s.loopB)
  const setPlaybackTime = useEditorStore(s => s.setPlaybackTime)
  const setPlaying = useEditorStore(s => s.setPlaying)

  const seekMedia = useCallback((t: number) => {
    const vid = videoRef.current
    const au = audioRef.current
    if (vid?.src && vid.readyState >= 1) {
      const vc = project?.clips.find(c => c.track === 'video' || c.track === 'overlay')
      if (vc) {
        const off = Math.max(0, t - vc.start) * (vc.speed || 1) + (vc.in_point || 0)
        if (Math.abs(vid.currentTime - off) > 0.15) vid.currentTime = off
      }
    }
    if (au?.src && au.readyState >= 1) {
      const ac = project?.clips.find(c => c.track === 'audio')
      if (ac) {
        const off = Math.max(0, t - ac.start) * (ac.speed || 1) + (ac.in_point || 0)
        if (Math.abs(au.currentTime - off) > 0.15) au.currentTime = off
      }
    }
  }, [project])

  const play = useCallback(() => {
    const vid = videoRef.current
    const au = audioRef.current
    const hasAudioClip = project?.clips.some(c => c.track === 'audio')
    if (vid?.src) { vid.muted = !!hasAudioClip; vid.loop = true; vid.play().catch(() => {}) }
    if (au?.src) { au.play().catch(() => {}) }
  }, [project])

  const pause = useCallback(() => {
    videoRef.current?.pause()
    audioRef.current?.pause()
  }, [])

  const togglePlay = useCallback(() => {
    if (playing) {
      setPlaying(false)
      pause()
    } else {
      seekMedia(playbackTime)
      play()
      setPlaying(true)
    }
  }, [playing, playbackTime, seekMedia, play, pause, setPlaying])

  const seek = useCallback((t: number) => {
    setPlaybackTime(t)
    seekMedia(t)
  }, [setPlaybackTime, seekMedia])

  // Animation frame loop
  useEffect(() => {
    if (!playing) {
      cancelAnimationFrame(rafRef.current)
      return
    }
    const dur = project?.duration || 0
    startRef.current = performance.now() - playbackTime * 1000

    const tick = () => {
      if (!useEditorStore.getState().playing) return
      let t = (performance.now() - startRef.current) / 1000
      const state = useEditorStore.getState()

      // A/B loop
      if (state.loopA !== null && state.loopB !== null && state.loopA < state.loopB) {
        if (t >= state.loopB) {
          t = state.loopA
          startRef.current = performance.now() - state.loopA * 1000
          seekMedia(state.loopA)
        }
      }
      // Loop at project end
      if (dur > 0 && t >= dur) {
        t = 0
        startRef.current = performance.now()
        seekMedia(0)
      }
      setPlaybackTime(t)
      rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [playing]) // eslint-disable-line

  return { videoRef, audioRef, togglePlay, seek, seekMedia, play, pause }
}
