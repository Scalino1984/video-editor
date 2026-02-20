"""Configuration management with YAML support and pydantic models."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class VADConfig(BaseModel):
    enabled: bool = True
    aggressiveness: int = Field(default=2, ge=0, le=3)
    min_speech_ms: int = 300
    min_silence_ms: int = 500


class NormalizeConfig(BaseModel):
    enabled: bool = True
    target_lufs: float = -16.0


class VocalIsolationConfig(BaseModel):
    enabled: bool = False
    model: str = "htdemucs"
    device: str = "cpu"
    cpu_threads: int = 0  # 0 = auto (half of CPU cores, max 6). Limits torch/OMP in demucs subprocess


class PreprocessConfig(BaseModel):
    vad: VADConfig = VADConfig()
    normalize: NormalizeConfig = NormalizeConfig()
    vocal_isolation: VocalIsolationConfig = VocalIsolationConfig()


class TranscriptionConfig(BaseModel):
    backend: str = "voxtral"
    language: str = "auto"
    word_timestamps: str = "auto"
    model: str = "voxtral-mini-latest"
    diarize: bool = True


class WhisperXConfig(BaseModel):
    model_size: str = "large-v3"
    compute_type: str = "float16"
    batch_size: int = 16
    device: str = "auto"
    cpu_threads: int = 0  # 0 = auto (half of CPU cores), limits torch/OMP/MKL threads


class RefinementConfig(BaseModel):
    cps: float = 18.0
    min_duration: float = 1.0
    max_duration: float = 6.0
    max_chars_per_line: int = 42
    max_lines: int = 2
    min_gap_ms: int = 80
    auto_punctuation: bool = False
    dictionary_path: str = ""


class BeatGridConfig(BaseModel):
    enabled: bool = False
    bpm: float | str = "detect"
    time_signature: str = "4/4"
    beat_offset_ms: float = 0.0
    snap_tolerance_ms: float = 80.0
    snap_strength: float = 0.5


class KaraokeConfig(BaseModel):
    mode: str = "kf"
    approx_karaoke: bool = True
    highlight_color: str = "&H00FFFF00"
    fade_in_ms: int = 150
    fade_out_ms: int = 100


class ThemeConfig(BaseModel):
    preset: str = "classic"
    safe_area: str = ""
    playresx: int = 0
    playresy: int = 0
    font: str = ""
    fontsize: int = 0
    primary_color: str = ""
    outline_color: str = ""
    outline: float = 0
    shadow: float = 0
    alignment: int = 0
    margins: str = ""


class PreviewConfig(BaseModel):
    duration: str = "15s"
    start: str = "60s"
    resolution: str = "1920x1080"
    background: str = "#000000"
    bg_image: str = ""
    ab_compare: bool = False


class CacheConfig(BaseModel):
    enabled: bool = True
    skip_existing: bool = True
    force: bool = False
    id_method: str = "hash"


class RenderingConfig(BaseModel):
    ffmpeg_threads: int = 0  # 0 = auto (half of CPU cores, min 2). Env: FFMPEG_THREADS
    x264_threads: int = 0    # 0 = same as ffmpeg_threads. Limits libx264 encoder threads
    nice: int = 10           # Process priority (Linux, 0-19). Env: MEDIA_NICE
    max_concurrent: int = 1  # Max parallel heavy media jobs. Env: MAX_MEDIA_JOBS


class ConfidenceConfig(BaseModel):
    low_threshold: float = 0.6
    mark_in_ass: bool = True
    uncertain_style: str = "UncertainKaraoke"
    report_format: str = "json"


class AppConfig(BaseModel):
    preprocess: PreprocessConfig = PreprocessConfig()
    transcription: TranscriptionConfig = TranscriptionConfig()
    whisperx: WhisperXConfig = WhisperXConfig()
    refinement: RefinementConfig = RefinementConfig()
    beat_grid: BeatGridConfig = BeatGridConfig()
    karaoke: KaraokeConfig = KaraokeConfig()
    theme: ThemeConfig = ThemeConfig()
    preview: PreviewConfig = PreviewConfig()
    cache: CacheConfig = CacheConfig()
    confidence: ConfidenceConfig = ConfidenceConfig()
    rendering: RenderingConfig = RenderingConfig()


def load_config(path: str | Path | None = None) -> AppConfig:
    if path is None:
        candidates = [Path("config.yaml"), Path("config.yml"), Path("karaoke.yaml")]
        for c in candidates:
            if c.exists():
                path = c
                break
    if path is not None:
        p = Path(path)
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
            return AppConfig(**data)
    return AppConfig()


def merge_cli_overrides(cfg: AppConfig, overrides: dict[str, Any]) -> AppConfig:
    data = cfg.model_dump()
    for key, val in overrides.items():
        if val is None:
            continue
        parts = key.split(".")
        d = data
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = val
    return AppConfig(**data)


DEFAULT_CONFIG_YAML = """\
# karaoke-sub-tool v3 configuration

preprocess:
  vad:
    enabled: true
    aggressiveness: 2
    min_speech_ms: 300
    min_silence_ms: 500
  normalize:
    enabled: true
    target_lufs: -16.0
  vocal_isolation:
    enabled: false
    model: htdemucs
    device: cpu
    cpu_threads: 0           # 0 = auto (half of cores, max 6). Env: DEMUCS_THREADS

transcription:
  backend: voxtral          # voxtral | openai_whisper | local_whisper | whisperx
  language: auto             # de | en | auto
  word_timestamps: auto      # on | auto | off
  model: "voxtral-mini-latest"
  diarize: true

whisperx:
  model_size: "large-v3"     # tiny | base | small | medium | large-v3
  compute_type: "float16"    # float16 | int8 | float32
  batch_size: 16
  device: "auto"             # auto | cpu | cuda
  cpu_threads: 0             # 0 = auto (half of cores, max 6). Env: WHISPERX_THREADS

refinement:
  cps: 18.0
  min_duration: 1.0
  max_duration: 6.0
  max_chars_per_line: 42
  max_lines: 2
  min_gap_ms: 80
  auto_punctuation: false
  dictionary_path: ""

beat_grid:
  enabled: false
  bpm: detect                # number or 'detect'
  time_signature: "4/4"
  beat_offset_ms: 0.0
  snap_tolerance_ms: 80.0
  snap_strength: 0.5

karaoke:
  mode: kf                   # k | kf | ko
  approx_karaoke: true
  highlight_color: "&H00FFFF00"

theme:
  preset: classic            # classic|neon|high_contrast|landscape_1080p|portrait_1080x1920|mobile_safe
  safe_area: ""              # "top,bottom,left,right" in px

preview:
  duration: "15s"
  start: "60s"
  resolution: "1920x1080"
  background: "#000000"

cache:
  enabled: true
  skip_existing: true
  force: false
  id_method: hash            # hash | mtime

confidence:
  low_threshold: 0.6
  mark_in_ass: true
  report_format: json        # json | csv

rendering:
  ffmpeg_threads: 0          # 0 = auto (half of cores, min 2). Env override: FFMPEG_THREADS
  x264_threads: 0            # 0 = same as ffmpeg_threads. Limits libx264 encoder threads
  nice: 10                   # Process priority 0-19 (Linux only). Env: MEDIA_NICE
  max_concurrent: 1          # Max parallel heavy media jobs. Env: MAX_MEDIA_JOBS
"""
