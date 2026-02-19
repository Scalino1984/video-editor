"""Lyrics Template System — parse lyrics files as source of truth for text layout.

Three modes:
1. lyrics_source_of_truth (default) — text+layout 100% from lyrics, timing from ASR
2. layout_only_reflow — lyrics control line breaks only, words may differ
3. hybrid_mark_differences — keep lyrics text, mark ASR differences for review

Supports: .txt (plain), .lrc (timestamped lyrics)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, debug


class LyricsMode(str, Enum):
    line_per_event = "line_per_event"        # 1 lyrics line = 1 subtitle event
    merge_by_empty_lines = "merge_by_empty_lines"  # group by stanzas


class TemplateMode(str, Enum):
    source_of_truth = "lyrics_source_of_truth"
    layout_only = "layout_only_reflow"
    hybrid = "hybrid_mark_differences"


class MatchMode(str, Enum):
    strict = "strict"
    lenient = "lenient"


@dataclass
class LyricsLine:
    """Single parsed lyrics line."""
    index: int                      # 0-based line number in original file
    text: str                       # exact text (preserved)
    is_empty: bool = False          # empty line (stanza separator)
    is_section: bool = False        # section marker like [Verse 1]
    section_label: str = ""         # e.g. "Verse 1", "Hook"
    lrc_time: float | None = None   # timestamp from LRC file (seconds)


@dataclass
class ParsedLyrics:
    """Result of parsing a lyrics file."""
    lines: list[LyricsLine]
    target_lines: list[str]         # non-empty, non-section lines (actual lyrics)
    sections: list[str]             # detected section labels
    total_lines: int                # including empty/section lines
    source_file: str
    format: str                     # "txt" or "lrc"
    has_timestamps: bool = False    # LRC with timestamps

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "format": self.format,
            "total_lines": self.total_lines,
            "target_lines_count": len(self.target_lines),
            "sections": self.sections,
            "has_timestamps": self.has_timestamps,
            "lines": [
                {
                    "index": l.index,
                    "text": l.text,
                    "is_empty": l.is_empty,
                    "is_section": l.is_section,
                    "section_label": l.section_label,
                    "lrc_time": l.lrc_time,
                }
                for l in self.lines
            ],
        }


# ── Section marker patterns ──────────────────────────────────────────────────

_SECTION_PATTERNS = [
    re.compile(r"^\[(.*?)\]$"),                    # [Verse 1], [Hook], [Outro]
    re.compile(r"^\((.*?)\)$"),                    # (Intro), (Bridge)
    re.compile(r"^(?:verse|hook|chorus|bridge|intro|outro|refrain|pre-chorus|interlude|breakdown|drop)\s*\d*\s*[:：]?\s*$", re.I),
]


def _is_section_marker(line: str) -> tuple[bool, str]:
    """Check if a line is a section marker. Returns (is_section, label)."""
    stripped = line.strip()
    for pat in _SECTION_PATTERNS:
        m = pat.match(stripped)
        if m:
            label = m.group(1) if m.lastindex else stripped
            return True, label.strip()
    return False, ""


# ── LRC timestamp parsing ────────────────────────────────────────────────────

_LRC_TIME_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
_LRC_META_RE = re.compile(r"^\[(ti|ar|al|by|offset|length|re|ve):(.+)\]$", re.I)


def _parse_lrc_time(tag: str) -> float | None:
    """Parse LRC time tag like [02:30.45] to seconds."""
    m = _LRC_TIME_RE.match(tag)
    if not m:
        return None
    mins = int(m.group(1))
    secs = int(m.group(2))
    ms_str = m.group(3) or "0"
    ms = int(ms_str.ljust(3, "0")[:3])
    return mins * 60 + secs + ms / 1000


# ── Main parser ──────────────────────────────────────────────────────────────

def parse_lyrics(
    lyrics_path: Path,
    preserve_empty_lines: bool = False,
    strip_section_markers: bool = True,
) -> ParsedLyrics:
    """Parse a lyrics file (.txt or .lrc) into structured lines.

    Args:
        lyrics_path: Path to lyrics file
        preserve_empty_lines: Include empty lines as stanza separators
        strip_section_markers: Remove [Verse 1] etc. from target_lines

    Returns:
        ParsedLyrics with all lines + filtered target_lines
    """
    text = lyrics_path.read_text(encoding="utf-8-sig").strip()
    is_lrc = lyrics_path.suffix.lower() == ".lrc"
    fmt = "lrc" if is_lrc else "txt"

    all_lines: list[LyricsLine] = []
    sections: list[str] = []
    has_timestamps = False

    for i, raw_line in enumerate(text.split("\n")):
        line = raw_line.rstrip()

        # Handle LRC metadata lines
        if is_lrc and _LRC_META_RE.match(line):
            continue

        # Parse LRC timestamps
        lrc_time = None
        if is_lrc:
            # Extract all time tags (some lines have multiple: [01:30][02:45]text)
            time_matches = list(_LRC_TIME_RE.finditer(line))
            if time_matches:
                lrc_time = _parse_lrc_time(time_matches[0].group())
                has_timestamps = True
                # Strip time tags from text
                line = _LRC_TIME_RE.sub("", line).strip()

        # Empty line
        if not line.strip():
            all_lines.append(LyricsLine(index=i, text="", is_empty=True))
            continue

        # Section marker check
        is_sec, label = _is_section_marker(line.strip())
        if is_sec:
            sections.append(label)
            all_lines.append(LyricsLine(
                index=i, text=line.strip(), is_section=True,
                section_label=label, lrc_time=lrc_time,
            ))
            continue

        # Normal lyrics line
        all_lines.append(LyricsLine(
            index=i, text=line.strip(), lrc_time=lrc_time,
        ))

    # Build target_lines (the actual lyrics text for alignment)
    target_lines = []
    for ll in all_lines:
        if ll.is_section and strip_section_markers:
            continue
        if ll.is_empty:
            if preserve_empty_lines:
                target_lines.append("")
            continue
        target_lines.append(ll.text)

    result = ParsedLyrics(
        lines=all_lines,
        target_lines=target_lines,
        sections=sections,
        total_lines=len(all_lines),
        source_file=lyrics_path.name,
        format=fmt,
        has_timestamps=has_timestamps,
    )

    info(f"Lyrics parsed: {len(target_lines)} lines, {len(sections)} sections, "
         f"format={fmt}, timestamps={'yes' if has_timestamps else 'no'}")
    return result


def group_by_stanzas(parsed: ParsedLyrics) -> list[list[str]]:
    """Group target_lines into stanzas (separated by empty lines in source)."""
    stanzas: list[list[str]] = []
    current: list[str] = []

    for ll in parsed.lines:
        if ll.is_section:
            continue
        if ll.is_empty:
            if current:
                stanzas.append(current)
                current = []
            continue
        current.append(ll.text)

    if current:
        stanzas.append(current)
    return stanzas


def get_lrc_timings(parsed: ParsedLyrics) -> list[tuple[float, str]]:
    """Extract (time_sec, text) pairs from LRC-parsed lyrics."""
    result = []
    for ll in parsed.lines:
        if ll.lrc_time is not None and not ll.is_empty and not ll.is_section:
            result.append((ll.lrc_time, ll.text))
    return result
