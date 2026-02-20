"""Segmentation: CPS limits, line breaks, duration rules, smart splitting."""

from __future__ import annotations

import re
from copy import deepcopy

from src.transcription.base import TranscriptSegment, WordInfo
from src.utils.logging import debug, warn


def compute_cps(segment: TranscriptSegment) -> float:
    duration = segment.end - segment.start
    if duration <= 0:
        return 999.0
    return len(segment.text) / duration


def should_split(segment: TranscriptSegment, max_cps: float = 18.0,
                 max_duration: float = 6.0, max_chars: int = 84,
                 max_lines: int = 2) -> bool:
    if segment.end - segment.start > max_duration:
        return True
    if compute_cps(segment) > max_cps:
        return True
    if len(segment.text) > max_chars * max_lines:
        return True
    return False


def find_split_point(segment: TranscriptSegment, max_chars_per_line: int = 42) -> int | None:
    text = segment.text
    mid = len(text) // 2

    # prefer splitting at punctuation near midpoint
    for punct in [". ", "! ", "? ", ", ", "; ", " - ", "… "]:
        idx = text.rfind(punct, mid // 2, mid + mid // 2)
        if idx > 0:
            return idx + len(punct)

    # fallback: split at space nearest to midpoint
    left = text.rfind(" ", 0, mid)
    right = text.find(" ", mid)
    if left > 0 and right > 0:
        return left + 1 if (mid - left) <= (right - mid) else right + 1
    if left > 0:
        return left + 1
    if right > 0:
        return right + 1
    return None


def split_segment(segment: TranscriptSegment) -> list[TranscriptSegment]:
    split_pos = find_split_point(segment)
    if split_pos is None:
        return [segment]

    text1 = segment.text[:split_pos].strip()
    text2 = segment.text[split_pos:].strip()

    if not text1 or not text2:
        return [segment]

    duration = segment.end - segment.start
    ratio = len(text1) / max(len(segment.text), 1)
    split_time = segment.start + duration * ratio

    # distribute words if available
    words1, words2 = [], []
    if segment.words:
        for w in segment.words:
            if w.end <= split_time + 0.05:
                words1.append(w)
            else:
                words2.append(w)
        if words1:
            split_time = words1[-1].end + 0.01

    seg1 = TranscriptSegment(
        start=segment.start, end=split_time, text=text1,
        words=words1, confidence=segment.confidence,
        has_word_timestamps=bool(words1),
    )
    seg2 = TranscriptSegment(
        start=split_time, end=segment.end, text=text2,
        words=words2, confidence=segment.confidence,
        has_word_timestamps=bool(words2),
    )
    return [seg1, seg2]


def merge_short_segments(segments: list[TranscriptSegment],
                         min_duration: float = 1.0,
                         max_chars: int = 84) -> list[TranscriptSegment]:
    if not segments:
        return segments

    result: list[TranscriptSegment] = [deepcopy(segments[0])]
    for seg in segments[1:]:
        prev = result[-1]
        prev_dur = prev.end - prev.start
        combined_len = len(prev.text) + 1 + len(seg.text)

        if prev_dur < min_duration and combined_len <= max_chars:
            prev.end = seg.end
            prev.text = prev.text + " " + seg.text
            prev.words.extend(seg.words)
            prev.confidence = min(prev.confidence, seg.confidence)
        else:
            result.append(deepcopy(seg))
    return result


def ensure_gaps(segments: list[TranscriptSegment], min_gap_ms: int = 80) -> list[TranscriptSegment]:
    """Ensure minimum gap between adjacent segments, adjusting word timestamps too."""
    gap = min_gap_ms / 1000
    for i in range(1, len(segments)):
        if segments[i].start - segments[i - 1].end < gap:
            mid = (segments[i - 1].end + segments[i].start) / 2
            new_end_prev = mid - gap / 2
            new_start_curr = mid + gap / 2

            # Shift word timestamps in previous segment if its end was trimmed
            delta_prev = new_end_prev - segments[i - 1].end
            if delta_prev != 0 and segments[i - 1].words:
                _clamp_words_to_segment(segments[i - 1].words,
                                        segments[i - 1].start, new_end_prev)

            # Shift word timestamps in current segment if its start was pushed later
            delta_curr = new_start_curr - segments[i].start
            if delta_curr != 0 and segments[i].words:
                _clamp_words_to_segment(segments[i].words,
                                        new_start_curr, segments[i].end)

            segments[i - 1].end = new_end_prev
            segments[i].start = new_start_curr
    return segments


def _clamp_words_to_segment(words: list[WordInfo], seg_start: float, seg_end: float) -> None:
    """Clamp word timestamps to lie within [seg_start, seg_end].

    If words fall outside the new boundary they are proportionally compressed
    so relative ordering and durations are preserved as much as possible.
    """
    if not words:
        return

    w_start = words[0].start
    w_end = words[-1].end

    # Nothing to do if all words already fit
    if w_start >= seg_start and w_end <= seg_end:
        return

    # Proportional rescale of all word timestamps into [seg_start, seg_end]
    old_span = w_end - w_start
    new_span = seg_end - seg_start
    if old_span <= 0 or new_span <= 0:
        # Degenerate case: stack all words at seg_start
        for w in words:
            w.start = seg_start
            w.end = seg_end
        return

    scale = new_span / old_span
    for w in words:
        w.start = seg_start + (w.start - w_start) * scale
        w.end = seg_start + (w.end - w_start) * scale
        # Ensure minimum word duration
        if w.end <= w.start:
            w.end = w.start + 0.02


def add_line_breaks(segment: TranscriptSegment, max_chars_per_line: int = 42,
                    max_lines: int = 2) -> str:
    text = segment.text
    if len(text) <= max_chars_per_line:
        return text

    lines: list[str] = []
    current_line = ""
    words = text.split()

    for i, word in enumerate(words):
        test_line = f"{current_line} {word}".strip() if current_line else word
        if len(test_line) > max_chars_per_line and current_line:
            lines.append(current_line)
            current_line = word
            if len(lines) >= max_lines - 1:
                current_line = " ".join(words[i:])
                break
        else:
            current_line = test_line

    if current_line:
        lines.append(current_line)

    return "\n".join(lines[:max_lines])


def refine_segments(segments: list[TranscriptSegment], cps: float = 18.0,
                    min_duration: float = 1.0, max_duration: float = 6.0,
                    max_chars_per_line: int = 42, max_lines: int = 2,
                    min_gap_ms: int = 80) -> list[TranscriptSegment]:
    result: list[TranscriptSegment] = []
    max_chars = max_chars_per_line * max_lines

    for seg in segments:
        if should_split(seg, cps, max_duration, max_chars, max_lines):
            parts = split_segment(seg)
            # recursively split if still too long
            for p in parts:
                if should_split(p, cps, max_duration, max_chars, max_lines):
                    result.extend(split_segment(p))
                else:
                    result.append(p)
        else:
            result.append(deepcopy(seg))

    result = merge_short_segments(result, min_duration, max_chars)
    result = ensure_gaps(result, min_gap_ms)

    for seg in result:
        seg.text = add_line_breaks(seg, max_chars_per_line, max_lines)

    return result
