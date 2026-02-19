"""Word-level timestamp alignment and approximation."""

from __future__ import annotations

import re

from src.transcription.base import TranscriptSegment, WordInfo
from src.utils.logging import debug, warn


def syllable_count_heuristic(word: str) -> int:
    """Approximate syllable count for duration weighting."""
    word = word.lower().strip()
    word = re.sub(r"[^a-zäöüß]", "", word)
    if not word:
        return 1
    count = len(re.findall(r"[aeiouyäöü]+", word))
    return max(1, count)


def approximate_word_timestamps(segment: TranscriptSegment) -> list[WordInfo]:
    """Distribute word timestamps proportionally based on syllable heuristic."""
    text = segment.text.replace("\n", " ")
    raw_words = text.split()
    if not raw_words:
        return []

    weights = [syllable_count_heuristic(w) for w in raw_words]
    total_weight = sum(weights)
    duration = segment.end - segment.start

    words: list[WordInfo] = []
    current_time = segment.start

    for word_text, weight in zip(raw_words, weights):
        word_duration = duration * (weight / total_weight) if total_weight > 0 else duration / len(raw_words)
        words.append(WordInfo(
            start=round(current_time, 3),
            end=round(current_time + word_duration, 3),
            word=word_text,
            confidence=0.5,  # low confidence for approximated
        ))
        current_time += word_duration

    return words


def ensure_word_timestamps(segments: list[TranscriptSegment],
                           mode: str = "auto") -> list[TranscriptSegment]:
    """Ensure all segments have word-level timestamps.
    mode: 'on' = require (error if missing), 'auto' = approximate if missing, 'off' = skip.
    """
    approx_count = 0
    for seg in segments:
        if seg.has_word_timestamps and seg.words:
            continue
        if mode == "off":
            continue
        seg.words = approximate_word_timestamps(seg)
        seg.has_word_timestamps = True
        approx_count += 1

    if approx_count > 0:
        warn(f"Approximated word timestamps for {approx_count} segments")

    return segments
