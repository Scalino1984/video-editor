"""Vocal isolation via Demucs (optional dependency)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.utils.logging import info, warn, error


def isolate_vocals(input_path: Path, output_dir: Path | None = None,
                   model: str = "htdemucs", device: str = "cpu") -> Path | None:
    try:
        import demucs  # noqa: F401
    except ImportError:
        warn("demucs not installed — skipping vocal isolation")
        warn("Install with: pip install demucs torch")
        return None

    if output_dir is None:
        output_dir = input_path.parent / "separated"
    output_dir.mkdir(parents=True, exist_ok=True)

    info(f"Isolating vocals with {model} on {device}...")

    cmd = [
        "python", "-m", "demucs",
        "--two-stems", "vocals",
        "-n", model,
        "-d", device,
        "-o", str(output_dir),
        str(input_path),
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            error(f"Demucs failed: {r.stderr}")
            return None
    except subprocess.TimeoutExpired:
        error("Demucs timed out (>10min)")
        return None
    except FileNotFoundError:
        warn("demucs command not found in PATH")
        return None

    vocals_path = output_dir / model / input_path.stem / "vocals.wav"
    if vocals_path.exists():
        info(f"Vocals isolated: {vocals_path}")
        return vocals_path

    warn(f"Expected vocals file not found at {vocals_path}")
    return None
