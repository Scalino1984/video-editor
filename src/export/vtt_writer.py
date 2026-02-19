"""WebVTT subtitle writer and parser."""

from __future__ import annotations

from pathlib import Path

from src.transcription.base import TranscriptSegment


def format_vtt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    ms = int((s - int(s)) * 1000)
    return f"{h:02d}:{m:02d}:{int(s):02d}.{ms:03d}"


def write_vtt(segments: list[TranscriptSegment], output_path: Path) -> Path:
    lines = ["WEBVTT", ""]
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{format_vtt_time(seg.start)} --> {format_vtt_time(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def read_vtt(path: Path) -> list[TranscriptSegment]:
    content = path.read_text(encoding="utf-8")
    blocks = content.strip().split("\n\n")
    segments: list[TranscriptSegment] = []
    for block in blocks:
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            if " --> " in line:
                parts = line.split(" --> ")
                start = _parse_vtt_time(parts[0].strip())
                end = _parse_vtt_time(parts[1].strip().split(" ")[0])
                text = "\n".join(lines[i + 1:])
                if text:
                    segments.append(TranscriptSegment(start=start, end=end, text=text))
                break
    return segments


def _parse_vtt_time(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])
