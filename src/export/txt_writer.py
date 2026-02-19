"""Plain text exporter — just the text, no timestamps."""

from __future__ import annotations

from pathlib import Path

from src.transcription.base import TranscriptSegment


def write_txt(segments: list[TranscriptSegment], output_path: Path,
              separator: str = "\n") -> Path:
    text = separator.join(seg.text for seg in segments if seg.text.strip())
    output_path.write_text(text + "\n", encoding="utf-8")
    return output_path


def write_txt_with_timestamps(segments: list[TranscriptSegment], output_path: Path) -> Path:
    """Write text with simple timestamps like [00:01] Hello world."""
    lines = []
    for seg in segments:
        m = int(seg.start // 60)
        s = int(seg.start % 60)
        lines.append(f"[{m:02d}:{s:02d}] {seg.text}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
