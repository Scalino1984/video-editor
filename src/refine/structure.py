"""Song structure detection — auto-detect Verse, Chorus, Bridge, Hook, Outro.

Uses text repetition analysis, segment timing patterns, and gap detection
to identify song sections. Optimized for rap/hip-hop structure.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from src.transcription.base import TranscriptSegment
from src.utils.logging import info, debug


@dataclass
class SongSection:
    """A detected section of the song."""
    section_type: str       # "verse" | "chorus" | "bridge" | "hook" | "intro" | "outro" | "break"
    label: str              # "Verse 1", "Chorus", "Bridge"
    start_line: int
    end_line: int
    start_time: float
    end_time: float
    line_count: int
    is_repeat: bool = False  # True if this section repeats earlier content
    repeat_of: int | None = None  # index of the section this repeats
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {
            "type": self.section_type, "label": self.label,
            "start_line": self.start_line, "end_line": self.end_line,
            "start_time": round(self.start_time, 2),
            "end_time": round(self.end_time, 2),
            "line_count": self.line_count,
            "is_repeat": self.is_repeat,
            "repeat_of": self.repeat_of,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class SongStructure:
    """Full song structure analysis."""
    sections: list[SongSection]
    total_lines: int
    total_duration: float
    has_chorus: bool
    chorus_count: int
    verse_count: int
    structure_pattern: str   # e.g. "V1-C-V2-C-B-C"

    def to_dict(self) -> dict:
        return {
            "sections": [s.to_dict() for s in self.sections],
            "total_lines": self.total_lines,
            "total_duration": round(self.total_duration, 2),
            "has_chorus": self.has_chorus,
            "chorus_count": self.chorus_count,
            "verse_count": self.verse_count,
            "pattern": self.structure_pattern,
        }


def _norm(text: str) -> str:
    """Normalize for comparison."""
    t = text.lower().strip()
    t = re.sub(r"[^\w\s]", "", t)
    t = unicodedata.normalize("NFC", t)
    return " ".join(t.split())


def _block_similarity(lines_a: list[str], lines_b: list[str]) -> float:
    """Compare two blocks of text lines."""
    if not lines_a or not lines_b:
        return 0.0
    text_a = " ".join(_norm(l) for l in lines_a)
    text_b = " ".join(_norm(l) for l in lines_b)
    return SequenceMatcher(None, text_a, text_b).ratio()


def detect_song_structure(
    segments: list[TranscriptSegment],
    min_section_lines: int = 2,
    chorus_threshold: float = 0.7,
    gap_threshold: float = 3.0,
) -> SongStructure:
    """Detect song structure from transcribed segments.

    Strategy:
    1. Find natural breaks (large gaps in timing)
    2. Group segments into candidate sections
    3. Find repeated blocks → these are likely choruses
    4. Label remaining sections as verses, bridges, etc.
    5. Detect intro/outro by position and duration

    Args:
        segments: Transcribed segments
        min_section_lines: Minimum lines per section
        chorus_threshold: Similarity threshold for chorus detection
        gap_threshold: Gap in seconds that indicates section boundary
    """
    if not segments:
        return SongStructure([], 0, 0, False, 0, 0, "")

    lines = [s.text for s in segments]
    n = len(lines)
    total_dur = segments[-1].end if segments else 0

    # Step 1: Find section boundaries from timing gaps
    boundaries = [0]  # always start at 0
    for i in range(1, n):
        gap = segments[i].start - segments[i - 1].end
        if gap >= gap_threshold:
            boundaries.append(i)
    boundaries.append(n)  # end boundary

    # Ensure minimum section sizes — merge tiny sections
    merged_boundaries = [boundaries[0]]
    for i in range(1, len(boundaries)):
        if boundaries[i] - merged_boundaries[-1] >= min_section_lines:
            merged_boundaries.append(boundaries[i])
        elif i == len(boundaries) - 1:
            merged_boundaries.append(boundaries[i])
    boundaries = merged_boundaries

    # Step 2: Create candidate blocks
    blocks: list[tuple[int, int]] = []
    for i in range(len(boundaries) - 1):
        blocks.append((boundaries[i], boundaries[i + 1]))

    if not blocks:
        return SongStructure([], n, total_dur, False, 0, 0, "")

    # If only 1 block, try splitting by line count heuristic (8-16 lines per section)
    if len(blocks) == 1 and n > 12:
        target_size = 8 if n <= 32 else 12 if n <= 64 else 16
        blocks = []
        for start in range(0, n, target_size):
            end = min(start + target_size, n)
            if end - start >= min_section_lines:
                blocks.append((start, end))

    # Step 3: Find repeated blocks (choruses)
    block_texts = [lines[s:e] for s, e in blocks]
    repeat_matrix: dict[int, list[tuple[int, float]]] = {}

    for i in range(len(block_texts)):
        for j in range(i + 1, len(block_texts)):
            sim = _block_similarity(block_texts[i], block_texts[j])
            if sim >= chorus_threshold:
                repeat_matrix.setdefault(i, []).append((j, sim))
                repeat_matrix.setdefault(j, []).append((i, sim))

    # Identify chorus candidates: blocks that repeat most often
    chorus_blocks = set()
    if repeat_matrix:
        # Block with most repetitions is likely the chorus
        most_repeated = max(repeat_matrix.keys(), key=lambda k: len(repeat_matrix[k]))
        chorus_blocks.add(most_repeated)
        for j, _ in repeat_matrix[most_repeated]:
            chorus_blocks.add(j)

    # Step 4: Label sections
    sections: list[SongSection] = []
    verse_num = 0
    chorus_num = 0
    bridge_count = 0

    for idx, (start, end) in enumerate(blocks):
        line_count = end - start
        start_time = segments[start].start
        end_time = segments[end - 1].end

        if idx in chorus_blocks:
            chorus_num += 1
            is_first = idx == min(chorus_blocks)
            section = SongSection(
                section_type="chorus",
                label=f"Chorus{' ' + str(chorus_num) if chorus_num > 1 else ''}",
                start_line=start, end_line=end,
                start_time=start_time, end_time=end_time,
                line_count=line_count,
                is_repeat=not is_first,
                repeat_of=min(chorus_blocks) if not is_first else None,
                confidence=0.8 if len(chorus_blocks) >= 2 else 0.5,
            )
        elif idx == 0 and line_count <= 4 and start_time < 15:
            section = SongSection(
                section_type="intro", label="Intro",
                start_line=start, end_line=end,
                start_time=start_time, end_time=end_time,
                line_count=line_count, confidence=0.6,
            )
        elif idx == len(blocks) - 1 and line_count <= 4:
            section = SongSection(
                section_type="outro", label="Outro",
                start_line=start, end_line=end,
                start_time=start_time, end_time=end_time,
                line_count=line_count, confidence=0.6,
            )
        elif line_count <= 4 and chorus_blocks:
            # Short non-chorus section between choruses → likely hook or bridge
            bridge_count += 1
            section = SongSection(
                section_type="bridge",
                label=f"Bridge{' ' + str(bridge_count) if bridge_count > 1 else ''}",
                start_line=start, end_line=end,
                start_time=start_time, end_time=end_time,
                line_count=line_count, confidence=0.4,
            )
        else:
            verse_num += 1
            section = SongSection(
                section_type="verse",
                label=f"Verse {verse_num}",
                start_line=start, end_line=end,
                start_time=start_time, end_time=end_time,
                line_count=line_count, confidence=0.7,
            )

        sections.append(section)

    # Build pattern string
    type_map = {"verse": "V", "chorus": "C", "bridge": "B",
                "hook": "H", "intro": "I", "outro": "O", "break": "…"}
    pattern_parts = []
    v_count = 0
    for s in sections:
        abbr = type_map.get(s.section_type, "?")
        if s.section_type == "verse":
            v_count += 1
            abbr = f"V{v_count}"
        pattern_parts.append(abbr)
    pattern = "-".join(pattern_parts)

    structure = SongStructure(
        sections=sections,
        total_lines=n,
        total_duration=total_dur,
        has_chorus=bool(chorus_blocks),
        chorus_count=sum(1 for s in sections if s.section_type == "chorus"),
        verse_count=sum(1 for s in sections if s.section_type == "verse"),
        structure_pattern=pattern,
    )

    info(f"Structure: {pattern} ({len(sections)} sections, "
         f"{structure.verse_count}V {structure.chorus_count}C)")

    return structure
