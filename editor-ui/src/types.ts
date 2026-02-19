// ── Editor Types ──

export interface Effect {
  type: string
  value: number
  params?: Record<string, unknown>
}

export interface Clip {
  id: string
  asset_id: string
  track: 'video' | 'audio' | 'subtitle' | 'overlay'
  start: number
  duration: number
  end: number
  in_point: number
  out_point: number
  volume: number
  speed: number
  loop: boolean
  effects: Effect[]
  z_index: number
  sub_style: string
  sub_position: string
}

export interface Asset {
  id: string
  filename: string
  path: string
  type: 'video' | 'audio' | 'image' | 'subtitle'
  duration: number
  width: number
  height: number
  fps: number
  has_audio: boolean
  thumbnail: string
}

export interface Project {
  id: string
  name: string
  width: number
  height: number
  fps: number
  duration: number
  assets: Record<string, Asset>
  clips: Clip[]
  preset: string
  crf: number
  audio_bitrate: string
  sub_font: string
  sub_size: number
  sub_color: string
  sub_outline_color: string
  sub_outline_width: number
  sub_position: string
  sub_margin_v: number
  sub_y_percent: number
  sub_lines: number
  sub_bg_enabled: boolean
  sub_bg_color: string
}

export interface SubtitleCue {
  start: number
  end: number
  text: string
}

export interface RenderResult {
  file: string
  download_url: string
  size_mb: number
}

export interface SavedProject {
  filename: string
  size: number
  modified: string
}

export interface JobItem {
  id?: string
  job_id?: string
  title?: string
  source_filename?: string
  duration_sec?: number
  segments_count?: number
  backend?: string
}

export type Theme = 'default' | 'neon' | 'light' | 'warm'
export type PropTab = 'clip' | 'effects' | 'project' | 'ai'

export const TRACK_COLORS: Record<string, string> = {
  video: '#a855f7',
  audio: '#00b8ff',
  subtitle: '#ffaa22',
  overlay: '#7a7f94',
}

export const TRACK_ORDER = ['video', 'audio', 'subtitle', 'overlay'] as const

export const EFFECTS_LIST = [
  { type: 'fade_in', label: '🌅 Fade In', value: 1 },
  { type: 'fade_out', label: '🌇 Fade Out', value: 1 },
  { type: 'brightness', label: '☀️ Helligkeit', value: 0 },
  { type: 'contrast', label: '🔲 Kontrast', value: 1 },
  { type: 'saturation', label: '🎨 Sättigung', value: 1 },
  { type: 'blur', label: '🔵 Blur', value: 0 },
  { type: 'grayscale', label: '⬛ Graustufen', value: 1 },
  { type: 'sepia', label: '🟤 Sepia', value: 1 },
  { type: 'hflip', label: '↔️ H-Flip', value: 1 },
  { type: 'vflip', label: '↕️ V-Flip', value: 1 },
  { type: 'rotate', label: '🔄 Rotation', value: 0 },
  { type: 'zoom', label: '🔍 Zoom', value: 1 },
  { type: 'vignette', label: '⭕ Vignette', value: 0.3 },
  { type: 'sharpen', label: '🔺 Schärfen', value: 1 },
  { type: 'speed', label: '⏩ Speed', value: 1 },
] as const
