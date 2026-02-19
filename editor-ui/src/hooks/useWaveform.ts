import { useRef, useCallback } from 'react'
import * as api from '../api/editor'
import { useEditorStore } from '../stores/useEditorStore'

const waveformCache: Record<string, number[]> = {}

export function useWaveform() {
  const decodingRef = useRef<Set<string>>(new Set())

  const drawWaveform = useCallback(async (canvas: HTMLCanvasElement, assetId: string) => {
    const pid = useEditorStore.getState().pid
    if (!pid || !canvas) return

    // Immediate fallback
    drawFallback(canvas)

    // Use cache
    if (waveformCache[assetId]) {
      renderPeaks(canvas, waveformCache[assetId])
      return
    }

    // Avoid duplicate decoding
    if (decodingRef.current.has(assetId)) return
    decodingRef.current.add(assetId)

    try {
      const url = api.assetFileUrl(pid, assetId)
      const resp = await fetch(url)
      if (!resp.ok) throw new Error('HTTP ' + resp.status)
      const buf = await resp.arrayBuffer()
      if (buf.byteLength < 100) throw new Error('Too small')

      const actx = new AudioContext()
      const decoded = await actx.decodeAudioData(buf)
      const raw = decoded.getChannelData(0)

      // Downsample to ~200 points
      const pts = 200
      const step = Math.floor(raw.length / pts) || 1
      const peaks: number[] = []
      for (let i = 0; i < pts; i++) {
        let max = 0
        const off = i * step
        for (let j = 0; j < step && off + j < raw.length; j++) {
          const v = Math.abs(raw[off + j])
          if (v > max) max = v
        }
        peaks.push(max)
      }

      waveformCache[assetId] = peaks
      renderPeaks(canvas, peaks)
      actx.close()
    } catch {
      // Keep fallback
    } finally {
      decodingRef.current.delete(assetId)
    }
  }, [])

  return { drawWaveform }
}

function drawFallback(canvas: HTMLCanvasElement) {
  const pts = 60
  const peaks: number[] = []
  for (let i = 0; i < pts; i++) peaks.push(0.15 + Math.random() * 0.55)
  renderPeaks(canvas, peaks)
}

function renderPeaks(canvas: HTMLCanvasElement, peaks: number[]) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const w = canvas.width, h = canvas.height
  ctx.clearRect(0, 0, w, h)
  const barW = w / peaks.length
  ctx.fillStyle = 'rgba(255,255,255,.7)'
  for (let i = 0; i < peaks.length; i++) {
    const barH = Math.max(1, peaks[i] * h * 0.85)
    const x = i * barW
    const y = (h - barH) / 2
    ctx.fillRect(x, y, Math.max(1, barW - 0.5), barH)
  }
}
