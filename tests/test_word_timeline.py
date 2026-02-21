"""Tests for word_timeline module: data model, tokenizer, remap flow, ASS export."""

from __future__ import annotations

import json

import pytest

from src.refine.word_timeline import (
    AlignmentRun,
    SegmentWordMapping,
    SyllableToken,
    WordTimeline,
    WordToken,
    apply_derived_times,
    build_timeline_from_segments,
    compute_alignment_window,
    compute_metrics,
    derive_all_segment_times,
    derive_segment_times,
    generate_syllable_tokens,
    load_timeline,
    normalize_token,
    process_segment_edit,
    save_timeline,
    split_syllables_de,
    tokenize_text,
    tokenize_text_words_only,
    timeline_words_for_segment,
)
from src.transcription.base import TranscriptSegment, WordInfo


# ── Tokenizer / Normalizer ───────────────────────────────────────────────────


class TestNormalizeToken:
    def test_lowercase(self):
        assert normalize_token("Hello") == "hello"

    def test_strip_punctuation(self):
        assert normalize_token("Bleiben.") == "bleiben"

    def test_umlauts_preserved(self):
        assert normalize_token("Über") == "über"

    def test_empty(self):
        assert normalize_token("") == ""

    def test_pure_punctuation(self):
        assert normalize_token("...") == ""

    def test_deterministic(self):
        """Same input always produces same output."""
        for _ in range(10):
            assert normalize_token("Regeln!") == "regeln"


class TestTokenizeText:
    def test_simple(self):
        tokens = tokenize_text("Hello world")
        assert tokens == ["Hello", "world"]

    def test_trailing_punctuation(self):
        tokens = tokenize_text("Bleiben. Die")
        assert "Bleiben" in tokens
        assert "." in tokens
        assert "Die" in tokens

    def test_whitespace_normalization(self):
        tokens = tokenize_text("  multiple   spaces  ")
        assert tokens == ["multiple", "spaces"]

    def test_newline_handling(self):
        tokens = tokenize_text("line one\nline two")
        assert "one" in tokens
        assert "two" in tokens

    def test_words_only(self):
        tokens = tokenize_text_words_only("Bleiben. Die!")
        assert tokens == ["Bleiben", "Die"]

    def test_deterministic(self):
        text = "Nur Meine Regeln"
        for _ in range(10):
            assert tokenize_text(text) == ["Nur", "Meine", "Regeln"]


# ── Syllable Generator ──────────────────────────────────────────────────────


class TestSplitSyllablesDe:
    def test_single_syllable(self):
        assert split_syllables_de("Nur") == ["Nur"]

    def test_two_syllables(self):
        sylls = split_syllables_de("Regeln")
        assert len(sylls) == 2

    def test_empty(self):
        assert split_syllables_de("") == []

    def test_punctuation_only(self):
        assert split_syllables_de(".") == ["."]


class TestGenerateSyllableTokens:
    def test_single_syllable_word(self):
        wt = WordToken(word_id="w0", idx_in_run=0, surface="Nur", norm="nur",
                       start_ms=1000, end_ms=1500, confidence=0.9)
        sylls = generate_syllable_tokens(wt)
        assert len(sylls) == 1
        assert sylls[0].start_ms == 1000
        assert sylls[0].end_ms == 1500

    def test_multi_syllable_word(self):
        wt = WordToken(word_id="w1", idx_in_run=1, surface="Regeln", norm="regeln",
                       start_ms=1500, end_ms=2000, confidence=0.9)
        sylls = generate_syllable_tokens(wt)
        assert len(sylls) >= 2

    def test_duration_sum_equals_word_duration(self):
        """Invariant: syllable durations sum to word duration (±1ms rounding)."""
        wt = WordToken(word_id="w0", idx_in_run=0, surface="Regeln", norm="regeln",
                       start_ms=1000, end_ms=2000, confidence=0.9)
        sylls = generate_syllable_tokens(wt)
        total = sum(s.end_ms - s.start_ms for s in sylls)
        assert abs(total - 1000) <= 1

    def test_monotonic_and_no_overlap(self):
        """Invariant: syllables are monotonic and non-overlapping."""
        wt = WordToken(word_id="w0", idx_in_run=0, surface="Beispiel", norm="beispiel",
                       start_ms=500, end_ms=1200, confidence=0.8)
        sylls = generate_syllable_tokens(wt)
        for i in range(len(sylls) - 1):
            assert sylls[i].end_ms <= sylls[i + 1].start_ms
        for s in sylls:
            assert s.start_ms < s.end_ms

    def test_last_syllable_matches_word_end(self):
        wt = WordToken(word_id="w0", idx_in_run=0, surface="Bleiben", norm="bleiben",
                       start_ms=2000, end_ms=3000, confidence=0.85)
        sylls = generate_syllable_tokens(wt)
        assert sylls[-1].end_ms == wt.end_ms

    def test_first_syllable_matches_word_start(self):
        wt = WordToken(word_id="w0", idx_in_run=0, surface="Bleiben", norm="bleiben",
                       start_ms=2000, end_ms=3000, confidence=0.85)
        sylls = generate_syllable_tokens(wt)
        assert sylls[0].start_ms == wt.start_ms


# ── Data Model Roundtrip ────────────────────────────────────────────────────


class TestDataModelRoundtrip:
    def test_word_token_roundtrip(self):
        wt = WordToken(word_id="w0", idx_in_run=0, surface="Hello", norm="hello",
                       start_ms=100, end_ms=500, confidence=0.95)
        d = wt.to_dict()
        restored = WordToken.from_dict(d)
        assert restored.word_id == "w0"
        assert restored.surface == "Hello"
        assert restored.start_ms == 100

    def test_syllable_token_roundtrip(self):
        st = SyllableToken(syll_id="w0_s0", word_id="w0", syll_index=0,
                           text="Hel", start_ms=100, end_ms=300, confidence=0.9)
        d = st.to_dict()
        restored = SyllableToken.from_dict(d)
        assert restored.syll_id == "w0_s0"
        assert restored.text == "Hel"

    def test_alignment_run_roundtrip(self):
        run = AlignmentRun(
            run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=5000,
            model_provider="whisper", model_version="v3", params_hash="abc123",
            words=[WordToken("w0", 0, "Test", "test", 100, 500, 0.9)],
        )
        d = run.to_dict()
        restored = AlignmentRun.from_dict(d)
        assert restored.run_id == "r1"
        assert len(restored.words) == 1
        assert restored.words[0].surface == "Test"

    def test_word_timeline_roundtrip(self):
        wt = WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=5000,
                model_provider="test", model_version="1", params_hash="h1",
                words=[WordToken("w0", 0, "A", "a", 0, 100, 1.0)],
            )],
            segment_mappings=[SegmentWordMapping(segment_id=0, word_ids=["w0"])],
        )
        d = wt.to_dict()
        restored = WordTimeline.from_dict(d)
        assert len(restored.alignment_runs) == 1
        assert len(restored.segment_mappings) == 1

    def test_all_words_lookup(self):
        wt = WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=5000,
                model_provider="test", model_version="1", params_hash="h1",
                words=[
                    WordToken("w0", 0, "A", "a", 0, 100, 1.0),
                    WordToken("w1", 1, "B", "b", 100, 200, 0.9),
                ],
            )],
        )
        lookup = wt.all_words()
        assert "w0" in lookup
        assert "w1" in lookup
        assert lookup["w0"].surface == "A"


# ── Persistence ──────────────────────────────────────────────────────────────


class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        timeline = WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=5000,
                model_provider="test", model_version="1", params_hash="h1",
                words=[WordToken("w0", 0, "Test", "test", 100, 500, 0.9)],
            )],
            segment_mappings=[SegmentWordMapping(segment_id=0, word_ids=["w0"])],
        )
        save_timeline(timeline, tmp_path)
        loaded = load_timeline(tmp_path)
        assert loaded is not None
        assert len(loaded.alignment_runs) == 1
        assert loaded.alignment_runs[0].words[0].surface == "Test"

    def test_load_missing(self, tmp_path):
        assert load_timeline(tmp_path) is None


# ── Build Timeline from Segments ─────────────────────────────────────────────


class TestBuildTimeline:
    def test_from_segments_with_words(self):
        segs = [
            TranscriptSegment(start=0.0, end=2.0, text="Nur Meine Regeln",
                              has_word_timestamps=True,
                              words=[
                                  WordInfo(0.0, 0.5, "Nur", 0.9),
                                  WordInfo(0.5, 1.2, "Meine", 0.85),
                                  WordInfo(1.2, 2.0, "Regeln", 0.92),
                              ]),
            TranscriptSegment(start=2.1, end=4.0, text="Bleiben. Die",
                              has_word_timestamps=True,
                              words=[
                                  WordInfo(2.1, 2.8, "Bleiben.", 0.88),
                                  WordInfo(2.9, 4.0, "Die", 0.95),
                              ]),
        ]
        timeline = build_timeline_from_segments(segs)
        assert len(timeline.alignment_runs) == 1
        assert len(timeline.alignment_runs[0].words) == 5
        assert len(timeline.segment_mappings) == 2
        assert len(timeline.segment_mappings[0].word_ids) == 3
        assert len(timeline.segment_mappings[1].word_ids) == 2

    def test_from_segments_without_words(self):
        segs = [
            TranscriptSegment(start=0.0, end=2.0, text="Hello world"),
        ]
        timeline = build_timeline_from_segments(segs)
        assert len(timeline.alignment_runs[0].words) == 2

    def test_with_syllable_generation(self):
        segs = [
            TranscriptSegment(start=0.0, end=2.0, text="Regeln Bleiben",
                              has_word_timestamps=True,
                              words=[
                                  WordInfo(0.0, 1.0, "Regeln", 0.9),
                                  WordInfo(1.0, 2.0, "Bleiben", 0.9),
                              ]),
        ]
        timeline = build_timeline_from_segments(segs, generate_syllables=True)
        assert len(timeline.alignment_runs[0].syllables) > 2


# ── Derive Segment Times ────────────────────────────────────────────────────


class TestDeriveSegmentTimes:
    def _make_timeline(self):
        words = [
            WordToken("w0", 0, "Nur", "nur", 0, 500, 0.9),
            WordToken("w1", 1, "Meine", "meine", 500, 1200, 0.85),
            WordToken("w2", 2, "Regeln", "regeln", 1200, 2000, 0.92),
            WordToken("w3", 3, "Bleiben.", "bleiben", 2100, 2800, 0.88),
            WordToken("w4", 4, "Die", "die", 2900, 4000, 0.95),
        ]
        return WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=4000,
                model_provider="test", model_version="1", params_hash="h1",
                words=words,
            )],
            segment_mappings=[
                SegmentWordMapping(segment_id=0, word_ids=["w0", "w1", "w2"]),
                SegmentWordMapping(segment_id=1, word_ids=["w3", "w4"]),
            ],
        )

    def test_derive_single_segment(self):
        timeline = self._make_timeline()
        start, end = derive_segment_times(timeline, 0)
        assert start == 0
        assert end == 2000

    def test_derive_second_segment(self):
        timeline = self._make_timeline()
        start, end = derive_segment_times(timeline, 1)
        assert start == 2100
        assert end == 4000

    def test_derive_missing_segment_raises(self):
        timeline = self._make_timeline()
        with pytest.raises(ValueError):
            derive_segment_times(timeline, 99)

    def test_derive_all_no_overlap(self):
        timeline = self._make_timeline()
        times = derive_all_segment_times(timeline)
        assert len(times) == 2
        for i in range(len(times) - 1):
            _, _, prev_end = times[i]
            _, next_start, _ = times[i + 1]
            assert prev_end <= next_start

    def test_min_duration_enforced(self):
        words = [WordToken("w0", 0, "X", "x", 1000, 1050, 0.9)]
        timeline = WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=5000,
                model_provider="test", model_version="1", params_hash="h1",
                words=words,
            )],
            segment_mappings=[SegmentWordMapping(segment_id=0, word_ids=["w0"])],
        )
        start, end = derive_segment_times(timeline, 0, min_duration_ms=200)
        assert end - start >= 200


# ── Edit Flow: Remap Only ───────────────────────────────────────────────────


class TestRemapOnly:
    """E2E test: The "Regeln wandert" example without re-alignment."""

    def _make_scenario(self):
        """Set up the scenario from the problem statement.

        Original:
          #0 "Nur Meine Regeln"  (0:00.00 - 0:02.00)
          #1 "Bleiben. Die"      (0:02.10 - 0:04.00)

        After edit:
          #0 "Nur Meine"
          #1 "Regeln Bleiben. Die"
        """
        words = [
            WordToken("w0", 0, "Nur", "nur", 0, 500, 0.9),
            WordToken("w1", 1, "Meine", "meine", 500, 1200, 0.85),
            WordToken("w2", 2, "Regeln", "regeln", 1200, 2000, 0.92),
            WordToken("w3", 3, "Bleiben.", "bleiben", 2100, 2800, 0.88),
            WordToken("w4", 4, "Die", "die", 2900, 4000, 0.95),
        ]
        timeline = WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=4000,
                model_provider="test", model_version="1", params_hash="h1",
                words=words,
            )],
            segment_mappings=[
                SegmentWordMapping(segment_id=0, word_ids=["w0", "w1", "w2"]),
                SegmentWordMapping(segment_id=1, word_ids=["w3", "w4"]),
            ],
        )
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Nur Meine Regeln",
             "confidence": 0.9, "has_word_timestamps": True, "words": [
                 {"start": 0.0, "end": 0.5, "word": "Nur", "confidence": 0.9},
                 {"start": 0.5, "end": 1.2, "word": "Meine", "confidence": 0.85},
                 {"start": 1.2, "end": 2.0, "word": "Regeln", "confidence": 0.92},
             ]},
            {"start": 2.1, "end": 4.0, "text": "Bleiben. Die",
             "confidence": 0.88, "has_word_timestamps": True, "words": [
                 {"start": 2.1, "end": 2.8, "word": "Bleiben.", "confidence": 0.88},
                 {"start": 2.9, "end": 4.0, "word": "Die", "confidence": 0.95},
             ]},
        ]
        return segments, timeline

    def test_remap_action_is_remap(self):
        segments, timeline = self._make_scenario()
        result = process_segment_edit(segments, timeline, {
            0: "Nur Meine",
            1: "Regeln Bleiben. Die",
        })
        assert result.action == "remap"
        assert not result.needs_review

    def test_remap_word_timeline_unchanged(self):
        """WordTimeline words must remain the same — only mapping changes."""
        segments, timeline = self._make_scenario()
        words_before = {w.word_id: (w.start_ms, w.end_ms)
                        for w in timeline.alignment_runs[0].words}
        result = process_segment_edit(segments, timeline, {
            0: "Nur Meine",
            1: "Regeln Bleiben. Die",
        })
        words_after = {w.word_id: (w.start_ms, w.end_ms)
                       for w in result.timeline.alignment_runs[0].words}
        assert words_before == words_after

    def test_remap_segment_ownership_changes(self):
        segments, timeline = self._make_scenario()
        result = process_segment_edit(segments, timeline, {
            0: "Nur Meine",
            1: "Regeln Bleiben. Die",
        })
        mapping_0 = result.timeline.mapping_for_segment(0)
        mapping_1 = result.timeline.mapping_for_segment(1)
        assert mapping_0 is not None
        assert mapping_1 is not None
        assert "w2" not in mapping_0.word_ids  # "Regeln" moved out
        assert "w2" in mapping_1.word_ids      # "Regeln" moved in

    def test_remap_derived_times_correct(self):
        """After remap: derived_end(#0) < derived_start(#1)."""
        segments, timeline = self._make_scenario()
        result = process_segment_edit(segments, timeline, {
            0: "Nur Meine",
            1: "Regeln Bleiben. Die",
        })
        seg0 = result.segments[0]
        seg1 = result.segments[1]
        assert seg0["end"] <= seg1["start"]

    def test_remap_segment_0_end_reduced(self):
        """Segment 0 end should be near end of 'Meine' (~1.2s), adjusted by gap policy."""
        segments, timeline = self._make_scenario()
        result = process_segment_edit(segments, timeline, {
            0: "Nur Meine",
            1: "Regeln Bleiben. Die",
        })
        # Gap/clamp policy may shift by up to gap_min_ms/2 (10ms) at boundary
        assert abs(result.segments[0]["end"] - 1.2) < 0.02

    def test_remap_segment_1_start_reduced(self):
        """Segment 1 start should be near start of 'Regeln' (~1.2s), adjusted by gap policy."""
        segments, timeline = self._make_scenario()
        result = process_segment_edit(segments, timeline, {
            0: "Nur Meine",
            1: "Regeln Bleiben. Die",
        })
        # Gap/clamp policy may shift by up to gap_min_ms/2 (10ms) at boundary
        assert abs(result.segments[1]["start"] - 1.2) < 0.02

    def test_remap_words_list_updated(self):
        """Segment word arrays should reflect new ownership."""
        segments, timeline = self._make_scenario()
        result = process_segment_edit(segments, timeline, {
            0: "Nur Meine",
            1: "Regeln Bleiben. Die",
        })
        seg0_words = [w["word"] for w in result.segments[0]["words"]]
        seg1_words = [w["word"] for w in result.segments[1]["words"]]
        assert "Regeln" not in seg0_words
        assert "Regeln" in seg1_words


# ── Edit Flow: Re-Alignment Needed ──────────────────────────────────────────


class TestRealignNeeded:
    def test_new_word_triggers_realign(self):
        """Adding a word not in the timeline requires re-alignment."""
        words = [
            WordToken("w0", 0, "Nur", "nur", 0, 500, 0.9),
            WordToken("w1", 1, "Meine", "meine", 500, 1200, 0.85),
        ]
        timeline = WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=2000,
                model_provider="test", model_version="1", params_hash="h1",
                words=words,
            )],
            segment_mappings=[
                SegmentWordMapping(segment_id=0, word_ids=["w0", "w1"]),
            ],
        )
        segments = [
            {"start": 0.0, "end": 1.2, "text": "Nur Meine",
             "confidence": 0.9, "has_word_timestamps": True, "words": []},
        ]
        result = process_segment_edit(segments, timeline, {
            0: "Nur Meine Regeln",  # "Regeln" is new
        })
        assert result.action == "realign_needed"
        assert result.needs_review
        assert "Regeln" in result.details["unmatched_tokens"]


# ── Windowing ────────────────────────────────────────────────────────────────


class TestWindowing:
    def test_basic_window(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "A"},
            {"start": 2.1, "end": 4.0, "text": "B"},
        ]
        start, end = compute_alignment_window(segments, [0, 1], padding_ms=500)
        assert start == 0
        assert end == 4500

    def test_window_max_cap(self):
        segments = [
            {"start": 0.0, "end": 50.0, "text": "long"},
        ]
        start, end = compute_alignment_window(segments, [0], padding_ms=1000, max_window_ms=30000)
        assert end - start <= 30000


# ── Apply Derived Times ─────────────────────────────────────────────────────


class TestApplyDerivedTimes:
    def test_updates_segment_dicts(self):
        words = [
            WordToken("w0", 0, "A", "a", 100, 500, 0.9),
            WordToken("w1", 1, "B", "b", 600, 1000, 0.8),
        ]
        timeline = WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=2000,
                model_provider="test", model_version="1", params_hash="h1",
                words=words,
            )],
            segment_mappings=[
                SegmentWordMapping(segment_id=0, word_ids=["w0"]),
                SegmentWordMapping(segment_id=1, word_ids=["w1"]),
            ],
        )
        segments = [
            {"start": 0.0, "end": 1.0, "text": "A", "words": [], "has_word_timestamps": False},
            {"start": 1.0, "end": 2.0, "text": "B", "words": [], "has_word_timestamps": False},
        ]
        result = apply_derived_times(segments, timeline)
        assert result[0]["start"] == 0.1
        assert result[0]["end"] == 0.5
        assert result[1]["start"] == 0.6
        assert result[1]["end"] == 1.0
        assert len(result[0]["words"]) == 1
        assert result[0]["has_word_timestamps"] is True


# ── Metrics / Observability ──────────────────────────────────────────────────


class TestMetrics:
    def test_compute_metrics(self):
        words = [
            WordToken("w0", 0, "A", "a", 0, 100, 0.9),
            WordToken("w1", 1, "B", "b", 100, 200, 0.3),
        ]
        timeline = WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=200,
                model_provider="test", model_version="1", params_hash="h1",
                words=words,
            )],
            segment_mappings=[SegmentWordMapping(segment_id=0, word_ids=["w0", "w1"])],
        )
        metrics = compute_metrics(timeline)
        assert metrics.word_count == 2
        assert metrics.coverage_pct == 0.5  # Only w0 has conf > 0.5
        assert 0.5 < metrics.avg_confidence < 0.7
        d = metrics.to_dict()
        assert "coverage_pct" in d


# ── ASS Export Helpers ───────────────────────────────────────────────────────


class TestTimelineExportHelpers:
    def test_timeline_words_for_segment(self):
        words = [
            WordToken("w0", 0, "Hello", "hello", 0, 500, 0.9),
            WordToken("w1", 1, "World", "world", 500, 1000, 0.8),
        ]
        timeline = WordTimeline(
            alignment_runs=[AlignmentRun(
                run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=1000,
                model_provider="test", model_version="1", params_hash="h1",
                words=words,
            )],
            segment_mappings=[SegmentWordMapping(segment_id=0, word_ids=["w0", "w1"])],
        )
        winfos = timeline_words_for_segment(timeline, 0)
        assert len(winfos) == 2
        assert winfos[0].word == "Hello"
        assert winfos[0].start == 0.0
        assert winfos[1].end == 1.0

    def test_syllable_karaoke_line(self):
        from src.export.karaoke_tags import generate_syllable_karaoke_line

        sylls = [
            SyllableToken("w0_s0", "w0", 0, "Hel", 0, 300, 0.9),
            SyllableToken("w0_s1", "w0", 1, "lo", 300, 500, 0.9),
            SyllableToken("w1_s0", "w1", 0, "World", 500, 1000, 0.8),
        ]
        line = generate_syllable_karaoke_line(sylls, mode="kf")
        assert "\\kf" in line
        assert "Hel" in line
        assert "lo" in line
        assert "World" in line

    def test_syllable_karaoke_has_spaces_between_words(self):
        from src.export.karaoke_tags import generate_syllable_karaoke_line

        sylls = [
            SyllableToken("w0_s0", "w0", 0, "Re", 0, 200, 0.9),
            SyllableToken("w0_s1", "w0", 1, "geln", 200, 500, 0.9),
            SyllableToken("w1_s0", "w1", 0, "Blei", 500, 700, 0.8),
            SyllableToken("w1_s1", "w1", 1, "ben", 700, 1000, 0.8),
        ]
        line = generate_syllable_karaoke_line(sylls, mode="kf")
        # Should have space between "geln" and "Blei" (word boundary)
        assert "geln " in line


# ── Regression: Deterministic ────────────────────────────────────────────────


class TestDeterministicRegression:
    """Same input must always produce same output."""

    def test_build_timeline_deterministic(self):
        segs = [
            TranscriptSegment(start=0.0, end=2.0, text="Nur Meine Regeln",
                              has_word_timestamps=True,
                              words=[
                                  WordInfo(0.0, 0.5, "Nur", 0.9),
                                  WordInfo(0.5, 1.2, "Meine", 0.85),
                                  WordInfo(1.2, 2.0, "Regeln", 0.92),
                              ]),
        ]
        tl1 = build_timeline_from_segments(segs)
        tl2 = build_timeline_from_segments(segs)
        # Word IDs and timestamps must be identical
        w1 = [(w.word_id, w.start_ms, w.end_ms) for w in tl1.alignment_runs[0].words]
        w2 = [(w.word_id, w.start_ms, w.end_ms) for w in tl2.alignment_runs[0].words]
        assert w1 == w2

    def test_remap_deterministic(self):
        words = [
            WordToken("w0", 0, "A", "a", 0, 500, 0.9),
            WordToken("w1", 1, "B", "b", 600, 1100, 0.9),
            WordToken("w2", 2, "C", "c", 1200, 1700, 0.9),
        ]
        first_result_start = None
        first_result_end = None
        for _ in range(5):
            timeline = WordTimeline(
                alignment_runs=[AlignmentRun(
                    run_id="r1", track_id="t1", window_start_ms=0, window_end_ms=1700,
                    model_provider="test", model_version="1", params_hash="h1",
                    words=list(words),
                )],
                segment_mappings=[
                    SegmentWordMapping(segment_id=0, word_ids=["w0", "w1"]),
                    SegmentWordMapping(segment_id=1, word_ids=["w2"]),
                ],
            )
            segments = [
                {"start": 0.0, "end": 1.1, "text": "A B", "words": [], "has_word_timestamps": False},
                {"start": 1.2, "end": 1.7, "text": "C", "words": [], "has_word_timestamps": False},
            ]
            result = process_segment_edit(segments, timeline, {
                0: "A",
                1: "B C",
            })
            assert result.action == "remap"
            if first_result_start is None:
                first_result_start = result.segments[0]["start"]
                first_result_end = result.segments[0]["end"]
            else:
                assert result.segments[0]["start"] == first_result_start
                assert result.segments[0]["end"] == first_result_end


# ── API Integration ──────────────────────────────────────────────────────────


class TestRemapAPI:
    """Test the remap-words API endpoint."""

    def _seed_job_with_words(self, storage_root):
        """Create a job with word timestamps for testing."""
        import src.api.tasks as tasks_mod
        from src.api.models import JobStatus
        from datetime import datetime, timezone

        job = tasks_mod.create_job("test_song.mp3")
        job_id = job.job_id
        job_dir = storage_root / "output" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        segments = [
            {"start": 0.0, "end": 2.0, "text": "Nur Meine Regeln",
             "confidence": 0.9, "has_word_timestamps": True, "words": [
                 {"start": 0.0, "end": 0.5, "word": "Nur", "confidence": 0.9},
                 {"start": 0.5, "end": 1.2, "word": "Meine", "confidence": 0.85},
                 {"start": 1.2, "end": 2.0, "word": "Regeln", "confidence": 0.92},
             ]},
            {"start": 2.1, "end": 4.0, "text": "Bleiben. Die",
             "confidence": 0.88, "has_word_timestamps": True, "words": [
                 {"start": 2.1, "end": 2.8, "word": "Bleiben.", "confidence": 0.88},
                 {"start": 2.9, "end": 4.0, "word": "Die", "confidence": 0.95},
             ]},
        ]

        seg_path = job_dir / "segments.json"
        seg_path.write_text(json.dumps(segments, indent=2), encoding="utf-8")
        srt_path = job_dir / "test_song.srt"
        srt_path.write_text("1\n00:00:00,000 --> 00:00:02,000\nNur Meine Regeln\n\n", encoding="utf-8")

        tasks_mod.update_job(job_id, status=JobStatus.completed,
                             completed_at=datetime.now(timezone.utc))
        return job_id, job_dir

    def test_build_timeline_endpoint(self, _patch_dirs, storage_root, client):
        job_id, _ = self._seed_job_with_words(storage_root)
        resp = client.post(f"/api/jobs/{job_id}/word-timeline/build")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "built"
        assert data["metrics"]["word_count"] == 5

    def test_get_timeline_endpoint(self, _patch_dirs, storage_root, client):
        job_id, _ = self._seed_job_with_words(storage_root)
        # Build first
        client.post(f"/api/jobs/{job_id}/word-timeline/build")
        # Then retrieve
        resp = client.get(f"/api/jobs/{job_id}/word-timeline")
        assert resp.status_code == 200
        assert "timeline" in resp.json()

    def test_get_timeline_404_when_missing(self, _patch_dirs, storage_root, client):
        job_id, _ = self._seed_job_with_words(storage_root)
        resp = client.get(f"/api/jobs/{job_id}/word-timeline")
        assert resp.status_code == 404

    def test_remap_endpoint(self, _patch_dirs, storage_root, client):
        job_id, _ = self._seed_job_with_words(storage_root)
        # Build timeline first
        client.post(f"/api/jobs/{job_id}/word-timeline/build")
        # Then remap
        resp = client.post(f"/api/jobs/{job_id}/segments/remap-words",
                           json={"0": "Nur Meine", "1": "Regeln Bleiben. Die"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "remap"

    def test_remap_with_new_word_returns_realign(self, _patch_dirs, storage_root, client):
        job_id, _ = self._seed_job_with_words(storage_root)
        client.post(f"/api/jobs/{job_id}/word-timeline/build")
        resp = client.post(f"/api/jobs/{job_id}/segments/remap-words",
                           json={"0": "Nur Meine NEUESWORT"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "realign_needed"
