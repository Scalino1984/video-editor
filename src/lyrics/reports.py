"""Lyrics alignment reports — match scoring, alignment quality, diff detection.

Generates:
- alignment_report.json: per-line match scores, timing confidence
- diff_report.json: differences between ASR text and lyrics text (hybrid mode)
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.transcription.base import TranscriptSegment, WordInfo
from src.utils.logging import info, warn, debug


@dataclass
class LineAlignment:
    """Alignment result for a single lyrics line."""
    line_index: int
    lyrics_text: str
    asr_text: str
    match_score: float          # 0.0 – 1.0
    timing_source: str          # "word_level" | "segment_level" | "estimated"
    start: float
    end: float
    word_count_lyrics: int
    word_count_asr: int
    needs_review: bool
    diff_words: list[str] = field(default_factory=list)  # words that differ


@dataclass
class AlignmentReport:
    """Full alignment report for lyrics template alignment."""
    total_lines: int
    matched_lines: int
    avg_match_score: float
    min_match_score: float
    lines_needing_review: int
    unresolved_lines: int
    approx_timing_lines: int
    word_level_lines: int
    total_duration: float
    line_alignments: list[LineAlignment]

    @property
    def needs_review(self) -> bool:
        return (
            self.avg_match_score < 0.75
            or self.unresolved_lines > 0
            or self.approx_timing_lines > self.total_lines * 0.3
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_lines": self.total_lines,
            "matched_lines": self.matched_lines,
            "avg_match_score": round(self.avg_match_score, 3),
            "min_match_score": round(self.min_match_score, 3),
            "lines_needing_review": self.lines_needing_review,
            "unresolved_lines": self.unresolved_lines,
            "approx_timing_lines": self.approx_timing_lines,
            "word_level_lines": self.word_level_lines,
            "total_duration": round(self.total_duration, 2),
            "needs_review": self.needs_review,
            "lines": [
                {
                    "index": la.line_index,
                    "lyrics": la.lyrics_text,
                    "asr": la.asr_text,
                    "score": round(la.match_score, 3),
                    "timing": la.timing_source,
                    "start": round(la.start, 3),
                    "end": round(la.end, 3),
                    "needs_review": la.needs_review,
                    "diffs": la.diff_words,
                }
                for la in self.line_alignments
            ],
        }


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, strip punctuation."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.split())


def compute_match_score(lyrics_text: str, asr_text: str) -> float:
    """Compute similarity between lyrics line and ASR output."""
    a = _normalize(lyrics_text)
    b = _normalize(asr_text)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def find_diff_words(lyrics_text: str, asr_text: str) -> list[str]:
    """Find words that differ between lyrics and ASR."""
    a_words = _normalize(lyrics_text).split()
    b_words = _normalize(asr_text).split()
    diffs = []
    sm = SequenceMatcher(None, a_words, b_words)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "replace":
            for w in a_words[i1:i2]:
                diffs.append(f"-{w}")
            for w in b_words[j1:j2]:
                diffs.append(f"+{w}")
        elif op == "delete":
            for w in a_words[i1:i2]:
                diffs.append(f"-{w}")
        elif op == "insert":
            for w in b_words[j1:j2]:
                diffs.append(f"+{w}")
    return diffs


def generate_alignment_report(
    lyrics_lines: list[str],
    aligned_segments: list[TranscriptSegment],
    original_segments: list[TranscriptSegment],
) -> AlignmentReport:
    """Generate alignment quality report.

    Args:
        lyrics_lines: Target lines from lyrics file
        aligned_segments: Segments after alignment (text = lyrics)
        original_segments: Original ASR segments (for comparison)
    """
    # Build flat ASR word sequence for global matching
    asr_words_flat: list[str] = []
    for s in original_segments:
        if s.words:
            asr_words_flat.extend(_normalize(w.word) for w in s.words)
        else:
            asr_words_flat.extend(_normalize(s.text).split())

    # Also build full ASR text for fallback
    asr_full = " ".join(s.text for s in original_segments)

    line_alignments: list[LineAlignment] = []
    unresolved = 0
    approx_count = 0
    word_level_count = 0
    asr_cursor = 0  # track position in ASR word sequence

    for i, seg in enumerate(aligned_segments):
        lyrics_text = lyrics_lines[i] if i < len(lyrics_lines) else seg.text

        # Strategy 1: time-range overlap (good when timing is accurate)
        asr_text_by_time = _find_asr_text_in_range(
            original_segments, seg.start, seg.end
        )

        # Strategy 2: sliding window over ASR word sequence (robust fallback)
        asr_text_by_words, new_cursor = _find_best_asr_match_sequential(
            asr_words_flat, asr_cursor, lyrics_text
        )

        # Use whichever produces a better score
        score_by_time = compute_match_score(lyrics_text, asr_text_by_time) if asr_text_by_time else 0.0
        score_by_words = compute_match_score(lyrics_text, asr_text_by_words) if asr_text_by_words else 0.0

        if score_by_words > score_by_time:
            asr_text = asr_text_by_words
            score = score_by_words
            asr_cursor = new_cursor  # advance cursor
        else:
            asr_text = asr_text_by_time
            score = score_by_time

        diffs = find_diff_words(lyrics_text, asr_text) if score < 0.95 else []

        # Determine timing source
        if seg.has_word_timestamps and seg.words:
            timing = "word_level"
            word_level_count += 1
        elif seg.confidence > 0.5:
            timing = "segment_level"
        else:
            timing = "estimated"
            approx_count += 1

        needs_rev = score < 0.6 or timing == "estimated"
        if timing == "estimated":
            unresolved += 1

        line_alignments.append(LineAlignment(
            line_index=i,
            lyrics_text=lyrics_text,
            asr_text=asr_text,
            match_score=score,
            timing_source=timing,
            start=seg.start,
            end=seg.end,
            word_count_lyrics=len(lyrics_text.split()),
            word_count_asr=len(asr_text.split()),
            needs_review=needs_rev,
            diff_words=diffs,
        ))

    scores = [la.match_score for la in line_alignments] or [0.0]
    total_dur = aligned_segments[-1].end if aligned_segments else 0

    report = AlignmentReport(
        total_lines=len(lyrics_lines),
        matched_lines=len(aligned_segments),
        avg_match_score=sum(scores) / len(scores),
        min_match_score=min(scores),
        lines_needing_review=sum(1 for la in line_alignments if la.needs_review),
        unresolved_lines=unresolved,
        approx_timing_lines=approx_count,
        word_level_lines=word_level_count,
        total_duration=total_dur,
        line_alignments=line_alignments,
    )

    info(f"Alignment report: avg_score={report.avg_match_score:.2f}, "
         f"review={report.lines_needing_review}/{report.total_lines}, "
         f"unresolved={report.unresolved_lines}")

    return report


def _find_best_asr_match_sequential(
    asr_words: list[str],
    cursor: int,
    lyrics_text: str,
) -> tuple[str, int]:
    """Find the best matching ASR text for a lyrics line using sliding window.

    Searches forward from cursor through the ASR word sequence,
    trying windows of similar length to the lyrics line.
    Returns (best_matching_text, new_cursor_position).
    """
    lyrics_norm = _normalize(lyrics_text)
    lyrics_tokens = lyrics_norm.split()
    if not lyrics_tokens or not asr_words:
        return ("", cursor)

    n_target = len(lyrics_tokens)
    best_score = 0.0
    best_text = ""
    best_end = cursor

    # Search forward with some lookahead
    search_end = min(len(asr_words), cursor + n_target * 4 + 30)

    for win_start in range(cursor, search_end):
        # Try windows of varying sizes around the target length
        for win_size in range(max(1, n_target - 2), n_target + 4):
            win_end = win_start + win_size
            if win_end > len(asr_words):
                break
            candidate = " ".join(asr_words[win_start:win_end])
            score = SequenceMatcher(None, lyrics_norm, candidate).ratio()
            if score > best_score:
                best_score = score
                best_text = candidate
                best_end = win_end

    # Only advance cursor if we found a reasonable match
    if best_score >= 0.3:
        return (best_text, best_end)
    return (best_text, cursor)


def _find_asr_text_in_range(
    segments: list[TranscriptSegment],
    start: float,
    end: float,
) -> str:
    """Find ASR text that overlaps with the given time range."""
    texts = []
    for seg in segments:
        # Check overlap
        if seg.end <= start - 0.5 or seg.start >= end + 0.5:
            continue
        # Check word-level overlap if available
        if seg.words:
            for w in seg.words:
                if w.end > start - 0.1 and w.start < end + 0.1:
                    texts.append(w.word)
        else:
            texts.append(seg.text)
    return " ".join(texts)


def save_alignment_report(report: AlignmentReport, output_path: Path) -> Path:
    """Save alignment report as JSON."""
    path = output_path.with_suffix(".alignment_report.json")
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    info(f"Alignment report saved: {path.name}")
    return path


def save_diff_report(report: AlignmentReport, output_path: Path) -> Path:
    """Save diff report (hybrid mode) — only lines with differences."""
    diffs = [
        la for la in report.line_alignments
        if la.diff_words or la.match_score < 0.95
    ]
    data = {
        "total_diffs": len(diffs),
        "lines": [
            {
                "index": d.line_index,
                "lyrics": d.lyrics_text,
                "asr": d.asr_text,
                "score": round(d.match_score, 3),
                "diffs": d.diff_words,
            }
            for d in diffs
        ],
    }
    path = output_path.with_suffix(".diff_report.json")
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    info(f"Diff report saved: {path.name} ({len(diffs)} lines with differences)")
    return path
