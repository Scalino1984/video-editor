"""LRC (Lyrics) subtitle writer — compatible with media players, karaoke apps."""

from __future__ import annotations

from pathlib import Path

from src.transcription.base import TranscriptSegment


def format_lrc_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{m:02d}:{int(s):02d}.{cs:02d}"


def write_lrc(segments: list[TranscriptSegment], output_path: Path,
              title: str = "", artist: str = "", album: str = "") -> Path:
    """Write standard LRC with optional enhanced word-level tags."""
    lines = []
    if title:
        lines.append(f"[ti:{title}]")
    if artist:
        lines.append(f"[ar:{artist}]")
    if album:
        lines.append(f"[al:{album}]")
    lines.append("[by:karaoke-sub-tool]")
    lines.append("")

    for seg in segments:
        ts = format_lrc_time(seg.start)
        if seg.has_word_timestamps and seg.words:
            # enhanced LRC with word timestamps
            word_parts = []
            for w in seg.words:
                wts = format_lrc_time(w.start)
                word_parts.append(f"<{wts}>{w.word}")
            lines.append(f"[{ts}]{' '.join(word_parts)}")
        else:
            lines.append(f"[{ts}]{seg.text}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def write_simple_lrc(segments: list[TranscriptSegment], output_path: Path) -> Path:
    """Write simple LRC without word-level tags."""
    lines = []
    for seg in segments:
        ts = format_lrc_time(seg.start)
        lines.append(f"[{ts}]{seg.text}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
