"""Tests for editor render pipeline: subtitle lifecycle, karaoke tags, logging."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


# ── Helper factories ──────────────────────────────────────────────────────────

def _make_segments(with_words: bool = True) -> list:
    """Create test TranscriptSegment objects."""
    from src.transcription.base import TranscriptSegment, WordInfo

    if with_words:
        return [
            TranscriptSegment(
                start=0.0, end=2.0, text="Hallo Welt",
                confidence=0.95, has_word_timestamps=True,
                words=[
                    WordInfo(start=0.0, end=0.8, word="Hallo", confidence=0.9),
                    WordInfo(start=0.9, end=2.0, word="Welt", confidence=0.95),
                ],
            ),
            TranscriptSegment(
                start=2.5, end=5.0, text="Zweite Zeile hier",
                confidence=0.9, has_word_timestamps=True,
                words=[
                    WordInfo(start=2.5, end=3.0, word="Zweite", confidence=0.9),
                    WordInfo(start=3.1, end=3.8, word="Zeile", confidence=0.85),
                    WordInfo(start=3.9, end=5.0, word="hier", confidence=0.92),
                ],
            ),
        ]
    else:
        return [
            TranscriptSegment(start=0.0, end=2.0, text="Hallo Welt"),
            TranscriptSegment(start=2.5, end=5.0, text="Zweite Zeile hier"),
        ]


def _make_project(**overrides) -> "Project":
    """Create a minimal Project for testing generate_styled_ass."""
    from src.video.editor import Project

    defaults = dict(
        id="test-proj",
        name="Test",
        width=1920,
        height=1080,
        fps=30,
        duration=10.0,
        sub_font="Arial",
        sub_size=48,
        sub_color="&H00FFFFFF",
        sub_highlight_color="&H0000FFFF",
        sub_outline_color="&H00000000",
        sub_outline_width=2,
        sub_y_percent=85,
        sub_lines=1,
        sub_bg_enabled=True,
        sub_bg_color="&H80000000",
        crf=23,
        audio_bitrate="192k",
    )
    defaults.update(overrides)
    return Project(**defaults)


# ── generate_styled_ass tests ─────────────────────────────────────────────────

class TestGenerateStyledASS:
    """Test that generate_styled_ass produces correct ASS output with karaoke tags."""

    def test_karaoke_tags_present_with_word_timestamps(self, tmp_path: Path):
        """Core bug fix: karaoke \\kf tags must appear when segments have word timestamps."""
        from src.video.editor import generate_styled_ass

        segments = _make_segments(with_words=True)
        project = _make_project(sub_lines=1)
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        result = generate_styled_ass(sub_path, project, out_path, segments=segments)

        assert result is not None
        content = out_path.read_text(encoding="utf-8")

        # Must contain \kf karaoke tags
        assert r"\kf" in content, "Styled ASS must contain \\kf karaoke tags"
        # Must have Dialogue lines
        assert "Dialogue:" in content
        # Must have 2 events (one per segment)
        dialogue_count = content.count("Dialogue:")
        assert dialogue_count == 2, f"Expected 2 Dialogue lines, got {dialogue_count}"

    def test_karaoke_tag_durations_correct(self, tmp_path: Path):
        """Verify \\kf durations are calculated correctly in centiseconds."""
        from src.video.editor import generate_styled_ass

        segments = _make_segments(with_words=True)
        project = _make_project(sub_lines=1)
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        generate_styled_ass(sub_path, project, out_path, segments=segments)
        content = out_path.read_text(encoding="utf-8")

        # Extract all \kf durations from first Dialogue line
        first_dialogue = [l for l in content.splitlines() if l.startswith("Dialogue:")][0]
        kf_values = re.findall(r"\\kf(\d+)", first_dialogue)
        assert len(kf_values) == 2, f"Expected 2 \\kf tags, got {len(kf_values)}: {kf_values}"

        # "Hallo" = 0.0-0.8 = 0.8s = 80cs
        assert int(kf_values[0]) == 80
        # "Welt" = 0.9-2.0 = 1.1s = 110cs
        assert int(kf_values[1]) == 110

    def test_highlight_color_in_first_word(self, tmp_path: Path):
        """The first word of each line should include highlight color override."""
        from src.video.editor import generate_styled_ass

        segments = _make_segments(with_words=True)
        hl_color = "&H00FF00FF"
        project = _make_project(sub_lines=1, sub_highlight_color=hl_color)
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        generate_styled_ass(sub_path, project, out_path, segments=segments)
        content = out_path.read_text(encoding="utf-8")

        dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        for d in dialogues:
            assert f"\\1c{hl_color}" in d, f"Highlight color must appear in first word: {d}"

    def test_no_karaoke_without_words(self, tmp_path: Path):
        """Without word timestamps, no \\kf tags should appear (plain text mode)."""
        from src.video.editor import generate_styled_ass

        segments = _make_segments(with_words=False)
        project = _make_project(sub_lines=1)
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        generate_styled_ass(sub_path, project, out_path, segments=segments)
        content = out_path.read_text(encoding="utf-8")

        assert "Dialogue:" in content
        assert r"\kf" not in content, "No \\kf tags without word timestamps"

    def test_multiline_2_with_karaoke(self, tmp_path: Path):
        """sub_lines=2 should show current (with karaoke) + next (plain context)."""
        from src.video.editor import generate_styled_ass

        segments = _make_segments(with_words=True)
        project = _make_project(sub_lines=2)
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        generate_styled_ass(sub_path, project, out_path, segments=segments)
        content = out_path.read_text(encoding="utf-8")

        dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        # First dialogue should have karaoke for current + context for next
        assert r"\kf" in dialogues[0], "Current line must have karaoke tags"
        # Context lines use \fs tag for smaller size
        assert r"\fs" in dialogues[0], "Multi-line should include context font size"

    def test_multiline_3_with_karaoke(self, tmp_path: Path):
        """sub_lines=3 should show prev + current (karaoke) + next."""
        from src.video.editor import generate_styled_ass

        segments = _make_segments(with_words=True)
        project = _make_project(sub_lines=3)
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        generate_styled_ass(sub_path, project, out_path, segments=segments)
        content = out_path.read_text(encoding="utf-8")

        dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogues) == 2
        # Second dialogue (index 1) should have prev context, current with karaoke, no next
        assert r"\kf" in dialogues[1], "Current line in 3-line mode must have karaoke"

    def test_fallback_from_file_without_segments(self, tmp_path: Path):
        """When no segments passed, should parse from SRT file on disk."""
        from src.video.editor import generate_styled_ass

        srt_content = (
            "1\n00:00:00,000 --> 00:00:02,000\nHallo Welt\n\n"
            "2\n00:00:02,500 --> 00:00:05,000\nZweite Zeile\n"
        )
        sub_path = tmp_path / "test.srt"
        sub_path.write_text(srt_content, encoding="utf-8")
        out_path = tmp_path / "styled.ass"
        project = _make_project(sub_lines=1)

        result = generate_styled_ass(sub_path, project, out_path, segments=None)

        assert result is not None
        content = out_path.read_text(encoding="utf-8")
        assert "Dialogue:" in content
        # No karaoke tags since SRT has no word timestamps
        assert r"\kf" not in content

    def test_ass_header_styles(self, tmp_path: Path):
        """The generated ASS must have correct Style definitions."""
        from src.video.editor import generate_styled_ass

        segments = _make_segments(with_words=True)
        project = _make_project(sub_font="Noto Sans", sub_size=60)
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        generate_styled_ass(sub_path, project, out_path, segments=segments)
        content = out_path.read_text(encoding="utf-8")

        assert "Style: Current,Noto Sans,60," in content
        assert "Style: Context,Noto Sans,45," in content  # 60 * 0.75 = 45
        assert "PlayResX: 1920" in content
        assert "PlayResY: 1080" in content


# ── Subtitle lifecycle integration test ───────────────────────────────────────

class TestSubtitleLifecycle:
    """End-to-end: segments.json → styled ASS → karaoke tags preserved."""

    def test_segments_json_to_styled_ass_preserves_karaoke(self, tmp_path: Path):
        """Simulate the full lifecycle: save segments.json, generate styled ASS."""
        from src.transcription.base import TranscriptSegment, WordInfo
        from src.video.editor import generate_styled_ass

        segments = [
            TranscriptSegment(
                start=0.0, end=3.0, text="Ich bin hier",
                confidence=0.9, has_word_timestamps=True,
                words=[
                    WordInfo(start=0.0, end=1.0, word="Ich", confidence=0.9),
                    WordInfo(start=1.1, end=2.0, word="bin", confidence=0.85),
                    WordInfo(start=2.1, end=3.0, word="hier", confidence=0.92),
                ],
            ),
        ]

        # Save segments.json (as the API would)
        seg_json = tmp_path / "segments.json"
        seg_json.write_text(
            json.dumps([s.to_dict() for s in segments], ensure_ascii=False),
            encoding="utf-8",
        )

        # Reload (as build_render_cmd does)
        reloaded = [TranscriptSegment.from_dict(d) for d in json.loads(seg_json.read_text(encoding="utf-8"))]

        project = _make_project(sub_lines=1)
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        result = generate_styled_ass(sub_path, project, out_path, segments=reloaded)
        assert result is not None

        content = out_path.read_text(encoding="utf-8")
        # All 3 words must have \kf tags
        kf_count = len(re.findall(r"\\kf\d+", content))
        assert kf_count == 3, f"Expected 3 \\kf tags (one per word), got {kf_count}"

        # Word text must be present
        assert "Ich" in content
        assert "bin" in content
        assert "hier" in content


# ── Karaoke tag round-trip test ───────────────────────────────────────────────

class TestKaraokeTagParsing:
    """Verify ASS karaoke tags can be parsed back into word-level timing.

    This mirrors the JS `_parseKaraokeTags` logic in editor.html, ensuring
    the generated ASS output is parseable for the live preview fill effect.
    """

    @staticmethod
    def _parse_karaoke_tags_py(raw: str, line_start: float) -> list:
        """Python equivalent of editor.html's _parseKaraokeTags JS function."""
        import re as _re
        pattern = _re.compile(r"\{[^}]*\\(kf|ko|k)(\d+)[^}]*\}([^{]*)")
        words = []
        t = line_start
        for m in pattern.finditer(raw):
            mode = m.group(1)
            dur_cs = int(m.group(2))
            w = m.group(3).replace("\\N", " ").strip()
            if not w:
                t += dur_cs / 100
                continue
            words.append({"start": t, "end": t + dur_cs / 100, "word": w, "_mode": mode})
            t += dur_cs / 100
        return words

    def test_round_trip_kf_tags(self, tmp_path: Path):
        """Generate ASS with \\kf tags, then parse back word timing."""
        from src.video.editor import generate_styled_ass

        segments = _make_segments(with_words=True)
        project = _make_project(sub_lines=1, sub_highlight_color="&H0000FFFF")
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        generate_styled_ass(sub_path, project, out_path, segments=segments)
        content = out_path.read_text(encoding="utf-8")

        dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogues) >= 1

        # Parse first dialogue line
        parts = dialogues[0].split(",", 9)
        start_str = parts[1].strip()
        # Parse ASS time
        sp = start_str.split(":")
        start_sec = int(sp[0]) * 3600 + int(sp[1]) * 60 + float(sp[2])
        raw_text = parts[9]

        words = self._parse_karaoke_tags_py(raw_text, start_sec)
        assert len(words) == 2, f"Expected 2 words, got {len(words)}: {words}"

        # Verify word text
        assert words[0]["word"] == "Hallo"
        assert words[1]["word"] == "Welt"

        # Verify mode is kf
        assert words[0]["_mode"] == "kf"
        assert words[1]["_mode"] == "kf"

        # Verify timing: durations should match original
        dur0 = round((words[0]["end"] - words[0]["start"]) * 100)
        dur1 = round((words[1]["end"] - words[1]["start"]) * 100)
        assert dur0 == 80, f"Hallo duration: expected 80cs, got {dur0}cs"
        assert dur1 == 110, f"Welt duration: expected 110cs, got {dur1}cs"

    def test_parse_with_color_override(self, tmp_path: Path):
        """Ensure \\1c color override in first word doesn't break parsing."""
        from src.video.editor import generate_styled_ass

        segments = _make_segments(with_words=True)
        hl_color = "&H00FF00FF"
        project = _make_project(sub_lines=1, sub_highlight_color=hl_color)
        sub_path = tmp_path / "test.ass"
        sub_path.write_text("", encoding="utf-8")
        out_path = tmp_path / "styled.ass"

        generate_styled_ass(sub_path, project, out_path, segments=segments)
        content = out_path.read_text(encoding="utf-8")

        dialogues = [l for l in content.splitlines() if l.startswith("Dialogue:")]
        parts = dialogues[0].split(",", 9)
        start_str = parts[1].strip()
        sp = start_str.split(":")
        start_sec = int(sp[0]) * 3600 + int(sp[1]) * 60 + float(sp[2])
        raw_text = parts[9]

        # Parse — must handle {\kf80\1c&H00FF00FF}Hallo correctly
        words = self._parse_karaoke_tags_py(raw_text, start_sec)
        assert len(words) == 2
        assert words[0]["word"] == "Hallo"
        assert words[0]["_mode"] == "kf"

    def test_parse_no_karaoke_tags(self):
        """Lines without karaoke tags should return empty word list."""
        words = self._parse_karaoke_tags_py("Just plain text", 0.0)
        assert words == []

    def test_parse_k_mode(self):
        """Parse \\k (instant highlight) tags."""
        raw = r"{\k50}Hello {\k30}World"
        words = self._parse_karaoke_tags_py(raw, 1.0)
        assert len(words) == 2
        assert words[0]["_mode"] == "k"
        assert words[1]["_mode"] == "k"
        assert words[0]["word"] == "Hello"
        assert words[1]["word"] == "World"
        assert abs(words[0]["end"] - 1.5) < 0.01
        assert abs(words[1]["start"] - 1.5) < 0.01

class TestLogging:
    """Test correlation IDs, file logging, and context management."""

    def test_set_get_request_id(self):
        from src.utils.logging import set_request_id, get_request_id, _request_id_var
        rid = set_request_id("test-req-123")
        assert rid == "test-req-123"
        assert get_request_id() == "test-req-123"
        _request_id_var.set("")

    def test_auto_generate_request_id(self):
        from src.utils.logging import set_request_id, get_request_id
        rid = set_request_id()
        assert len(rid) == 12  # uuid hex[:12]
        assert get_request_id() == rid
        set_request_id("")

    def test_set_get_job_id(self):
        from src.utils.logging import set_job_id, get_job_id
        set_job_id("abc123")
        assert get_job_id() == "abc123"
        set_job_id("")

    def test_ctx_prefix_with_both_ids(self):
        from src.utils.logging import set_request_id, set_job_id, _ctx_prefix, _request_id_var, _job_id_var
        set_request_id("req-1")
        set_job_id("job-2")
        prefix = _ctx_prefix()
        assert "req=req-1" in prefix
        assert "job=job-2" in prefix
        _request_id_var.set("")
        _job_id_var.set("")

    def test_ctx_prefix_empty(self):
        from src.utils.logging import _request_id_var, _job_id_var, _ctx_prefix
        _request_id_var.set("")
        _job_id_var.set("")
        assert _ctx_prefix() == ""

    def test_file_logger_writes(self, tmp_path: Path, monkeypatch):
        """Verify that the file logger actually writes to disk."""
        import logging

        from src.utils.logging import _setup_file_handler, _ContextFormatter

        logger = logging.getLogger("test.file_write")
        logger.setLevel(logging.DEBUG)
        log_file = tmp_path / "test.log"
        _setup_file_handler(logger, log_file)

        logger.info("Test message 1234")
        # Flush handlers
        for h in logger.handlers:
            h.flush()

        content = log_file.read_text(encoding="utf-8")
        assert "Test message 1234" in content

    def test_context_formatter_includes_ids(self, tmp_path: Path):
        """Context formatter should prepend request/job IDs."""
        import logging

        from src.utils.logging import (
            _setup_file_handler,
            _request_id_var,
            _job_id_var,
            set_request_id,
            set_job_id,
        )

        logger = logging.getLogger("test.ctx_fmt")
        logger.setLevel(logging.DEBUG)
        log_file = tmp_path / "ctx.log"
        _setup_file_handler(logger, log_file)

        set_request_id("r-abc")
        set_job_id("j-xyz")
        logger.info("context test message")
        for h in logger.handlers:
            h.flush()

        content = log_file.read_text(encoding="utf-8")
        assert "req=r-abc" in content
        assert "job=j-xyz" in content
        assert "context test message" in content

        _request_id_var.set("")
        _job_id_var.set("")


# ── Filtergraph null removal test ─────────────────────────────────────────────

class TestFiltergraph:
    """Verify filtergraph no longer contains confusing 'null' filter."""

    def test_no_null_filter_in_source(self):
        """The build_render_cmd source should use 'copy' not 'null' for final chain."""
        source = Path("src/video/editor.py").read_text(encoding="utf-8")
        # The old pattern was: null[vout]
        # The new pattern should be: copy[vout]
        assert "null[vout]" not in source, "Filtergraph should use 'copy' instead of 'null'"
        assert "copy[vout]" in source, "Filtergraph should use 'copy[vout]' for final label"
