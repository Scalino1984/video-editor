"""Shared test fixtures for integration tests.

Provides:
- FastAPI TestClient with isolated storage roots
- Seed data (segments.json, SRT files, dummy audio)
- Mock subprocess/ffmpeg
- DB isolation via per-test SQLite
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── Seed data ────────────────────────────────────────────────────────────────

SAMPLE_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "Hello world", "confidence": 0.95,
     "has_word_timestamps": False, "words": []},
    {"start": 2.5, "end": 5.0, "text": "This is a test", "confidence": 0.88,
     "has_word_timestamps": False, "words": []},
    {"start": 5.5, "end": 8.0, "text": "Third segment here", "confidence": 0.72,
     "has_word_timestamps": False, "words": []},
]

SAMPLE_SRT = """\
1
00:00:00,000 --> 00:00:02,500
Hello world

2
00:00:02,500 --> 00:00:05,000
This is a test

3
00:00:05,500 --> 00:00:08,000
Third segment here
"""


@pytest.fixture
def sample_segments():
    """Return a deep copy of sample segments."""
    return json.loads(json.dumps(SAMPLE_SEGMENTS))


# ── Storage isolation ────────────────────────────────────────────────────────

@pytest.fixture
def storage_root(tmp_path):
    """Create isolated storage directories matching production layout."""
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "output"
    editor_dir = tmp_path / "editor"
    upload_dir.mkdir()
    output_dir.mkdir()
    editor_dir.mkdir()
    (editor_dir / "assets").mkdir()
    (editor_dir / "projects").mkdir()
    (editor_dir / "renders").mkdir()
    return tmp_path


@pytest.fixture
def _patch_dirs(storage_root):
    """Patch all module-level directory constants to use tmp_path."""
    import src.api.tasks as tasks_mod
    import src.video.editor as editor_mod

    orig_upload = tasks_mod.UPLOAD_DIR
    orig_output = tasks_mod.OUTPUT_DIR

    tasks_mod.UPLOAD_DIR = storage_root / "uploads"
    tasks_mod.OUTPUT_DIR = storage_root / "output"

    orig_editor = editor_mod.EDITOR_DIR
    editor_mod.EDITOR_DIR = storage_root / "editor"

    yield storage_root

    tasks_mod.UPLOAD_DIR = orig_upload
    tasks_mod.OUTPUT_DIR = orig_output
    editor_mod.EDITOR_DIR = orig_editor


# ── Seed job helper ──────────────────────────────────────────────────────────

@pytest.fixture
def seed_job(_patch_dirs, storage_root):
    """Create a completed job with segments.json and SRT file.

    Returns (job_id, job_dir) tuple.
    """
    import src.api.tasks as tasks_mod
    from src.api.models import JobStatus
    from datetime import datetime, timezone

    job = tasks_mod.create_job("test_song.mp3")
    job_id = job.job_id
    job_dir = storage_root / "output" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    seg_path = job_dir / "segments.json"
    seg_path.write_text(json.dumps(SAMPLE_SEGMENTS, indent=2), encoding="utf-8")

    srt_path = job_dir / "test_song.srt"
    srt_path.write_text(SAMPLE_SRT, encoding="utf-8")

    tasks_mod.update_job(job_id, status=JobStatus.completed,
                         completed_at=datetime.now(timezone.utc))

    return job_id, job_dir


# ── TestClient ───────────────────────────────────────────────────────────────

@pytest.fixture
def client(_patch_dirs):
    """FastAPI TestClient with patched storage directories."""
    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── DB isolation ─────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    """Initialize an isolated SQLite DB for library tests."""
    from src.db.library import init_db, close_db
    db_path = tmp_path / "test_library.sqlite"
    init_db(db_path)
    yield db_path
    close_db()


# ── Cleanup global job state ─────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _cleanup_jobs():
    """Ensure global job state is cleaned up after each test."""
    from src.api.tasks import _jobs, _jobs_lock, _cancel_events, _undo_stacks, _redo_stacks

    # Save state
    with _jobs_lock:
        saved = dict(_jobs)
    saved_cancel = dict(_cancel_events)
    saved_undo = dict(_undo_stacks)
    saved_redo = dict(_redo_stacks)

    yield

    # Restore state
    with _jobs_lock:
        _jobs.clear()
        _jobs.update(saved)
    _cancel_events.clear()
    _cancel_events.update(saved_cancel)
    _undo_stacks.clear()
    _undo_stacks.update(saved_undo)
    _redo_stacks.clear()
    _redo_stacks.update(saved_redo)
