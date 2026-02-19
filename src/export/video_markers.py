"""Video editor marker export — DaVinci Resolve, Premiere Pro, EDL.

Generates marker/chapter files that can be imported into video editors
to mark segment positions, song sections, or review points.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.transcription.base import TranscriptSegment
from src.utils.logging import info


def _tc(seconds: float, fps: float = 25.0) -> str:
    """Convert seconds to SMPTE timecode HH:MM:SS:FF."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    f = int((seconds % 1) * fps)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _hhmmssmmm(seconds: float) -> str:
    """HH:MM:SS.mmm format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


# ── DaVinci Resolve ───────────────────────────────────────────────────────────

def export_resolve_markers(
    segments: list[TranscriptSegment],
    output_path: Path,
    fps: float = 25.0,
    color: str = "Blue",
    include_text: bool = True,
) -> Path:
    """Export as DaVinci Resolve EDL markers.

    Can be imported via File > Import > Timeline Markers from EDL.
    """
    lines = ["TITLE: Karaoke Markers", ""]
    for i, seg in enumerate(segments):
        tc_in = _tc(seg.start, fps)
        tc_out = _tc(seg.end, fps)
        name = seg.text[:60].replace("|", " ") if include_text else f"Seg {i+1}"
        lines.append(f"{i+1:03d}  001  V  C        {tc_in} {tc_out} {tc_in} {tc_out}")
        lines.append(f"* FROM CLIP NAME: {name}")
        lines.append(f"|M:{name} |D:1 |C:{color}")
        lines.append("")

    path = output_path.with_suffix(".edl")
    path.write_text("\n".join(lines), encoding="utf-8")
    info(f"Resolve EDL: {path.name} ({len(segments)} markers)")
    return path


# ── Premiere Pro ──────────────────────────────────────────────────────────────

def export_premiere_markers(
    segments: list[TranscriptSegment],
    output_path: Path,
    fps: float = 25.0,
) -> Path:
    """Export as Premiere Pro CSV markers.

    Import via Marker panel > Import Markers.
    """
    lines = ["Marker Name\tDescription\tIn\tOut\tDuration\tMarker Type"]
    for i, seg in enumerate(segments):
        name = seg.text[:60].replace("\t", " ")
        tc_in = _tc(seg.start, fps)
        tc_out = _tc(seg.end, fps)
        dur = _tc(seg.end - seg.start, fps)
        lines.append(f"{name}\tSegment {i+1}\t{tc_in}\t{tc_out}\t{dur}\tComment")

    path = output_path.with_suffix(".csv")
    path.write_text("\n".join(lines), encoding="utf-8")
    info(f"Premiere CSV: {path.name} ({len(segments)} markers)")
    return path


# ── YouTube Chapters ──────────────────────────────────────────────────────────

def export_youtube_chapters(
    sections: list[dict],
    output_path: Path,
) -> Path:
    """Export song structure as YouTube chapter timestamps.

    Args:
        sections: List of {"label": str, "start_time": float} dicts
    """
    lines = []
    for sec in sections:
        t = sec["start_time"]
        m = int(t // 60)
        s = int(t % 60)
        lines.append(f"{m}:{s:02d} {sec['label']}")

    # YouTube requires first chapter at 0:00
    if lines and not lines[0].startswith("0:00"):
        lines.insert(0, "0:00 Intro")

    path = output_path.with_suffix(".chapters.txt")
    path.write_text("\n".join(lines), encoding="utf-8")
    info(f"YouTube chapters: {path.name} ({len(lines)} chapters)")
    return path


# ── Generic JSON markers ─────────────────────────────────────────────────────

def export_json_markers(
    segments: list[TranscriptSegment],
    output_path: Path,
    include_words: bool = False,
) -> Path:
    """Export as generic JSON markers (for custom integrations)."""
    markers = []
    for i, seg in enumerate(segments):
        m = {
            "index": i,
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "duration": round(seg.end - seg.start, 3),
            "text": seg.text,
            "confidence": round(seg.confidence, 3),
        }
        if include_words and seg.words:
            m["words"] = [
                {"word": w.word, "start": round(w.start, 3),
                 "end": round(w.end, 3), "confidence": round(w.confidence, 3)}
                for w in seg.words
            ]
        markers.append(m)

    path = output_path.with_suffix(".markers.json")
    path.write_text(json.dumps({"markers": markers}, indent=2, ensure_ascii=False),
                     encoding="utf-8")
    info(f"JSON markers: {path.name} ({len(markers)} markers)")
    return path


# ── FFMPEG Chapter Metadata ──────────────────────────────────────────────────

def export_ffmpeg_chapters(
    sections: list[dict],
    output_path: Path,
) -> Path:
    """Export as FFMPEG metadata chapters.

    Use with: ffmpeg -i input.mp4 -i chapters.txt -map_metadata 1 -codec copy output.mp4
    """
    lines = [";FFMETADATA1"]
    for sec in sections:
        start_ms = int(sec["start_time"] * 1000)
        end_ms = int(sec["end_time"] * 1000)
        lines.extend([
            "", "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start_ms}",
            f"END={end_ms}",
            f"title={sec['label']}",
        ])

    path = output_path.with_suffix(".ffmeta")
    path.write_text("\n".join(lines), encoding="utf-8")
    info(f"FFMPEG chapters: {path.name} ({len(sections)} chapters)")
    return path
