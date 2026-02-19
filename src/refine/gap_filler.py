"""Segment gap operations — fill, merge, redistribute.

Provides automated tools for:
- Filling gaps with pause indicators
- Merging micro-gaps (< threshold)
- Redistributing segment timing evenly
- Snap-to-grid for consistent timing
"""

from __future__ import annotations

from dataclasses import dataclass

from src.transcription.base import TranscriptSegment
from src.utils.logging import info


@dataclass
class GapFillResult:
    """Result of gap fill operation."""
    original_count: int
    final_count: int
    gaps_filled: int
    micro_gaps_merged: int
    total_gap_duration: float

    def to_dict(self) -> dict:
        return {
            "original_count": self.original_count,
            "final_count": self.final_count,
            "gaps_filled": self.gaps_filled,
            "micro_gaps_merged": self.micro_gaps_merged,
            "total_gap_duration": round(self.total_gap_duration, 2),
        }


def fill_gaps(
    segments: list[TranscriptSegment],
    min_gap: float = 2.0,
    merge_threshold: float = 0.3,
    fill_text: str = "♪",
) -> tuple[list[TranscriptSegment], GapFillResult]:
    """Fill significant gaps with pause segments and merge micro-gaps.

    Args:
        segments: Input segments sorted by start time
        min_gap: Minimum gap duration to fill with a pause segment
        merge_threshold: Gaps smaller than this get merged (extend previous segment)
        fill_text: Text for gap-fill segments

    Returns:
        (processed_segments, result)
    """
    if len(segments) < 2:
        return segments, GapFillResult(len(segments), len(segments), 0, 0, 0)

    result: list[TranscriptSegment] = [segments[0]]
    gaps_filled = 0
    micro_merged = 0
    total_gap = 0.0

    for i in range(1, len(segments)):
        prev = result[-1]
        curr = segments[i]
        gap = curr.start - prev.end

        if gap > min_gap:
            # Large gap → insert pause segment
            result.append(TranscriptSegment(
                start=round(prev.end + 0.05, 3),
                end=round(curr.start - 0.05, 3),
                text=fill_text,
                confidence=1.0,
                has_word_timestamps=False,
            ))
            gaps_filled += 1
            total_gap += gap
        elif 0 < gap <= merge_threshold:
            # Micro gap → extend previous segment
            result[-1] = TranscriptSegment(
                start=prev.start,
                end=curr.start,
                text=prev.text,
                words=prev.words,
                confidence=prev.confidence,
                has_word_timestamps=prev.has_word_timestamps,

            )
            micro_merged += 1

        result.append(curr)

    info(f"Gap fill: {gaps_filled} filled, {micro_merged} micro-merged, "
         f"total gap {total_gap:.1f}s")

    return result, GapFillResult(
        original_count=len(segments),
        final_count=len(result),
        gaps_filled=gaps_filled,
        micro_gaps_merged=micro_merged,
        total_gap_duration=total_gap,
    )


def redistribute_timing(
    segments: list[TranscriptSegment],
    total_duration: float | None = None,
    gap: float = 0.05,
) -> list[TranscriptSegment]:
    """Redistribute segment timing evenly across the total duration.

    Useful when timing is completely wrong but text order is correct.
    Preserves original text and word timestamps are dropped.

    Args:
        segments: Input segments
        total_duration: Total audio duration (uses last segment end if None)
        gap: Gap between segments in seconds
    """
    if not segments:
        return segments

    if total_duration is None:
        total_duration = segments[-1].end

    n = len(segments)
    total_text = sum(len(s.text) for s in segments)
    if total_text == 0:
        return segments

    usable = total_duration - gap * (n - 1)
    if usable <= 0:
        usable = total_duration

    result = []
    cursor = 0.0
    for seg in segments:
        frac = len(seg.text) / total_text
        dur = usable * frac
        result.append(TranscriptSegment(
            start=round(cursor, 3),
            end=round(cursor + dur, 3),
            text=seg.text,
            confidence=seg.confidence,
            has_word_timestamps=False,
    
        ))
        cursor += dur + gap

    info(f"Timing redistributed: {n} segments over {total_duration:.1f}s")
    return result
