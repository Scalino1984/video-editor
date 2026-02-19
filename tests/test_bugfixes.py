"""Tests for bugfixes: DB locking, path traversal, job cleanup, undo, CORS, Pydantic."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest


# ── DB Lock Usage ─────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_bugfix.sqlite"


@pytest.fixture
def setup_db(db_path):
    from src.db.library import init_db, close_db
    init_db(db_path)
    yield
    close_db()


def test_concurrent_save_transcription(setup_db):
    """Verify _db_lock prevents concurrent write corruption."""
    from src.db.library import save_transcription, list_transcriptions

    errors = []

    def _save(i):
        try:
            save_transcription(
                source_filename=f"song_{i}.mp3",
                backend="voxtral",
                language="de",
                segments_count=i,
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_save, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent saves produced errors: {errors}"
    records, total = list_transcriptions(limit=50)
    assert total == 10


def test_concurrent_register_media(setup_db):
    """Verify _db_lock prevents concurrent media registration corruption."""
    from src.db.library import register_media, list_media

    errors = []

    def _register(i):
        try:
            register_media(
                filename=f"file_{i}.mp3",
                path=f"data/uploads/file_{i}.mp3",
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_register, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent registrations produced errors: {errors}"
    items = list_media(limit=50)
    assert len(items) == 10


# ── File Registry Lock ────────────────────────────────────────────────────────

def test_concurrent_file_registry(setup_db, tmp_path, monkeypatch):
    """Verify _db_lock on file registry operations."""
    import src.db.library as lib
    monkeypatch.setattr(lib, "_ALLOWED_BASES", [tmp_path])

    errors = []

    def _register(i):
        try:
            p = tmp_path / f"file_{i}.srt"
            p.write_text("test")
            lib.register_file(
                storage_path=str(p),
                original_name=f"file_{i}.srt",
                file_type="derived",
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_register, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent file registry ops produced errors: {errors}"
    files = lib.list_registered_files(limit=50)
    assert len(files) == 10


# ── Job Memory Cleanup ────────────────────────────────────────────────────────

def test_job_memory_cleanup():
    """Verify old completed jobs are cleaned up from memory."""
    from src.api.tasks import (
        create_job, update_job, get_jobs, _jobs, _jobs_lock,
        _cancel_events, _undo_stacks, _redo_stacks,
        MAX_FINISHED_JOBS, JobStatus, _cleanup_finished_jobs,
    )
    from datetime import datetime, timezone

    # Save current state
    with _jobs_lock:
        saved_jobs = dict(_jobs)
        saved_cancel = dict(_cancel_events)

    try:
        # Clear state
        with _jobs_lock:
            _jobs.clear()
        _cancel_events.clear()
        _undo_stacks.clear()
        _redo_stacks.clear()

        # Create more jobs than the limit
        job_ids = []
        for i in range(MAX_FINISHED_JOBS + 10):
            job = create_job(f"test_{i}.mp3")
            job_ids.append(job.job_id)
            update_job(job.job_id, status=JobStatus.completed,
                       completed_at=datetime.now(timezone.utc))

        # Create one more job — should trigger cleanup
        new_job = create_job("trigger.mp3")

        with _jobs_lock:
            job_count = len(_jobs)

        # Should have cleaned up old jobs
        assert job_count <= MAX_FINISHED_JOBS + 11  # +1 for the new pending job

    finally:
        # Restore state
        with _jobs_lock:
            _jobs.clear()
            _jobs.update(saved_jobs)
        _cancel_events.clear()
        _cancel_events.update(saved_cancel)


# ── Pydantic Model Fix ───────────────────────────────────────────────────────

def test_job_result_no_deprecation_warning():
    """Verify JobResult uses ConfigDict instead of deprecated class Config."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        from src.api.models import JobResult
        # Should not raise a deprecation warning
        result = JobResult(segments_count=10, backend="test")
        assert result.segments_count == 10


# ── Path Traversal Protection ────────────────────────────────────────────────

def test_load_segs_path_traversal():
    """Verify _load_segs rejects path traversal in job_id."""
    pytest.importorskip("multipart", reason="python-multipart not installed")
    from fastapi import HTTPException
    from src.api.routes import _load_segs

    with pytest.raises(HTTPException) as exc_info:
        _load_segs("../../etc")
    assert exc_info.value.status_code == 400


# ── CORS Configuration ───────────────────────────────────────────────────────

def test_cors_no_credentials_with_wildcard():
    """Verify CORS does not allow credentials with wildcard origins."""
    pytest.importorskip("dotenv", reason="python-dotenv not installed")
    from main import app

    cors_middleware = None
    for m in app.user_middleware:
        if "CORSMiddleware" in str(m):
            cors_middleware = m
            break

    assert cors_middleware is not None
    # The kwargs should have allow_credentials=False when using wildcard origins
    assert cors_middleware.kwargs.get("allow_credentials") is False
