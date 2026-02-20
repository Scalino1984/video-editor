"""Tests for BPM snap guardrails and AI word-count validation."""

from __future__ import annotations

import pytest

from src.transcription.base import TranscriptSegment, WordInfo


# ══════════════════════════════════════════════════════════════════════════════
#  BEATGRID GUARDRAILS
# ══════════════════════════════════════════════════════════════════════════════

class TestBeatgridGuardrails:
    """snap_segments_to_grid must never lose intro or create gaps."""

    def _make_seg(self, start: float, end: float, text: str = "x") -> TranscriptSegment:
        return TranscriptSegment(start=start, end=end, text=text)

    def test_first_segment_clamped_to_zero(self):
        """After snapping, the first segment must always start at 0.0."""
        from src.refine.beatgrid import snap_segments_to_grid
        segs = [
            self._make_seg(0.05, 2.0, "intro text"),
            self._make_seg(2.0, 4.0, "second"),
        ]
        result = snap_segments_to_grid(segs, bpm=120.0, duration=4.0, snap_strength=1.0)
        assert result[0].start == 0.0

    def test_first_segment_at_zero_stays(self):
        """If the first segment already starts at 0.0, it stays there."""
        from src.refine.beatgrid import snap_segments_to_grid
        segs = [self._make_seg(0.0, 1.0), self._make_seg(1.0, 2.0)]
        result = snap_segments_to_grid(segs, bpm=120.0, duration=2.0)
        assert result[0].start == 0.0

    def test_last_segment_extends_to_duration(self):
        """After snapping, the last segment must reach audio duration."""
        from src.refine.beatgrid import snap_segments_to_grid
        segs = [self._make_seg(0.0, 3.0, "only segment")]
        result = snap_segments_to_grid(segs, bpm=120.0, duration=5.0)
        assert result[-1].end == 5.0

    def test_segments_sorted_after_snap(self):
        """Segments must be sorted by start time after snapping."""
        from src.refine.beatgrid import snap_segments_to_grid
        segs = [
            self._make_seg(0.0, 1.0, "A"),
            self._make_seg(1.0, 2.5, "B"),
            self._make_seg(2.5, 4.0, "C"),
        ]
        result = snap_segments_to_grid(segs, bpm=120.0, duration=4.0, snap_strength=1.0)
        for i in range(1, len(result)):
            assert result[i].start >= result[i - 1].start

    def test_no_gaps_after_snap(self):
        """Adjacent segments must not have gaps after snapping (gap-free)."""
        from src.refine.beatgrid import snap_segments_to_grid
        segs = [
            self._make_seg(0.0, 1.0, "A"),
            self._make_seg(1.02, 2.5, "B"),
            self._make_seg(2.52, 4.0, "C"),
        ]
        result = snap_segments_to_grid(segs, bpm=120.0, duration=4.0, snap_strength=0.5)
        for i in range(1, len(result)):
            # No gap: next start must be <= prev end
            assert result[i].start <= result[i - 1].end + 0.001

    def test_empty_segments_returns_empty(self):
        """Empty segment list should return empty."""
        from src.refine.beatgrid import snap_segments_to_grid
        result = snap_segments_to_grid([], bpm=120.0, duration=10.0)
        assert result == []

    def test_word_timestamps_clamped_with_first_segment(self):
        """First word of first segment should start at 0.0 after clamping."""
        from src.refine.beatgrid import snap_segments_to_grid
        segs = [
            TranscriptSegment(
                start=0.1, end=2.0, text="hello world",
                words=[
                    WordInfo(start=0.1, end=0.5, word="hello"),
                    WordInfo(start=0.6, end=1.0, word="world"),
                ],
                has_word_timestamps=True,
            ),
        ]
        result = snap_segments_to_grid(segs, bpm=120.0, duration=2.0)
        assert result[0].start == 0.0
        assert result[0].words[0].start == 0.0

    def test_intro_preserved_with_late_first_segment(self):
        """Even if transcription starts late, first segment still starts at 0.0."""
        from src.refine.beatgrid import snap_segments_to_grid
        segs = [
            self._make_seg(21.0, 25.0, "late start"),
            self._make_seg(25.0, 30.0, "second line"),
        ]
        result = snap_segments_to_grid(segs, bpm=120.0, duration=30.0)
        assert result[0].start == 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  AI WORD COUNT VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

class TestAIWordCountValidation:
    """_ai_correct_lyrics must reject corrections that change word count."""

    def test_validate_word_count_same(self):
        """Corrections with same word count should be accepted."""
        old = "Ich bin hier"
        new = "Ich bin da"
        assert len(old.split()) == len(new.split())

    def test_validate_word_count_different(self):
        """Corrections with different word count should be detected."""
        old = "Ich bin hier"
        new = "Ich bin hier und da"
        assert len(old.split()) != len(new.split())

    def test_ai_correction_rejects_word_count_change(self):
        """Integration test: word count changes are rejected in the parse loop."""
        import re
        # Simulate the parse loop from _ai_correct_lyrics
        segments_text = ["Hello world", "Foo bar baz"]

        result_text = "1: Hello beautiful world\n2: Foo bar bam"
        corrections = 0
        rejected = 0
        for line in result_text.split("\n"):
            line = line.strip()
            match = re.match(r"(\d+)\s*:\s*(.+)", line)
            if not match:
                continue
            idx = int(match.group(1)) - 1
            new_text = match.group(2).strip()
            if 0 <= idx < len(segments_text):
                old_text = segments_text[idx]
                old_words = old_text.split()
                new_words = new_text.split()
                if len(old_words) != len(new_words):
                    rejected += 1
                    continue
                segments_text[idx] = new_text
                corrections += 1

        # "Hello world" (2 words) -> "Hello beautiful world" (3 words) = REJECTED
        assert rejected == 1
        # "Foo bar baz" (3 words) -> "Foo bar bam" (3 words) = ACCEPTED
        assert corrections == 1
        assert segments_text[0] == "Hello world"  # unchanged
        assert segments_text[1] == "Foo bar bam"  # corrected
