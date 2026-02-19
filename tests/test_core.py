"""Core tests for karaoke-sub-tool v3."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── Data models ───────────────────────────────────────────────────────────────

def test_transcript_segment_roundtrip():
    from src.transcription.base import TranscriptSegment, WordInfo
    seg = TranscriptSegment(
        start=1.0, end=3.5, text="Hello world",
        confidence=0.95, has_word_timestamps=True,
        words=[WordInfo(start=1.0, end=2.0, word="Hello", confidence=0.9),
               WordInfo(start=2.1, end=3.5, word="world", confidence=0.98)],
    )
    d = seg.to_dict()
    restored = TranscriptSegment.from_dict(d)
    assert restored.text == "Hello world"
    assert len(restored.words) == 2
    assert restored.words[0].word == "Hello"
    assert restored.confidence == 0.95


def test_transcript_result():
    from src.transcription.base import TranscriptResult, TranscriptSegment
    tr = TranscriptResult(
        segments=[TranscriptSegment(start=0, end=1, text="Test")],
        language="de", backend="whisperx", duration=1.0,
    )
    d = tr.to_dict()
    restored = TranscriptResult.from_dict(d)
    assert restored.backend == "whisperx"
    assert len(restored.segments) == 1


# ── SRT Writer ────────────────────────────────────────────────────────────────

def test_srt_write_read(tmp_path):
    from src.transcription.base import TranscriptSegment
    from src.export.srt_writer import write_srt, read_srt
    segs = [
        TranscriptSegment(start=0.0, end=2.5, text="Erste Zeile"),
        TranscriptSegment(start=3.0, end=5.5, text="Zweite Zeile"),
    ]
    p = tmp_path / "test.srt"
    write_srt(segs, p)
    loaded = read_srt(p)
    assert len(loaded) == 2
    assert loaded[0].text == "Erste Zeile"
    assert abs(loaded[1].start - 3.0) < 0.01


# ── VTT Writer ────────────────────────────────────────────────────────────────

def test_vtt_write_read(tmp_path):
    from src.transcription.base import TranscriptSegment
    from src.export.vtt_writer import write_vtt, read_vtt
    segs = [TranscriptSegment(start=1.0, end=3.0, text="VTT test")]
    p = tmp_path / "test.vtt"
    write_vtt(segs, p)
    content = p.read_text()
    assert "WEBVTT" in content
    loaded = read_vtt(p)
    assert len(loaded) == 1
    assert loaded[0].text == "VTT test"


# ── LRC Writer ────────────────────────────────────────────────────────────────

def test_lrc_write(tmp_path):
    from src.transcription.base import TranscriptSegment
    from src.export.lrc_writer import write_lrc
    segs = [TranscriptSegment(start=10.5, end=15.0, text="Lyrics line")]
    p = tmp_path / "test.lrc"
    write_lrc(segs, p, title="Test Song")
    content = p.read_text()
    assert "[ti:Test Song]" in content
    assert "[00:10.50]" in content
    assert "Lyrics line" in content


# ── TXT Writer ────────────────────────────────────────────────────────────────

def test_txt_write(tmp_path):
    from src.transcription.base import TranscriptSegment
    from src.export.txt_writer import write_txt, write_txt_with_timestamps
    segs = [TranscriptSegment(start=0, end=1, text="Hallo"), TranscriptSegment(start=1, end=2, text="Welt")]
    p1 = tmp_path / "plain.txt"
    write_txt(segs, p1)
    assert "Hallo\nWelt" in p1.read_text()
    p2 = tmp_path / "timed.txt"
    write_txt_with_timestamps(segs, p2)
    assert "[00:00]" in p2.read_text()


# ── Config ────────────────────────────────────────────────────────────────────

def test_config_load_default():
    from src.utils.config import AppConfig
    cfg = AppConfig()
    assert cfg.transcription.backend == "voxtral"
    assert cfg.whisperx.model_size == "large-v3"
    assert cfg.refinement.cps == 18.0


def test_config_merge():
    from src.utils.config import AppConfig, merge_cli_overrides
    cfg = AppConfig()
    merged = merge_cli_overrides(cfg, {"transcription.backend": "whisperx", "refinement.cps": 15.0})
    assert merged.transcription.backend == "whisperx"
    assert merged.refinement.cps == 15.0


# ── API Models ────────────────────────────────────────────────────────────────

def test_api_models():
    from src.api.models import (TranscribeRequest, ExportRequest, SegmentUpdate,
        SegmentSplit, SegmentMerge, TimeShift, SearchReplace, DictionaryEntry,
        BackendEnum, ExportFormatEnum, GapOverlap, JobStats)
    req = TranscribeRequest(backend="whisperx", language="de")
    assert req.backend == BackendEnum.whisperx
    exp = ExportRequest(formats=["srt", "vtt", "lrc"])
    assert len(exp.formats) == 3
    upd = SegmentUpdate(index=0, text="new text", speaker="Speaker1", pinned=True)
    assert upd.speaker == "Speaker1"
    ts = TimeShift(offset_ms=-500, range_start=0, range_end=10)
    assert ts.offset_ms == -500
    sr = SearchReplace(search="foo", replace="bar", regex=True)
    assert sr.regex is True
    de = DictionaryEntry(wrong="teh", correct="the")
    assert de.correct == "the"


# ── Segmentation ──────────────────────────────────────────────────────────────

def test_refine_segments():
    from src.transcription.base import TranscriptSegment
    from src.refine.segmentation import refine_segments
    segs = [TranscriptSegment(start=0, end=12, text="A " * 100)]
    result = refine_segments(segs, cps=18, max_duration=6.0, max_chars_per_line=42, max_lines=2)
    assert len(result) > 1
    for s in result:
        assert s.end - s.start <= 7.0  # some tolerance


# ── Text Cleanup ──────────────────────────────────────────────────────────────

def test_text_cleanup():
    from src.transcription.base import TranscriptSegment
    from src.refine.text_cleanup import clean_all_segments
    segs = [TranscriptSegment(start=0, end=1, text="  Hello   world  ")]
    cleaned = clean_all_segments(segs)
    assert cleaned[0].text.strip() == "Hello world"


# ── ASS Export ────────────────────────────────────────────────────────────────

def test_ass_writer(tmp_path):
    from src.transcription.base import TranscriptSegment, WordInfo
    from src.export.ass_writer import write_ass
    segs = [TranscriptSegment(
        start=0, end=3, text="Karaoke test",
        has_word_timestamps=True,
        words=[WordInfo(start=0, end=1.5, word="Karaoke"), WordInfo(start=1.5, end=3, word="test")],
    )]
    p = tmp_path / "test.ass"
    write_ass(segs, p, preset="classic", karaoke_mode="kf")
    content = p.read_text()
    assert "[Script Info]" in content
    assert "Karaoke" in content


# ── Themes ────────────────────────────────────────────────────────────────────

def test_themes():
    from src.export.themes import PRESETS, get_theme, apply_safe_area
    assert "classic" in PRESETS
    assert "neon" in PRESETS
    theme = get_theme("classic")
    assert theme.playresx == 1920
    modified = apply_safe_area(theme, "100,100,80,80")
    assert modified.margin_l >= 80


# ── Karaoke Tags ──────────────────────────────────────────────────────────────

def test_karaoke_tags():
    from src.transcription.base import TranscriptSegment, WordInfo
    from src.export.karaoke_tags import generate_karaoke_line
    seg = TranscriptSegment(
        start=0, end=2, text="Hello world",
        has_word_timestamps=True,
        words=[WordInfo(start=0, end=1, word="Hello"), WordInfo(start=1, end=2, word="world")],
    )
    line = generate_karaoke_line(seg, mode="kf")
    assert "\\kf" in line


# ── Confidence ────────────────────────────────────────────────────────────────

def test_confidence_analysis():
    from src.transcription.base import TranscriptSegment, WordInfo
    from src.refine.confidence import analyze_confidence
    segs = [
        TranscriptSegment(start=0, end=1, text="Good", confidence=0.95,
            has_word_timestamps=True,
            words=[WordInfo(start=0, end=1, word="Good", confidence=0.95)]),
        TranscriptSegment(start=1, end=2, text="Bad", confidence=0.3,
            has_word_timestamps=True,
            words=[WordInfo(start=1, end=2, word="Bad", confidence=0.3)]),
    ]
    reports = analyze_confidence(segs, threshold=0.6)
    assert len(reports) == 2
    assert not reports[0].needs_review
    assert reports[1].needs_review


# ── WhisperX Backend ──────────────────────────────────────────────────────────

def test_whisperx_backend_check():
    from src.transcription.whisperx_backend import WhisperXBackend
    backend = WhisperXBackend()
    assert backend.name == "whisperx"
    ok, msg = backend.check_available()
    # whisperx may not be installed in test env
    assert isinstance(ok, bool)
    assert isinstance(msg, str)


# ── Deps Check ────────────────────────────────────────────────────────────────

def test_deps_check():
    from src.utils.deps_check import check_all_backends
    backends = check_all_backends()
    assert "voxtral" in backends
    assert "whisperx" in backends
    assert "local_whisper" in backends
    assert "openai_whisper" in backends


# ── SRT Time Format ──────────────────────────────────────────────────────────

def test_srt_time_format():
    from src.export.srt_writer import format_srt_time, parse_srt_time
    assert format_srt_time(0) == "00:00:00,000"
    assert format_srt_time(3661.5) == "01:01:01,500"
    assert abs(parse_srt_time("01:01:01,500") - 3661.5) < 0.01


def test_vtt_time_format():
    from src.export.vtt_writer import format_vtt_time
    assert format_vtt_time(0) == "00:00:00.000"
    assert format_vtt_time(90.123) == "00:01:30.123"


def test_lrc_time_format():
    from src.export.lrc_writer import format_lrc_time
    assert format_lrc_time(0) == "00:00.00"
    assert format_lrc_time(65.5) == "01:05.50"
