"""Auto CPS (Characters Per Second) fixer.

Batch-fixes segments that exceed CPS limits by:
1. Splitting at natural break points (punctuation, word boundaries)
2. Redistributing timing proportionally
3. Respecting word timestamps when available
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.transcription.base import TranscriptSegment, WordInfo
from src.utils.logging import info, debug


@dataclass
class CPSFixResult:
    """Result of auto-CPS fix operation."""
    original_count: int
    fixed_count: int
    segments_split: int
    segments_trimmed: int
    max_cps_before: float
    max_cps_after: float
    avg_cps_before: float
    avg_cps_after: float

    def to_dict(self) -> dict:
        return {
            "original_count": self.original_count,
            "fixed_count": self.fixed_count,
            "segments_split": self.segments_split,
            "segments_trimmed": self.segments_trimmed,
            "max_cps_before": round(self.max_cps_before, 1),
            "max_cps_after": round(self.max_cps_after, 1),
            "avg_cps_before": round(self.avg_cps_before, 1),
            "avg_cps_after": round(self.avg_cps_after, 1),
        }


def _cps(seg: TranscriptSegment) -> float:
    """Calculate characters per second for a segment."""
    dur = seg.end - seg.start
    return len(seg.text) / dur if dur > 0 else 999.0


def _find_split_point(text: str) -> int | None:
    """Find the best split point in text (punctuation > conjunction > midpoint)."""
    # Priority 1: Split at comma, semicolon, dash
    for pattern in [r",\s", r";\s", r"\s-\s", r"\s–\s"]:
        m = list(re.finditer(pattern, text))
        if m:
            # Pick split closest to middle
            mid = len(text) // 2
            best = min(m, key=lambda x: abs(x.start() - mid))
            return best.end()

    # Priority 2: Split at German conjunctions/prepositions
    for word in ["und", "oder", "aber", "denn", "weil", "dass", "wenn", "als",
                 "with", "and", "but", "the", "for", "that", "when"]:
        pattern = rf"\s{word}\s"
        m = list(re.finditer(pattern, text, re.IGNORECASE))
        if m:
            mid = len(text) // 2
            best = min(m, key=lambda x: abs(x.start() - mid))
            return best.start() + 1  # split before the conjunction

    # Priority 3: Split at nearest word boundary to middle
    mid = len(text) // 2
    # Search outward from middle for a space
    for offset in range(0, len(text) // 2):
        for pos in [mid + offset, mid - offset]:
            if 0 < pos < len(text) and text[pos] == ' ':
                return pos + 1
    return None


def _split_segment(seg: TranscriptSegment, max_cps: float) -> list[TranscriptSegment]:
    """Split a segment into smaller pieces to meet CPS limit."""
    if _cps(seg) <= max_cps:
        return [seg]

    text = seg.text
    split_pos = _find_split_point(text)
    if split_pos is None or split_pos <= 0 or split_pos >= len(text):
        return [seg]  # can't split

    part_a = text[:split_pos].rstrip()
    part_b = text[split_pos:].lstrip()
    if not part_a or not part_b:
        return [seg]

    # Distribute time proportionally by character count
    total_dur = seg.end - seg.start
    ratio = len(part_a) / len(text)
    split_time = seg.start + total_dur * ratio

    # If we have word timestamps, find the exact split time
    if seg.words:
        char_count = 0
        for w in seg.words:
            char_count += len(w.word) + 1
            if char_count >= split_pos:
                split_time = w.end
                break

    # Build two new segments
    words_a, words_b = [], []
    if seg.words:
        for w in seg.words:
            if w.end <= split_time + 0.05:
                words_a.append(w)
            else:
                words_b.append(w)

    seg_a = TranscriptSegment(
        start=seg.start, end=round(split_time, 3), text=part_a,
        words=words_a, confidence=seg.confidence,
        has_word_timestamps=bool(words_a),
    )
    seg_b = TranscriptSegment(
        start=round(split_time, 3), end=seg.end, text=part_b,
        words=words_b, confidence=seg.confidence,
        has_word_timestamps=bool(words_b),
    )

    # Recursive split if still too fast
    result = []
    for s in [seg_a, seg_b]:
        if _cps(s) > max_cps and len(s.text.split()) >= 3:
            result.extend(_split_segment(s, max_cps))
        else:
            result.append(s)
    return result


def auto_fix_cps(
    segments: list[TranscriptSegment],
    max_cps: float = 22.0,
    min_duration: float = 0.5,
) -> tuple[list[TranscriptSegment], CPSFixResult]:
    """Auto-fix all segments that exceed the CPS limit.

    Args:
        segments: Input segments
        max_cps: Maximum allowed characters per second
        min_duration: Minimum segment duration after fixing

    Returns:
        (fixed_segments, result_stats)
    """
    if not segments:
        return segments, CPSFixResult(0, 0, 0, 0, 0, 0, 0, 0)

    # Before stats
    cps_values = [_cps(s) for s in segments]
    max_before = max(cps_values)
    avg_before = sum(cps_values) / len(cps_values)

    result: list[TranscriptSegment] = []
    splits = 0
    trims = 0

    for seg in segments:
        if _cps(seg) <= max_cps:
            result.append(seg)
            continue

        # Try splitting
        pieces = _split_segment(seg, max_cps)
        if len(pieces) > 1:
            result.extend(pieces)
            splits += 1
        else:
            # Can't split — just extend duration slightly if possible
            needed_dur = len(seg.text) / max_cps
            new_end = seg.start + needed_dur
            result.append(TranscriptSegment(
                start=seg.start, end=round(new_end, 3), text=seg.text,
                words=seg.words, confidence=seg.confidence,
                has_word_timestamps=seg.has_word_timestamps,
            ))
            trims += 1

    # Filter too-short segments (but only truly degenerate ones)
    result = [s for s in result if s.end - s.start >= 0.05]

    # After stats
    cps_after = [_cps(s) for s in result]
    max_after = max(cps_after) if cps_after else 0
    avg_after = sum(cps_after) / len(cps_after) if cps_after else 0

    fix_result = CPSFixResult(
        original_count=len(segments),
        fixed_count=len(result),
        segments_split=splits,
        segments_trimmed=trims,
        max_cps_before=max_before,
        max_cps_after=max_after,
        avg_cps_before=avg_before,
        avg_cps_after=avg_after,
    )

    info(f"CPS fix: {splits} split, {trims} trimmed | "
         f"max CPS {max_before:.0f}→{max_after:.0f} | "
         f"segments {len(segments)}→{len(result)}")

    return result, fix_result
