"""SRT subtitle file writer and parser."""

from __future__ import annotations

from pathlib import Path

from src.transcription.base import TranscriptSegment


def format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    ms = int((s - int(s)) * 1000)
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


def write_srt(segments: list[TranscriptSegment], output_path: Path) -> Path:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}")
        lines.append(seg.text)
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def parse_srt_time(time_str: str) -> float:
    time_str = time_str.strip()
    parts = time_str.replace(",", ".").split(":")
    h, m = int(parts[0]), int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


def read_srt(path: Path) -> list[TranscriptSegment]:
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    blocks = content.strip().split("\n\n")
    segments: list[TranscriptSegment] = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        # skip index line
        time_line = lines[1]
        if " --> " not in time_line:
            continue

        start_str, end_str = time_line.split(" --> ")
        start = parse_srt_time(start_str)
        end = parse_srt_time(end_str)
        text = "\n".join(lines[2:])

        segments.append(TranscriptSegment(start=start, end=end, text=text))

    return segments
