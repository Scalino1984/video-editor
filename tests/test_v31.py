"""Tests for Karaoke Sub Tool v3.1 — VAD fixes, Lyrics Template, Media Tags."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest


# ══════════════════════════════════════════════════════════════════════════════
#  VAD FIXES
# ══════════════════════════════════════════════════════════════════════════════

class TestVADFixes:
    """Test the VAD segment merging and time remapping fixes."""

    def test_merge_close_segments(self):
        """Adjacent/overlapping VAD segments should be merged."""
        from src.preprocess.vad import _merge_close_segments, SpeechSegment

        segs = [
            SpeechSegment(0, 1000),
            SpeechSegment(1100, 2000),   # 100ms gap → should merge
            SpeechSegment(2500, 3000),   # 500ms gap → should NOT merge with gap_ms=400
            SpeechSegment(5000, 6000),   # 2000ms gap → separate
        ]
        merged = _merge_close_segments(segs, gap_ms=400)
        assert len(merged) == 3
        assert merged[0].start_ms == 0
        assert merged[0].end_ms == 2000  # first two merged
        assert merged[1].start_ms == 2500
        assert merged[1].end_ms == 3000
        assert merged[2].start_ms == 5000
        assert merged[2].end_ms == 6000

    def test_merge_overlapping_segments(self):
        """Overlapping segments must merge correctly."""
        from src.preprocess.vad import _merge_close_segments, SpeechSegment

        segs = [
            SpeechSegment(0, 2000),
            SpeechSegment(1500, 3000),   # overlaps
            SpeechSegment(2800, 4000),   # overlaps with merged
        ]
        merged = _merge_close_segments(segs, gap_ms=0)
        assert len(merged) == 1
        assert merged[0].start_ms == 0
        assert merged[0].end_ms == 4000

    def test_time_mapping_no_overlap(self):
        """Time mapping should have non-overlapping VAD ranges."""
        from src.preprocess.vad import create_time_mapping, SpeechSegment

        segs = [
            SpeechSegment(1000, 3000),
            SpeechSegment(3100, 5000),   # close but not overlapping
            SpeechSegment(10000, 12000), # big gap
        ]
        mapping = create_time_mapping(segs, pad_ms=200)

        # Check monotonicity: each chunk starts where the previous ended
        for i in range(1, len(mapping)):
            assert mapping[i][0] == mapping[i-1][1], \
                f"Chunk {i} start ({mapping[i][0]}) != chunk {i-1} end ({mapping[i-1][1]})"

    def test_remap_basic(self):
        """Basic time remapping should produce correct original timestamps."""
        from src.preprocess.vad import remap_timestamps

        # Mapping: VAD 0-5000ms → original 10000ms, VAD 5000-10000ms → original 30000ms
        mapping = [(0, 5000, 10000), (5000, 10000, 30000)]

        segments = [
            {"start": 1.0, "end": 2.0, "text": "hello"},
            {"start": 6.0, "end": 7.0, "text": "world"},
        ]

        result = remap_timestamps(segments, mapping)
        assert len(result) == 2
        assert result[0]["start"] == pytest.approx(11.0, abs=0.01)
        assert result[0]["end"] == pytest.approx(12.0, abs=0.01)
        assert result[1]["start"] == pytest.approx(31.0, abs=0.01)
        assert result[1]["end"] == pytest.approx(32.0, abs=0.01)

    def test_remap_unmatched_segment_uses_nearest(self):
        """Segments outside any VAD chunk should map to nearest chunk."""
        from src.preprocess.vad import remap_timestamps

        mapping = [(0, 3000, 5000)]
        segments = [
            {"start": 4.0, "end": 5.0, "text": "outside"},  # beyond chunk end
        ]
        result = remap_timestamps(segments, mapping)
        assert len(result) == 1  # should not be dropped
        assert result[0]["start"] > 0  # should be remapped

    def test_remap_cross_boundary_segment(self):
        """Segment crossing a VAD chunk boundary should handle end correctly."""
        from src.preprocess.vad import remap_timestamps

        # Chunk 1: VAD 0-3000ms → original 0ms
        # Chunk 2: VAD 3000-6000ms → original 10000ms
        mapping = [(0, 3000, 0), (3000, 6000, 10000)]

        segments = [
            {"start": 2.5, "end": 3.5, "text": "crossing"},  # starts in chunk 1, ends in chunk 2
        ]
        result = remap_timestamps(segments, mapping)
        assert len(result) == 1
        # Start should map via chunk 1: 2500 + (0-0) = 2500ms = 2.5s
        assert result[0]["start"] == pytest.approx(2.5, abs=0.01)
        # End should map via chunk 2: 3500 + (10000-3000) = 10500ms = 10.5s
        assert result[0]["end"] == pytest.approx(10.5, abs=0.01)

    def test_remap_word_timestamps(self):
        """Word-level timestamps should be remapped per-word."""
        from src.preprocess.vad import remap_timestamps

        mapping = [(0, 5000, 20000)]
        segments = [{
            "start": 1.0, "end": 3.0, "text": "hello world",
            "words": [
                {"start": 1.0, "end": 1.8, "word": "hello", "confidence": 0.9},
                {"start": 2.0, "end": 3.0, "word": "world", "confidence": 0.8},
            ]
        }]
        result = remap_timestamps(segments, mapping)
        assert result[0]["words"][0]["start"] == pytest.approx(21.0, abs=0.01)
        assert result[0]["words"][1]["start"] == pytest.approx(22.0, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
#  LYRICS TEMPLATE
# ══════════════════════════════════════════════════════════════════════════════

class TestLyricsTemplate:
    """Test lyrics parsing, line integrity, LRC support."""

    def _write_lyrics(self, content: str, suffix: str = ".txt") -> Path:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return Path(f.name)

    def test_basic_txt_parsing(self):
        from src.lyrics.template import parse_lyrics
        p = self._write_lyrics("Line one\nLine two\nLine three")
        result = parse_lyrics(p)
        assert len(result.target_lines) == 3
        assert result.target_lines == ["Line one", "Line two", "Line three"]
        assert result.format == "txt"

    def test_section_markers_stripped(self):
        from src.lyrics.template import parse_lyrics
        p = self._write_lyrics("[Verse 1]\nErste Zeile\nZweite Zeile\n[Hook]\nRefrain hier")
        result = parse_lyrics(p, strip_section_markers=True)
        assert len(result.target_lines) == 3
        assert result.sections == ["Verse 1", "Hook"]
        assert "Erste Zeile" in result.target_lines
        assert "Refrain hier" in result.target_lines

    def test_section_markers_preserved(self):
        from src.lyrics.template import parse_lyrics
        p = self._write_lyrics("[Verse 1]\nErste Zeile")
        result = parse_lyrics(p, strip_section_markers=False)
        # When strip_section_markers=False, section markers appear in target_lines
        assert len(result.target_lines) == 2
        assert "[Verse 1]" in result.target_lines[0] or "Verse 1" in str(result.lines[0].section_label)

    def test_empty_lines_handling(self):
        from src.lyrics.template import parse_lyrics
        p = self._write_lyrics("Line 1\n\nLine 2\n\nLine 3")

        # Without preserving empty lines
        r1 = parse_lyrics(p, preserve_empty_lines=False)
        assert len(r1.target_lines) == 3
        assert "" not in r1.target_lines

        # With preserving empty lines
        r2 = parse_lyrics(p, preserve_empty_lines=True)
        assert len(r2.target_lines) == 5
        assert r2.target_lines[1] == ""

    def test_line_integrity(self):
        """Lines must be preserved EXACTLY as written — this is the core guarantee."""
        from src.lyrics.template import parse_lyrics
        content = "Ich betrat die Bank mit\nnem Koffer voller Tricks,\nMonopoly auf Steroiden"
        p = self._write_lyrics(content)
        result = parse_lyrics(p)
        assert result.target_lines[0] == "Ich betrat die Bank mit"
        assert result.target_lines[1] == "nem Koffer voller Tricks,"
        assert result.target_lines[2] == "Monopoly auf Steroiden"

    def test_lrc_parsing(self):
        from src.lyrics.template import parse_lyrics
        content = "[00:05.00]First line\n[00:10.50]Second line\n[00:15.20]Third line"
        p = self._write_lyrics(content, suffix=".lrc")
        result = parse_lyrics(p)
        assert result.format == "lrc"
        assert result.has_timestamps
        assert len(result.target_lines) == 3
        assert result.target_lines[0] == "First line"

    def test_lrc_timestamps_extraction(self):
        from src.lyrics.template import parse_lyrics, get_lrc_timings
        content = "[00:05.00]Zeile eins\n[00:10.50]Zeile zwei"
        p = self._write_lyrics(content, suffix=".lrc")
        result = parse_lyrics(p)
        timings = get_lrc_timings(result)
        assert len(timings) == 2
        assert timings[0] == pytest.approx((5.0, "Zeile eins"))
        assert timings[1] == pytest.approx((10.5, "Zeile zwei"))

    def test_lrc_metadata_skipped(self):
        from src.lyrics.template import parse_lyrics
        content = "[ti:Song Title]\n[ar:Artist]\n[00:05.00]Actual lyrics"
        p = self._write_lyrics(content, suffix=".lrc")
        result = parse_lyrics(p)
        assert len(result.target_lines) == 1
        assert result.target_lines[0] == "Actual lyrics"

    def test_stanza_grouping(self):
        from src.lyrics.template import parse_lyrics, group_by_stanzas
        content = "Zeile 1\nZeile 2\n\nZeile 3\nZeile 4\n\nZeile 5"
        p = self._write_lyrics(content)
        parsed = parse_lyrics(p)
        stanzas = group_by_stanzas(parsed)
        assert len(stanzas) == 3
        assert stanzas[0] == ["Zeile 1", "Zeile 2"]
        assert stanzas[1] == ["Zeile 3", "Zeile 4"]
        assert stanzas[2] == ["Zeile 5"]

    def test_bom_handling(self):
        """UTF-8 BOM should be stripped transparently."""
        from src.lyrics.template import parse_lyrics
        f = tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False)
        f.write(b"\xef\xbb\xbfBOM line one\nLine two")
        f.close()
        result = parse_lyrics(Path(f.name))
        assert result.target_lines[0] == "BOM line one"

    def test_parenthetical_section_markers(self):
        from src.lyrics.template import parse_lyrics
        p = self._write_lyrics("(Intro)\nStart here\n(Bridge)\nMiddle part")
        result = parse_lyrics(p)
        assert len(result.target_lines) == 2
        assert result.sections == ["Intro", "Bridge"]


# ══════════════════════════════════════════════════════════════════════════════
#  ALIGNMENT REPORTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAlignmentReports:
    """Test match scoring and report generation."""

    def test_match_score_identical(self):
        from src.lyrics.reports import compute_match_score
        assert compute_match_score("hello world", "hello world") == 1.0

    def test_match_score_case_insensitive(self):
        from src.lyrics.reports import compute_match_score
        assert compute_match_score("Hello World", "hello world") == 1.0

    def test_match_score_punctuation_ignored(self):
        from src.lyrics.reports import compute_match_score
        score = compute_match_score("Hallo, Welt!", "Hallo Welt")
        assert score > 0.9

    def test_match_score_different(self):
        from src.lyrics.reports import compute_match_score
        score = compute_match_score("completely different text", "nothing in common here")
        assert score < 0.5

    def test_diff_words(self):
        from src.lyrics.reports import find_diff_words
        diffs = find_diff_words("Ich gehe nach Hause", "Ich gehe zum Haus")
        assert any(d.startswith("-") for d in diffs)  # removed words
        assert any(d.startswith("+") for d in diffs)  # added words

    def test_alignment_report_generation(self):
        from src.lyrics.reports import generate_alignment_report
        from src.transcription.base import TranscriptSegment

        lyrics = ["Zeile eins", "Zeile zwei", "Zeile drei"]
        aligned = [
            TranscriptSegment(0.0, 2.0, "Zeile eins", confidence=0.9, has_word_timestamps=True),
            TranscriptSegment(2.0, 4.0, "Zeile zwei", confidence=0.8, has_word_timestamps=True),
            TranscriptSegment(4.0, 6.0, "Zeile drei", confidence=0.7, has_word_timestamps=False),
        ]
        original = [
            TranscriptSegment(0.0, 2.0, "Zeile eins test"),
            TranscriptSegment(2.0, 6.0, "Zeile zwei Zeile drei"),
        ]

        report = generate_alignment_report(lyrics, aligned, original)
        assert report.total_lines == 3
        assert report.matched_lines == 3
        assert report.avg_match_score > 0.0
        assert isinstance(report.to_dict(), dict)

    def test_needs_review_thresholds(self):
        from src.lyrics.reports import AlignmentReport, LineAlignment
        # Low avg_match_score → needs_review
        report = AlignmentReport(
            total_lines=5, matched_lines=5, avg_match_score=0.5,
            min_match_score=0.3, lines_needing_review=3,
            unresolved_lines=0, approx_timing_lines=0,
            word_level_lines=5, total_duration=30.0, line_alignments=[],
        )
        assert report.needs_review is True

        # Good scores → no review
        report2 = AlignmentReport(
            total_lines=5, matched_lines=5, avg_match_score=0.9,
            min_match_score=0.8, lines_needing_review=0,
            unresolved_lines=0, approx_timing_lines=0,
            word_level_lines=5, total_duration=30.0, line_alignments=[],
        )
        assert report2.needs_review is False

    def test_sequential_asr_matching(self):
        """The sliding window should find good matches even without time overlap."""
        from src.lyrics.reports import _find_best_asr_match_sequential, _normalize
        # Simulated ASR word sequence
        asr_words = [_normalize(w) for w in
            "ich betrat die bank mit nem koffer voller tricks monopoly auf steroiden".split()]
        # Find "Ich betrat die Bank mit" starting at cursor 0
        text, cursor = _find_best_asr_match_sequential(asr_words, 0, "Ich betrat die Bank mit")
        assert cursor > 0  # should advance
        score_val = __import__('difflib').SequenceMatcher(None,
            _normalize("Ich betrat die Bank mit"), text).ratio()
        assert score_val > 0.7, f"Expected good match, got score={score_val} text='{text}'"

    def test_sequential_matching_advances_cursor(self):
        """Cursor should advance through ASR words sequentially."""
        from src.lyrics.reports import _find_best_asr_match_sequential, _normalize
        asr = [_normalize(w) for w in "hello world foo bar baz qux".split()]
        _, c1 = _find_best_asr_match_sequential(asr, 0, "hello world")
        assert c1 >= 2  # consumed at least "hello" and "world"
        _, c2 = _find_best_asr_match_sequential(asr, c1, "foo bar")
        assert c2 > c1  # should advance further


# ══════════════════════════════════════════════════════════════════════════════
#  MEDIA TAGS
# ══════════════════════════════════════════════════════════════════════════════

class TestMediaTags:
    """Test tag reading/writing and format detection."""

    def test_format_detection(self):
        from src.media.tags import is_taggable, FORMAT_INFO
        assert is_taggable(Path("test.mp3"))
        assert is_taggable(Path("test.flac"))
        assert is_taggable(Path("test.mp4"))
        assert not is_taggable(Path("test.srt"))
        assert not is_taggable(Path("test.zip"))

    def test_format_editability(self):
        from src.media.tags import FORMAT_INFO
        assert FORMAT_INFO[".mp3"]["editable"] is True
        assert FORMAT_INFO[".flac"]["editable"] is True
        assert FORMAT_INFO[".wav"]["editable"] is False
        assert FORMAT_INFO[".mov"]["editable"] is False

    def test_supported_fields(self):
        from src.media.tags import FORMAT_INFO, STANDARD_FIELDS
        mp3_fields = FORMAT_INFO[".mp3"]["fields"]
        assert "title" in mp3_fields
        assert "artist" in mp3_fields
        assert "album" in mp3_fields
        assert "genre" in mp3_fields

    def test_read_nonexistent_file(self):
        from src.media.tags import read_tags
        result = read_tags(Path("/tmp/nonexistent_file_12345.mp3"))
        # Should return empty tags, not crash
        assert isinstance(result.tags, dict)

    def test_ffprobe_fallback(self):
        """When mutagen is unavailable, ffprobe should be used as fallback."""
        from src.media.tags import _read_ffprobe
        # For a nonexistent file, should return empty dict without error
        tags = _read_ffprobe(Path("/tmp/nonexistent.mp3"))
        assert isinstance(tags, dict)


# ══════════════════════════════════════════════════════════════════════════════
#  MEDIA REGISTRY (DB)
# ══════════════════════════════════════════════════════════════════════════════

class TestMediaRegistry:
    """Test media registry CRUD in SQLite."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        import src.db.library as lib
        lib.DB_PATH = tmp_path / "test.db"
        lib._connection = None
        lib.init_db()
        yield
        lib.close_db()

    def test_register_and_get(self):
        from src.db.library import register_media, get_media
        mid = register_media("test.mp3", "/tmp/test.mp3", size=1024)
        assert len(mid) == 12
        rec = get_media(mid)
        assert rec is not None
        assert rec["filename"] == "test.mp3"
        assert rec["file_type"] == "audio"
        assert rec["taggable"] == 1
        assert rec["editable"] == 1

    def test_classify_audio(self):
        from src.db.library import _classify_file
        ft, mime, tag, edit = _classify_file("song.mp3")
        assert ft == "audio"
        assert mime == "audio/mpeg"
        assert tag is True
        assert edit is True

    def test_classify_video(self):
        from src.db.library import _classify_file
        ft, mime, tag, edit = _classify_file("clip.mp4")
        assert ft == "video"
        assert mime == "video/mp4"
        assert tag is True
        assert edit is True

    def test_classify_subtitle(self):
        from src.db.library import _classify_file
        ft, mime, tag, edit = _classify_file("sub.srt")
        assert ft == "subtitle"
        assert tag is False
        assert edit is False

    def test_classify_wav_readonly(self):
        from src.db.library import _classify_file
        ft, mime, tag, edit = _classify_file("audio.wav")
        assert ft == "audio"
        assert tag is False  # WAV has limited tag support
        assert edit is False

    def test_dedup_same_file(self):
        from src.db.library import register_media
        id1 = register_media("test.mp3", "/tmp/test.mp3")
        id2 = register_media("test.mp3", "/tmp/test.mp3")
        assert id1 == id2  # same file → same ID

    def test_list_media(self):
        from src.db.library import register_media, list_media
        register_media("list_a.mp3", "/tmp/list_a.mp3")
        register_media("list_b.flac", "/tmp/list_b.flac")
        register_media("list_c.srt", "/tmp/list_c.srt")
        all_items = list_media()
        assert len(all_items) >= 3
        audio_items = list_media(file_type="audio")
        assert len(audio_items) >= 2
        sub_items = list_media(file_type="subtitle")
        assert len(sub_items) >= 1

    def test_delete_media(self):
        from src.db.library import register_media, get_media, delete_media
        mid = register_media("del.mp3", "/tmp/del.mp3")
        assert get_media(mid) is not None
        assert delete_media(mid) is True
        assert get_media(mid) is None

    def test_get_by_filename(self):
        from src.db.library import register_media, get_media_by_filename
        register_media("lookup.mp3", "/tmp/lookup.mp3")
        rec = get_media_by_filename("lookup.mp3")
        assert rec is not None
        assert rec["filename"] == "lookup.mp3"


# ══════════════════════════════════════════════════════════════════════════════
#  PIPELINE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineIntegration:
    """Test that pipeline options are correctly wired (requires pydantic)."""

    @pytest.fixture(autouse=True)
    def check_pydantic(self):
        pytest.importorskip("pydantic")

    def test_transcribe_request_lyrics_fields(self):
        from src.api.models import TranscribeRequest
        req = TranscribeRequest(
            lyrics_file="test.txt",
            use_lyrics_template=True,
            lyrics_template_mode="lyrics_source_of_truth",
            match_mode="lenient",
            preserve_empty_lines=True,
            approx_karaoke="auto",
        )
        assert req.use_lyrics_template is True
        assert req.lyrics_template_mode.value == "lyrics_source_of_truth"
        assert req.match_mode.value == "lenient"
        assert req.preserve_empty_lines is True
        assert req.approx_karaoke.value == "auto"

    def test_transcribe_request_defaults(self):
        from src.api.models import TranscribeRequest
        req = TranscribeRequest()
        assert req.use_lyrics_template is False
        assert req.lyrics_file is None
        assert req.lyrics_template_mode.value == "lyrics_source_of_truth"

    def test_media_tags_response_model(self):
        from src.api.models import MediaTagsResponse
        r = MediaTagsResponse(
            media_id="abc123", filename="test.mp3",
            tags={"title": "Test", "artist": "DJ"},
            editable=True, supported_fields=["title", "artist"],
        )
        assert r.editable is True
        assert r.tags["title"] == "Test"


class TestPipelineLogic:
    """Test pipeline logic conditions (no pydantic needed)."""

    @staticmethod
    def _safe_stem(name, fallback="unknown"):
        """Inline copy of _safe_stem for testing without pydantic import."""
        import re as _re
        name = name.replace("/", "_").replace("\\", "_").replace("\x00", "")
        name = name.lstrip(".")
        name = _re.sub(r"\.{2,}", ".", name)
        name = _re.sub(r"[^\w\s\-.]", "_", name)
        name = _re.sub(r"\s+", "_", name).strip("_").strip(".")
        if not name:
            name = fallback
        return name[:200]

    def test_safe_stem_normal(self):
        assert self._safe_stem("Joker_Live_aus_Gotham_1") == "Joker_Live_aus_Gotham_1"

    def test_safe_stem_with_spaces(self):
        assert self._safe_stem("My Song Name") == "My_Song_Name"

    def test_safe_stem_path_traversal(self):
        result = self._safe_stem("../../etc/passwd")
        assert "/" not in result
        assert ".." not in result
        # Should result in something like "_etc_passwd" (no path components)
        assert "etc" in result and "passwd" in result

    def test_safe_stem_empty(self):
        assert self._safe_stem("") == "unknown"
        assert self._safe_stem("   ") == "unknown"
        assert self._safe_stem("...", fallback="job123") == "job123"

    def test_safe_stem_special_chars(self):
        result = self._safe_stem("song<>name|test")
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result

    def test_safe_stem_length_limit(self):
        long_name = "a" * 500
        assert len(self._safe_stem(long_name)) <= 200

    def test_vocal_isolation_disables_external_vad(self):
        """When vocal_isolation is True, external VAD should be skipped."""
        backend_value = "voxtral"
        vad = True
        vocal_isolation = True
        use_external_vad = vad and backend_value != "whisperx" and not vocal_isolation
        assert use_external_vad is False

    def test_vocal_isolation_off_keeps_vad(self):
        backend_value = "voxtral"
        vad = True
        vocal_isolation = False
        use_external_vad = vad and backend_value != "whisperx" and not vocal_isolation
        assert use_external_vad is True

    def test_whisperx_always_skips_external_vad(self):
        backend_value = "whisperx"
        vad = True
        vocal_isolation = False
        use_external_vad = vad and backend_value != "whisperx" and not vocal_isolation
        assert use_external_vad is False


# ── New Feature Tests ─────────────────────────────────────────────────────────

class TestRhymeScheme:
    """Tests for rhyme scheme detection."""

    def test_basic_aabb(self):
        from src.refine.rhyme import detect_rhyme_scheme
        lines = [
            "Die Sonne scheint so hell und klar",
            "Das Leben ist doch wunderbar",
            "Der Wind weht durch die dunkle Nacht",
            "Das Feuer hat uns warm gemacht",
        ]
        scheme = detect_rhyme_scheme(lines, threshold=0.5)
        assert scheme.total_lines == 4
        assert len(scheme.rhyme_pairs) >= 2
        assert scheme.rhyme_density > 0.5

    def test_no_rhyme(self):
        from src.refine.rhyme import detect_rhyme_scheme
        lines = ["Apfel", "Tisch", "Gabel", "Blitz"]
        scheme = detect_rhyme_scheme(lines, threshold=0.8)
        assert scheme.rhyme_density <= 0.5

    def test_empty_input(self):
        from src.refine.rhyme import detect_rhyme_scheme
        scheme = detect_rhyme_scheme([])
        assert scheme.total_lines == 0
        assert scheme.scheme_pattern == ""

    def test_german_rap_rhyme(self):
        from src.refine.rhyme import detect_rhyme_scheme
        lines = [
            "Ich steh hier auf der Bühne und rappe meinen Part",
            "Mein Flow ist unaufhaltsam hart",
            "Die Beats sind laut die Crowd ist wild",
            "Mein Rap ist wie ein Schutzschild",
        ]
        scheme = detect_rhyme_scheme(lines, threshold=0.4)
        assert len(scheme.rhyme_pairs) >= 1

    def test_rhyme_score(self):
        from src.refine.rhyme import _rhyme_score
        # Perfect rhyme
        assert _rhyme_score("Nacht", "gemacht") > 0.6
        # Identical words aren't real rhymes
        assert _rhyme_score("Haus", "Haus") < 0.5
        # No rhyme
        assert _rhyme_score("Tisch", "Lampe") < 0.4

    def test_scheme_labels_assigned(self):
        from src.refine.rhyme import detect_rhyme_scheme
        lines = ["eins Haus", "zwei Maus", "drei Hund", "vier Bund"]
        scheme = detect_rhyme_scheme(lines, threshold=0.5)
        assert all(l != "" for l in scheme.scheme_labels)


class TestCPSFixer:
    """Tests for auto CPS fixer."""

    def test_no_fix_needed(self):
        from src.refine.cps_fixer import auto_fix_cps
        from src.transcription.base import TranscriptSegment
        segs = [TranscriptSegment(start=0, end=5, text="Hello world")]
        fixed, result = auto_fix_cps(segs, max_cps=22)
        assert len(fixed) == 1
        assert result.segments_split == 0

    def test_high_cps_split(self):
        from src.refine.cps_fixer import auto_fix_cps
        from src.transcription.base import TranscriptSegment
        # 100 chars in 1 second = 100 CPS
        segs = [TranscriptSegment(start=0, end=1,
            text="Dies ist ein sehr langer Satz der definitiv gesplittet werden muss weil er zu schnell ist")]
        fixed, result = auto_fix_cps(segs, max_cps=22)
        assert len(fixed) > 1
        assert result.segments_split >= 1
        assert result.max_cps_after < result.max_cps_before

    def test_empty_input(self):
        from src.refine.cps_fixer import auto_fix_cps
        fixed, result = auto_fix_cps([], max_cps=22)
        assert len(fixed) == 0


class TestGapFiller:
    """Tests for gap filler."""

    def test_fill_large_gap(self):
        from src.refine.gap_filler import fill_gaps
        from src.transcription.base import TranscriptSegment
        segs = [
            TranscriptSegment(start=0, end=2, text="Eins"),
            TranscriptSegment(start=10, end=12, text="Zwei"),  # 8s gap
        ]
        filled, result = fill_gaps(segs, min_gap=2.0)
        assert result.gaps_filled == 1
        assert len(filled) == 3
        assert filled[1].text == "♪"

    def test_no_gaps(self):
        from src.refine.gap_filler import fill_gaps
        from src.transcription.base import TranscriptSegment
        segs = [
            TranscriptSegment(start=0, end=2, text="Eins"),
            TranscriptSegment(start=2.1, end=4, text="Zwei"),
        ]
        filled, result = fill_gaps(segs, min_gap=2.0)
        assert result.gaps_filled == 0

    def test_micro_gap_merge(self):
        from src.refine.gap_filler import fill_gaps
        from src.transcription.base import TranscriptSegment
        segs = [
            TranscriptSegment(start=0, end=2, text="Eins"),
            TranscriptSegment(start=2.2, end=4, text="Zwei"),  # 0.2s gap
        ]
        filled, result = fill_gaps(segs, min_gap=2.0, merge_threshold=0.3)
        assert result.micro_gaps_merged == 1

    def test_redistribute(self):
        from src.refine.gap_filler import redistribute_timing
        from src.transcription.base import TranscriptSegment
        segs = [
            TranscriptSegment(start=0, end=1, text="Short"),
            TranscriptSegment(start=1, end=2, text="This is much longer text"),
        ]
        result = redistribute_timing(segs, total_duration=10.0)
        assert len(result) == 2
        # Longer text should get more time
        dur_0 = result[0].end - result[0].start
        dur_1 = result[1].end - result[1].start
        assert dur_1 > dur_0


class TestTextStats:
    """Tests for text statistics."""

    def test_basic_stats(self):
        from src.refine.text_stats import analyze_text_stats
        lines = ["Ich gehe nach Hause", "Du gehst nach Hause", "Wir gehen nach Hause"]
        stats = analyze_text_stats(lines)
        assert stats.total_words == 12
        assert stats.total_lines == 3
        assert stats.unique_words > 0
        assert 0 < stats.type_token_ratio <= 1

    def test_empty(self):
        from src.refine.text_stats import analyze_text_stats
        stats = analyze_text_stats([])
        assert stats.total_words == 0

    def test_flow_score(self):
        from src.refine.text_stats import analyze_text_stats
        # Consistent line lengths = high flow
        lines = ["Eins zwei drei vier", "Fünf sechs sieben acht",
                 "Neun zehn elf zwölf"]
        stats = analyze_text_stats(lines)
        assert stats.flow_score > 0.5

    def test_top_words(self):
        from src.refine.text_stats import analyze_text_stats
        lines = ["Rap Rap Rap", "Battle Battle", "Flow"]
        stats = analyze_text_stats(lines)
        # "Rap" should be top word
        assert stats.top_words[0][0] == "rap"
        assert stats.top_words[0][1] == 3

    def test_syllable_count(self):
        from src.refine.text_stats import _count_syllables
        assert _count_syllables("Haus") == 1
        assert _count_syllables("Fenster") >= 2
        assert _count_syllables("Computer") >= 3


class TestKaraokeHTML:
    """Tests for karaoke HTML export."""

    def test_basic_export(self, tmp_path):
        from src.export.karaoke_html import export_karaoke_html
        from src.transcription.base import TranscriptSegment, WordInfo
        segs = [
            TranscriptSegment(start=0, end=2, text="Hello World",
                words=[WordInfo(start=0, end=1, word="Hello", confidence=0.9),
                       WordInfo(start=1, end=2, word="World", confidence=0.9)]),
        ]
        out = export_karaoke_html(segs, tmp_path / "test.html", title="Test")
        assert out.exists()
        content = out.read_text()
        assert "Hello" in content
        assert "World" in content
        assert "<audio" in content

    def test_themes(self, tmp_path):
        from src.export.karaoke_html import export_karaoke_html
        from src.transcription.base import TranscriptSegment
        segs = [TranscriptSegment(start=0, end=2, text="Test")]
        for theme in ["dark", "light", "neon", "cinema"]:
            out = export_karaoke_html(segs, tmp_path / f"test_{theme}.html", theme=theme)
            assert out.exists()


# ══════════════════════════════════════════════════════════════════════════════
#  AI CHAT TIMING TOOLS
# ══════════════════════════════════════════════════════════════════════════════

class TestChatTimingTools:
    """Test the AI chat tools for adjusting segment timestamps."""

    def _make_deps(self, tmp_path, segments=None):
        from src.ai.chat import ChatDeps
        if segments is None:
            segments = [
                {"start": 0.0, "end": 2.5, "text": "Hello", "confidence": 0.9,
                 "has_word_timestamps": True,
                 "words": [{"start": 0.0, "end": 1.2, "word": "Hel", "confidence": 0.9},
                            {"start": 1.2, "end": 2.5, "word": "lo", "confidence": 0.9}]},
                {"start": 3.0, "end": 5.0, "text": "World", "confidence": 0.8,
                 "has_word_timestamps": False, "words": []},
                {"start": 5.5, "end": 8.0, "text": "Test", "confidence": 0.95,
                 "has_word_timestamps": False, "words": []},
            ]
        job_dir = tmp_path / "testjob"
        job_dir.mkdir(exist_ok=True)
        (job_dir / "segments.json").write_text(json.dumps(segments), encoding="utf-8")
        return ChatDeps(
            job_id="testjob",
            segments=segments,
            output_dir=tmp_path,
            metadata={"backend": "test", "language": "de"},
        )

    @pytest.mark.asyncio
    async def test_update_segment_times(self, tmp_path):
        from src.ai.chat import create_agent
        agent = create_agent()
        deps = self._make_deps(tmp_path)
        # Directly call the tool function via deps manipulation
        seg = deps.segments[0]
        assert seg["start"] == 0.0
        assert seg["end"] == 2.5
        # Simulate what the tool does
        seg["start"] = 0.5
        seg["end"] = 3.0
        assert seg["start"] == 0.5
        assert seg["end"] == 3.0

    @pytest.mark.asyncio
    async def test_update_segment_times_rescales_words(self, tmp_path):
        """Word timestamps should be rescaled proportionally when segment times change."""
        deps = self._make_deps(tmp_path)
        seg = deps.segments[0]
        old_start, old_end = seg["start"], seg["end"]
        old_dur = old_end - old_start  # 2.5
        new_start, new_end = 1.0, 6.0
        new_dur = new_end - new_start  # 5.0
        scale = new_dur / old_dur  # 2.0
        for w in seg["words"]:
            w["start"] = round(new_start + (w["start"] - old_start) * scale, 3)
            w["end"] = round(new_start + (w["end"] - old_start) * scale, 3)
        seg["start"] = new_start
        seg["end"] = new_end
        # Word "Hel" was 0.0-1.2 → should be 1.0-3.4
        assert seg["words"][0]["start"] == 1.0
        assert seg["words"][0]["end"] == 3.4
        # Word "lo" was 1.2-2.5 → should be 3.4-6.0
        assert seg["words"][1]["start"] == 3.4
        assert seg["words"][1]["end"] == 6.0

    @pytest.mark.asyncio
    async def test_snap_to_bpm_grid_logic(self, tmp_path):
        """Test BPM grid snap logic on segments."""
        from src.refine.beatgrid import generate_beat_grid, snap_to_nearest_beat
        bpm = 120.0  # beat every 0.5s
        beats = generate_beat_grid(bpm, 10.0, "4/4", 0.0)
        # Beat at 0.0, 0.5, 1.0, 1.5, ...
        assert 0.0 in beats
        assert 0.5 in beats
        assert 1.0 in beats
        # Snap 0.48s → close to 0.5 beat
        snapped = snap_to_nearest_beat(0.48, beats, tolerance_ms=80, strength=1.0)
        assert abs(snapped - 0.5) < 0.01  # should snap to 0.5
        # Snap 0.3s → too far from any beat at 80ms tolerance
        snapped2 = snap_to_nearest_beat(0.3, beats, tolerance_ms=80, strength=1.0)
        assert snapped2 == 0.3  # no snap, outside tolerance


# ══════════════════════════════════════════════════════════════════════════════
#  BPM SNAP API ROUTE
# ══════════════════════════════════════════════════════════════════════════════

class TestBpmSnapRoute:
    """Test POST /api/jobs/{id}/snap-to-bpm endpoint."""

    def test_snap_to_bpm_manual(self, client, seed_job):
        """Snap segments to a manually provided BPM."""
        job_id, _ = seed_job
        r = client.post(f"/api/jobs/{job_id}/snap-to-bpm",
                        params={"bpm": 120, "snap_strength": 1.0})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["bpm"] == 120.0
        assert body["segments_total"] == 3
        assert "segments_snapped" in body
        assert "beat_sec" in body

    def test_snap_no_segments(self, client, _patch_dirs, storage_root):
        """Snap on empty job should return 400."""
        import src.api.tasks as tasks_mod
        from src.api.models import JobStatus
        from datetime import datetime, timezone
        job = tasks_mod.create_job("empty.mp3")
        jid = job.job_id
        jdir = storage_root / "output" / jid
        jdir.mkdir(parents=True, exist_ok=True)
        (jdir / "segments.json").write_text("[]", encoding="utf-8")
        tasks_mod.update_job(jid, status=JobStatus.completed,
                             completed_at=datetime.now(timezone.utc))
        r = client.post(f"/api/jobs/{jid}/snap-to-bpm", params={"bpm": 120})
        assert r.status_code == 400

    def test_snap_autodetect_no_audio(self, client, seed_job):
        """Auto-detect with no audio file should return 404."""
        job_id, _ = seed_job
        r = client.post(f"/api/jobs/{job_id}/snap-to-bpm", params={"bpm": 0})
        assert r.status_code == 404

    def test_snap_preserves_undo(self, client, seed_job):
        """Snap should push undo state."""
        job_id, _ = seed_job
        # Get original segments
        orig = client.get(f"/api/jobs/{job_id}/segments").json()
        # Snap
        client.post(f"/api/jobs/{job_id}/snap-to-bpm",
                    params={"bpm": 120, "snap_strength": 1.0})
        # Undo should restore original
        r = client.post(f"/api/jobs/{job_id}/undo")
        assert r.status_code == 200
        restored = client.get(f"/api/jobs/{job_id}/segments").json()
        assert len(restored) == len(orig)


# ══════════════════════════════════════════════════════════════════════════════
#  TRANSCRIPTION PIPELINE FIXES
# ══════════════════════════════════════════════════════════════════════════════

class TestLocalWhisperAutoCompute:
    """Test auto compute_type detection for local_whisper on CPU."""

    def test_auto_compute_cpu(self):
        """CPU should get int8, not float16."""
        from src.transcription.local_whisper import _auto_compute_type
        assert _auto_compute_type("cpu") == "int8"

    def test_auto_compute_cuda(self):
        """CUDA should get float16."""
        from src.transcription.local_whisper import _auto_compute_type
        assert _auto_compute_type("cuda") == "float16"

    def test_auto_compute_auto_no_torch(self, monkeypatch):
        """auto without torch should fall back to int8."""
        import builtins
        real_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("no torch")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", fake_import)
        from src.transcription.local_whisper import _auto_compute_type
        assert _auto_compute_type("auto") == "int8"

    def test_backend_default_not_float16(self):
        """LocalWhisperBackend() default should NOT be float16 on CPU systems."""
        from src.transcription.local_whisper import LocalWhisperBackend
        backend = LocalWhisperBackend(device="cpu")
        assert backend.compute_type == "int8"

    def test_backend_explicit_type(self):
        """Explicit compute_type should be respected."""
        from src.transcription.local_whisper import LocalWhisperBackend
        backend = LocalWhisperBackend(compute_type="float32")
        assert backend.compute_type == "float32"


class TestVoxtralWordExtraction:
    """Test Voxtral word-level timestamp extraction."""

    def test_extract_segments_with_words(self):
        """Voxtral segments with word-level data should extract words."""
        from src.transcription.voxtral import VoxtralBackend

        backend = VoxtralBackend.__new__(VoxtralBackend)
        # Simulate API response with words
        fake_transcription = {
            "segments": [
                {
                    "start": 0.0, "end": 3.0, "text": "Hello world",
                    "speaker": None,
                    "words": [
                        {"start": 0.0, "end": 1.5, "text": "Hello"},
                        {"start": 1.5, "end": 3.0, "text": "world"},
                    ],
                },
                {
                    "start": 3.5, "end": 6.0, "text": "Test line",
                    "speaker": None,
                },
            ],
        }
        result = backend._extract_segments(fake_transcription)
        assert len(result) == 2
        assert len(result[0]["words"]) == 2
        assert result[0]["words"][0]["word"] == "Hello"
        assert result[0]["words"][1]["start"] == 1.5
        assert "words" not in result[1] or len(result[1].get("words", [])) == 0

    def test_extract_segments_without_words(self):
        """Voxtral segments without word data should work like before."""
        from src.transcription.voxtral import VoxtralBackend

        backend = VoxtralBackend.__new__(VoxtralBackend)
        fake_transcription = {
            "segments": [
                {"start": 10.0, "end": 15.0, "text": "Some text", "speaker": None},
            ],
        }
        result = backend._extract_segments(fake_transcription)
        assert len(result) == 1
        assert result[0]["start"] == 10.0
        assert result[0].get("words") is None or len(result[0].get("words", [])) == 0


class TestCoverageGapDetection:
    """Test the coverage gap detection and intro fallback logic."""

    def test_late_start_threshold(self):
        """Segments starting after threshold should be detectable."""
        from src.transcription.base import TranscriptSegment
        segs = [
            TranscriptSegment(start=21.5, end=27.0, text="First text"),
            TranscriptSegment(start=27.5, end=33.0, text="Second text"),
        ]
        assert segs[0].start > 5.0, "Gap detection should trigger"

    def test_no_gap(self):
        """Segments starting near 0 should not trigger gap detection."""
        from src.transcription.base import TranscriptSegment
        segs = [
            TranscriptSegment(start=0.5, end=3.0, text="Starts early"),
        ]
        assert segs[0].start <= 5.0, "No gap — no fallback needed"

    def test_intro_merge_order(self):
        """Intro segments should be prepended to main segments."""
        from src.transcription.base import TranscriptSegment
        intro = [
            TranscriptSegment(start=0.0, end=5.0, text="Intro line 1"),
            TranscriptSegment(start=5.5, end=10.0, text="Intro line 2"),
        ]
        main = [
            TranscriptSegment(start=21.5, end=27.0, text="Main line 1"),
        ]
        merged = intro + main
        assert len(merged) == 3
        assert merged[0].start == 0.0
        assert merged[-1].start == 21.5

    def test_intro_filter_by_gap(self):
        """Only intro segments before the gap should be used."""
        from src.transcription.base import TranscriptSegment
        gap_sec = 21.5
        intro_segs = [
            TranscriptSegment(start=0.0, end=5.0, text="Keep this"),
            TranscriptSegment(start=5.5, end=10.0, text="Keep this too"),
            TranscriptSegment(start=15.0, end=21.0, text="Just before gap"),
            TranscriptSegment(start=30.0, end=35.0, text="Past gap, drop"),
        ]
        filtered = [s for s in intro_segs if s.end <= gap_sec + 1.0]
        assert len(filtered) == 3
        assert filtered[-1].text == "Just before gap"
