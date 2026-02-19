"""Audio loudness normalization via ffmpeg loudnorm or RMS."""

from __future__ import annotations

from pathlib import Path

from src.preprocess.ffmpeg_io import apply_loudnorm
from src.utils.logging import debug, info


def normalize_audio(input_path: Path, output_path: Path | None = None,
                    target_lufs: float = -16.0) -> Path:
    if output_path is None:
        output_path = input_path.with_stem(input_path.stem + "_norm")
        if output_path.suffix != ".wav":
            output_path = output_path.with_suffix(".wav")
    info(f"Normalizing audio to {target_lufs} LUFS")
    return apply_loudnorm(input_path, output_path, target_lufs)
