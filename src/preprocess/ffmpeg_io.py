"""FFmpeg I/O helpers for audio conversion, probing, and processing."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.utils.logging import debug, error

SUPPORTED_FORMATS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}


def probe_audio(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return json.loads(r.stdout)
    except Exception as e:
        error(f"ffprobe failed for {path}: {e}")
        return {}


def get_duration(path: Path) -> float:
    info = probe_audio(path)
    try:
        return float(info["format"]["duration"])
    except (KeyError, ValueError):
        return 0.0


def convert_to_wav(input_path: Path, output_path: Path | None = None,
                   sample_rate: int = 16000, mono: bool = True) -> Path:
    if output_path is None:
        output_path = input_path.with_suffix(".wav")
    channels = "1" if mono else "2"
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-ar", str(sample_rate), "-ac", channels,
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    debug(f"Converting: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {r.stderr}")
    return output_path


def apply_loudnorm(input_path: Path, output_path: Path, target_lufs: float = -16.0) -> Path:
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(output_path),
    ]
    debug(f"Normalizing: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"Loudness normalization failed: {r.stderr}")
    return output_path


def is_supported_audio(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_FORMATS


def find_audio_files(directory: Path, recursive: bool = False) -> list[Path]:
    files = []
    pattern = "**/*" if recursive else "*"
    for p in directory.glob(pattern):
        if p.is_file() and is_supported_audio(p):
            files.append(p)
    return sorted(files)
