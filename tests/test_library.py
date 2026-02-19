"""Tests for Transcriptions Library (SQLite CRUD) and Video Render models."""

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_library.sqlite"


@pytest.fixture
def setup_db(db_path):
    from src.db.library import init_db, close_db
    init_db(db_path)
    yield
    close_db()


# ── Library DB Tests ──────────────────────────────────────────────────────────

def test_db_init_creates_file(setup_db, db_path):
    assert db_path.exists()


def test_save_and_list(setup_db):
    from src.db.library import save_transcription, list_transcriptions

    rec_id = save_transcription(
        source_filename="test_song.mp3",
        backend="voxtral",
        language="de",
        duration_sec=180.0,
        bpm=120.5,
        segments_count=42,
        has_word_timestamps=True,
        needs_review=3,
        avg_confidence=0.87,
        srt_text="1\n00:00:00,000 --> 00:00:03,000\nHello World\n",
        ass_text=None,
        job_id="abc123",
    )

    assert rec_id
    records, total = list_transcriptions()
    assert total == 1
    assert records[0].source_filename == "test_song.mp3"
    assert records[0].backend == "voxtral"
    assert records[0].bpm == 120.5
    assert records[0].segments_count == 42
    assert records[0].has_word_timestamps is True


def test_deduplicate_on_save(setup_db):
    from src.db.library import save_transcription, list_transcriptions

    id1 = save_transcription(
        source_filename="song.mp3", backend="voxtral", language="de",
        segments_count=10, srt_text="v1",
    )
    id2 = save_transcription(
        source_filename="song.mp3", backend="voxtral", language="de",
        segments_count=20, srt_text="v2",
    )

    # Same source_hash → should update, not create duplicate
    assert id1 == id2
    records, total = list_transcriptions()
    assert total == 1
    assert records[0].segments_count == 20  # updated


def test_different_backend_not_deduped(setup_db):
    from src.db.library import save_transcription, list_transcriptions

    save_transcription(
        source_filename="song.mp3", backend="voxtral", language="de",
        srt_text="v1",
    )
    save_transcription(
        source_filename="song.mp3", backend="openai", language="de",
        srt_text="v2",
    )

    _, total = list_transcriptions()
    assert total == 2


def test_get_single(setup_db):
    from src.db.library import save_transcription, get_transcription

    rec_id = save_transcription(
        source_filename="track.wav", backend="local", language="en",
        srt_text="hello", ass_text="[Script Info]\nTitle: test",
    )

    rec = get_transcription(rec_id)
    assert rec is not None
    assert rec.srt_text == "hello"
    assert rec.ass_text is not None
    assert rec.language == "en"


def test_delete_soft(setup_db):
    from src.db.library import save_transcription, delete_transcription, list_transcriptions

    rec_id = save_transcription(
        source_filename="x.mp3", backend="voxtral", language="de",
    )
    _, total_before = list_transcriptions()
    assert total_before == 1

    ok = delete_transcription(rec_id, hard=False)
    assert ok

    _, total_after = list_transcriptions()
    assert total_after == 0  # soft-deleted, hidden from list


def test_delete_hard(setup_db):
    from src.db.library import save_transcription, delete_transcription, get_transcription

    rec_id = save_transcription(
        source_filename="x.mp3", backend="voxtral", language="de",
    )
    ok = delete_transcription(rec_id, hard=True)
    assert ok
    assert get_transcription(rec_id) is None


def test_update_title_and_tags(setup_db):
    from src.db.library import save_transcription, update_transcription, get_transcription

    rec_id = save_transcription(
        source_filename="track.mp3", backend="voxtral", language="de",
    )

    update_transcription(rec_id, title="My Custom Title", tags=["rap", "german"])
    rec = get_transcription(rec_id)
    assert rec.title == "My Custom Title"
    assert rec.tags == ["rap", "german"]


def test_search_filter(setup_db):
    from src.db.library import save_transcription, list_transcriptions

    save_transcription(
        source_filename="alpha_song.mp3", backend="voxtral", language="de",
        title="Alpha Song",
    )
    save_transcription(
        source_filename="beta_track.wav", backend="openai", language="en",
        title="Beta Track",
    )

    records, total = list_transcriptions(q="alpha")
    assert total == 1
    assert records[0].title == "Alpha Song"

    records, total = list_transcriptions(q="openai")
    assert total == 1
    assert records[0].backend == "openai"


def test_pagination(setup_db):
    from src.db.library import save_transcription, list_transcriptions

    for i in range(15):
        save_transcription(
            source_filename=f"song_{i}.mp3", backend="voxtral", language="de",
        )

    records, total = list_transcriptions(limit=5, offset=0)
    assert total == 15
    assert len(records) == 5

    records2, _ = list_transcriptions(limit=5, offset=5)
    assert len(records2) == 5
    assert records[0].id != records2[0].id


# ── Video Render Models ──────────────────────────────────────────────────────

def test_render_presets():
    from src.video.render import RENDER_PRESETS

    assert "youtube" in RENDER_PRESETS
    assert "mobile" in RENDER_PRESETS
    assert "draft" in RENDER_PRESETS
    assert RENDER_PRESETS["youtube"]["crf"] < RENDER_PRESETS["draft"]["crf"]


def test_render_options_defaults():
    from src.video.render import RenderOptions

    opts = RenderOptions()
    assert opts.preset == "youtube"
    assert opts.position == "bottom"
    assert opts.font_size == 48


def test_probe_result():
    from src.video.render import ProbeResult

    pr = ProbeResult(width=1920, height=1080)
    assert pr.is_portrait is False
    assert pr.resolution == "1920x1080"

    pr2 = ProbeResult(width=720, height=1280)
    assert pr2.is_portrait is True


# ── Source Hash ───────────────────────────────────────────────────────────────

def test_source_hash_deterministic(setup_db):
    from src.db.library import compute_source_hash

    h1 = compute_source_hash("song.mp3", "voxtral", "de")
    h2 = compute_source_hash("song.mp3", "voxtral", "de")
    h3 = compute_source_hash("song.mp3", "openai", "de")

    assert h1 == h2
    assert h1 != h3
