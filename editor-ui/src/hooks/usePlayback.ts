import { useEffect, useRef, useCallback } from 'react'
import { useEditorStore } from '../stores/useEditorStore'
import * as api from '../api/editor'

export function usePlayback() {
  const rafRef = useRef<number>(0)
  const startRef = useRef<number>(0)
  const videoRef = useRef<HTMLVideoElement>(null!)
  const audioRef = useRef<HTMLAudioElement>(null!)

  const playing = useEditorStore(s => s.playing)
  const playbackTime = useEditorStore(s => s.playbackTime)
  const project = useEditorStore(s => s.project)
  const playSpeed = useEditorStore(s => s.playSpeed)
  const setPlaybackTime = useEditorStore(s => s.setPlaybackTime)
  const setPlaying = useEditorStore(s => s.setPlaying)

  // ── Sync playback rate on speed change ──
  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = playSpeed
    if (audioRef.current) audioRef.current.playbackRate = playSpeed
  }, [playSpeed])

  const seekMedia = useCallback((t: number) => {
    const vid = videoRef.current
    const au = audioRef.current
    const proj = useEditorStore.getState().project
    if (vid?.src && vid.readyState >= 1) {
      const vc = proj?.clips.find(c => c.track === 'video' || c.track === 'overlay')
      if (vc) {
        const off = Math.max(0, t - vc.start) * (vc.speed || 1) + (vc.in_point || 0)
        if (Math.abs(vid.currentTime - off) > 0.15) vid.currentTime = off
      }
    }
    if (au?.src && au.readyState >= 1) {
      const ac = proj?.clips.find(c => c.track === 'audio')
      if (ac) {
        const off = Math.max(0, t - ac.start) * (ac.speed || 1) + (ac.in_point || 0)
        if (Math.abs(au.currentTime - off) > 0.15) au.currentTime = off
      }
    }
  }, [])

  const syncMediaSources = useCallback(() => {
    const vid = videoRef.current
    const au = audioRef.current
    const state = useEditorStore.getState()
    const proj = state.project
    const pid = state.pid
    if (!proj || !pid) return

    const vc = proj.clips.find(c => c.track === 'video' || c.track === 'overlay')
    const ac = proj.clips.find(c => c.track === 'audio')

    const base = api.apiBase()
    if (vid && vc) {
      const url = `${base}/api/editor/projects/${pid}/assets/${vc.asset_id}/file`
      if (vid.dataset.curSrc !== url) {
        vid.src = url; vid.dataset.curSrc = url; vid.loop = true; vid.load()
      }
      vid.muted = !!ac
    }
    if (au && ac) {
      const url = `${base}/api/editor/projects/${pid}/assets/${ac.asset_id}/file`
      if (au.dataset.curSrc !== url) {
        au.src = url; au.dataset.curSrc = url; au.load()
      }
    }
  }, [])

  const play = useCallback(() => {
    const vid = videoRef.current
    const au = audioRef.current
    const spd = useEditorStore.getState().playSpeed
    if (vid?.src) { vid.playbackRate = spd; vid.play().catch(() => {}) }
    if (au?.src) { au.playbackRate = spd; au.play().catch(() => {}) }
  }, [])

  const pause = useCallback(() => {
    videoRef.current?.pause()
    audioRef.current?.pause()
  }, [])

  const togglePlay = useCallback(() => {
    if (useEditorStore.getState().playing) {
      setPlaying(false)
      pause()
    } else {
      syncMediaSources()
      seekMedia(useEditorStore.getState().playbackTime)
      play()
      setPlaying(true)
    }
  }, [syncMediaSources, seekMedia, play, pause, setPlaying])

  const seek = useCallback((t: number) => {
    setPlaybackTime(t)
    seekMedia(t)
  }, [setPlaybackTime, seekMedia])

  const stop = useCallback(() => {
    setPlaying(false)
    pause()
    setPlaybackTime(0)
    seekMedia(0)
  }, [setPlaying, pause, setPlaybackTime, seekMedia])

  // ── Animation frame loop ──
  useEffect(() => {
    if (!playing) {
      cancelAnimationFrame(rafRef.current)
      return
    }
    const dur = useEditorStore.getState().project?.duration || 0
    const spd = useEditorStore.getState().playSpeed
    startRef.current = performance.now() - playbackTime * 1000 / spd

    const tick = () => {
      const state = useEditorStore.getState()
      if (!state.playing) return
      const spd = state.playSpeed
      let t = (performance.now() - startRef.current) / 1000 * spd

      // A/B loop
      if (state.loopA !== null && state.loopB !== null && state.loopA < state.loopB) {
        if (t >= state.loopB) {
          t = state.loopA
          startRef.current = performance.now() - state.loopA * 1000 / spd
          seekMedia(state.loopA)
        }
      }
      // Loop at project end
      const d = state.project?.duration || 0
      if (d > 0 && t >= d) {
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

  return { videoRef, audioRef, togglePlay, seek, seekMedia, play, pause, stop, syncMediaSources }
}
