import type { SubtitleCue } from '../types'

// ── Time Formatting ──
export function fmt(s: number): string {
  if (!s || s < 0) s = 0
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(1)
  return m + ':' + sec.padStart(4, '0')
}

export function fmtMs(s: number): string {
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(2)
  return m + ':' + sec.padStart(5, '0')
}

export function parseTimeStr(str: string): number {
  const parts = str.split(':')
  if (parts.length === 2) return parseFloat(parts[0]) * 60 + parseFloat(parts[1])
  if (parts.length === 3) return parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2])
  return parseFloat(str) || 0
}

// ── Color Conversion ──
export function hexToAss(hex: string): string {
  const r = hex.slice(1, 3), g = hex.slice(3, 5), b = hex.slice(5, 7)
  return '&H00' + b.toUpperCase() + g.toUpperCase() + r.toUpperCase()
}

export function hexToAssBg(hex: string, alpha: number): string {
  const r = hex.slice(1, 3), g = hex.slice(3, 5), b = hex.slice(5, 7)
  const a = Math.max(0, Math.min(255, Math.round(alpha)))
  return '&H' + a.toString(16).toUpperCase().padStart(2, '0') + b.toUpperCase() + g.toUpperCase() + r.toUpperCase()
}

export function assToHex(ass: string): string {
  if (!ass || ass.length < 10) return '#FFFFFF'
  const b = ass.slice(4, 6), g = ass.slice(6, 8), r = ass.slice(8, 10)
  return '#' + r + g + b
}

export function assAlpha(ass: string): number {
  if (!ass || ass.length < 10) return 128
  return parseInt(ass.slice(2, 4), 16)
}

// ── SRT/ASS Parsing ──
export function parseSRT(text: string): SubtitleCue[] {
  const cues: SubtitleCue[] = []
  const blocks = text.trim().split(/\n\s*\n/)
  for (const block of blocks) {
    const lines = block.trim().split('\n')
    if (lines.length < 2) continue
    const tsLine = lines.find(l => l.includes('-->'))
    if (!tsLine) continue
    const m = tsLine.match(/(\d{2}):(\d{2}):(\d{2})[,.](\d+)\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d+)/)
    if (!m) continue
    const start = +m[1] * 3600 + +m[2] * 60 + +m[3] + +m[4] / 1000
    const end = +m[5] * 3600 + +m[6] * 60 + +m[7] + +m[8] / 1000
    const idx = lines.indexOf(tsLine)
    const txt = lines.slice(idx + 1).join('\n').replace(/<[^>]+>/g, '').trim()
    if (txt) cues.push({ start, end, text: txt })
  }
  return cues
}

export function parseASS(text: string): SubtitleCue[] {
  const cues: SubtitleCue[] = []
  for (const line of text.split('\n')) {
    if (!line.startsWith('Dialogue:')) continue
    const parts = line.slice(10).split(',', 10)
    if (parts.length < 10) continue
    try {
      const parseT = (s: string) => {
        const p = s.trim().split(':')
        return +p[0] * 3600 + +p[1] * 60 + parseFloat(p[2])
      }
      const start = parseT(parts[1])
      const end = parseT(parts[2])
      const raw = parts[9]
      const txt = raw.replace(/\{[^}]*\}/g, '').replace(/\\N/g, '\n').replace(/\\n/g, '\n').trim()
      if (txt) cues.push({ start, end, text: txt })
    } catch { /* skip */ }
  }
  return cues
}
