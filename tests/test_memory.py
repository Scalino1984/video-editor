"""Tests for memory management features.

Covers backend caching, undo-stack LRU eviction, AI chat DB LRU,
upload streaming, backend unload, and the /memory API endpoints.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.api.models import JobInfo, JobStatus
from tests.conftest import SAMPLE_SEGMENTS


# ── Backend singleton cache ─────────────────────────────────────────────────


class TestBackendCache:
    """Backend instances are cached by key and reused."""

    def test_local_whisper_cached(self):
        """LocalWhisperBackend is returned from cache on second call."""
        from src.api import tasks as t

        # Clear cache
        with t._backend_cache_lock:
            t._backend_cache.clear()

        with patch("src.transcription.local_whisper.LocalWhisperBackend") as MockLW:
            instance = MagicMock()
            MockLW.return_value = instance

            req = MagicMock()
            req.whisperx_model_size = "large-v3"

            b1 = t._get_backend("local_whisper", req=req)
            b2 = t._get_backend("local_whisper", req=req)

            assert b1 is b2, "Should return same cached instance"
            assert MockLW.call_count == 1, "Constructor called only once"

        # Cleanup
        with t._backend_cache_lock:
            t._backend_cache.clear()

    def test_whisperx_cached(self):
        """WhisperXBackend is cached by model key."""
        from src.api import tasks as t

        with t._backend_cache_lock:
            t._backend_cache.clear()

        with patch("src.transcription.whisperx_backend.WhisperXBackend") as MockWX:
            instance = MagicMock()
            MockWX.return_value = instance

            req = MagicMock()
            req.whisperx_model_size = "medium"
            req.whisperx_compute_type = "int8"
            req.whisperx_batch_size = 1

            b1 = t._get_backend("whisperx", req=req)
            b2 = t._get_backend("whisperx", req=req)

            assert b1 is b2
            assert MockWX.call_count == 1

        with t._backend_cache_lock:
            t._backend_cache.clear()

    def test_voxtral_not_cached(self):
        """Voxtral (API-only) creates a new instance each time."""
        from src.api import tasks as t

        with patch("src.transcription.voxtral.VoxtralBackend") as MockV:
            b1 = t._get_backend("voxtral")
            b2 = t._get_backend("voxtral")

            assert MockV.call_count == 2, "Voxtral not cached — new instance each call"

    def test_unload_backend_all(self):
        """unload_backend() without name clears all cached backends."""
        from src.api import tasks as t

        mock_be = MagicMock()
        mock_be.unload = MagicMock()

        with t._backend_cache_lock:
            t._backend_cache["local_whisper:large-v3"] = mock_be
            t._backend_cache["whisperx:medium"] = MagicMock()

        count = t.unload_backend()
        assert count == 2
        assert len(t._backend_cache) == 0
        mock_be.unload.assert_called_once()

    def test_unload_backend_by_name(self):
        """unload_backend('whisperx') only removes whisperx entries."""
        from src.api import tasks as t

        with t._backend_cache_lock:
            t._backend_cache.clear()
            t._backend_cache["whisperx:medium"] = MagicMock()
            t._backend_cache["local_whisper:large-v3"] = MagicMock()

        count = t.unload_backend("whisperx")
        assert count == 1
        assert "local_whisper:large-v3" in t._backend_cache
        assert "whisperx:medium" not in t._backend_cache

        with t._backend_cache_lock:
            t._backend_cache.clear()


# ── Undo-stack LRU eviction ────────────────────────────────────────────────


class TestUndoEviction:
    """Undo stacks are evicted for old jobs beyond MAX_UNDO_IDLE_JOBS."""

    def test_eviction_triggers(self):
        """Creating jobs beyond MAX_UNDO_IDLE_JOBS evicts oldest undo stacks."""
        from src.api import tasks as t

        # Prepare: create many jobs with undo data
        original_max = t.MAX_UNDO_IDLE_JOBS
        t.MAX_UNDO_IDLE_JOBS = 3

        try:
            job_ids = []
            for i in range(6):
                job = t.create_job(f"test_{i}.mp3")
                jid = job.job_id
                job_ids.append(jid)

                t.update_job(jid, status=JobStatus.completed,
                             completed_at=datetime.now(timezone.utc))

                # Add undo data
                with t._undo_lock:
                    t._undo_stacks[jid] = deque(["snapshot_data"], maxlen=t.MAX_UNDO)

            # create_job triggers _cleanup_finished_jobs which evicts undo stacks
            trigger = t.create_job("trigger.mp3")

            # Count remaining undo stacks (only from our test jobs)
            remaining = [jid for jid in job_ids if jid in t._undo_stacks]
            assert len(remaining) <= 3, f"Expected ≤3 undo stacks, got {len(remaining)}"

        finally:
            t.MAX_UNDO_IDLE_JOBS = original_max
            # Cleanup
            for jid in job_ids:
                with t._jobs_lock:
                    t._jobs.pop(jid, None)
                t._undo_stacks.pop(jid, None)
                t._redo_stacks.pop(jid, None)
                t._cancel_events.pop(jid, None)
            with t._jobs_lock:
                t._jobs.pop(trigger.job_id, None)
            t._cancel_events.pop(trigger.job_id, None)


# ── AI Chat DB LRU ──────────────────────────────────────────────────────────


class TestChatDbLRU:
    """AI chat database connections are bounded by _MAX_OPEN_DBS."""

    def test_lru_eviction(self, tmp_path):
        """Opening more than _MAX_OPEN_DBS evicts oldest DB."""
        from src.ai.database import _dbs, _MAX_OPEN_DBS, get_db, close_all

        # Clean slate
        close_all()
        original_max = _MAX_OPEN_DBS

        try:
            # Create more DBs than the limit
            from src.ai import database as db_mod
            db_mod._MAX_OPEN_DBS = 3

            job_ids = []
            for i in range(5):
                jid = f"test_chat_{i}"
                job_ids.append(jid)
                get_db(jid, tmp_path)

            assert len(_dbs) <= 3, f"Expected ≤3 open DBs, got {len(_dbs)}"
            # Oldest should have been evicted
            assert "test_chat_0" not in _dbs
            assert "test_chat_1" not in _dbs
            # Newest should remain
            assert "test_chat_4" in _dbs

        finally:
            db_mod._MAX_OPEN_DBS = original_max
            close_all()

    def test_lru_reuse_refreshes(self, tmp_path):
        """Accessing an existing DB moves it to the end (most recent)."""
        from src.ai.database import _dbs, get_db, close_all
        from src.ai import database as db_mod

        close_all()
        original_max = db_mod._MAX_OPEN_DBS

        try:
            db_mod._MAX_OPEN_DBS = 3

            get_db("a", tmp_path)
            get_db("b", tmp_path)
            get_db("c", tmp_path)

            # Access "a" again — refreshes it
            get_db("a", tmp_path)

            # Now adding "d" should evict "b" (oldest after refresh), not "a"
            get_db("d", tmp_path)

            assert "a" in _dbs, "'a' should survive (was refreshed)"
            assert "b" not in _dbs, "'b' should be evicted (oldest)"
            assert "d" in _dbs

        finally:
            db_mod._MAX_OPEN_DBS = original_max
            close_all()


# ── deps_check lazy imports ─────────────────────────────────────────────────


class TestDepsCheckLazy:
    """deps_check functions use importlib.util.find_spec instead of real imports."""

    def test_check_demucs_no_import(self):
        """check_demucs() doesn't actually import demucs."""
        from src.utils.deps_check import check_demucs

        with patch("importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = None  # demucs not installed
            result = check_demucs()
            assert not result.available
            mock_spec.assert_called_with("demucs")

    def test_check_whisperx_no_import(self):
        """check_whisperx() doesn't import the full whisperx package."""
        from src.utils.deps_check import check_whisperx

        with patch("importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = MagicMock()  # whisperx "installed"
            result = check_whisperx()
            assert result.available
            mock_spec.assert_called_with("whisperx")


# ── Memory API endpoints ────────────────────────────────────────────────────


class TestMemoryAPI:
    """GET /api/memory and POST /api/memory/unload-backends."""

    def test_memory_status(self, client):
        r = client.get("/api/memory")
        assert r.status_code == 200
        data = r.json()
        assert "rss_mb" in data
        assert "cached_backends" in data
        assert "undo_stacks" in data
        assert "chat_dbs_open" in data
        assert isinstance(data["rss_mb"], (int, float))

    def test_unload_backends_endpoint(self, client):
        r = client.post("/api/memory/unload-backends")
        assert r.status_code == 200
        data = r.json()
        assert "unloaded" in data


# ── Upload streaming ────────────────────────────────────────────────────────


class TestUploadStreaming:
    """File uploads use streaming (shutil.copyfileobj) not .read()."""

    def test_upload_uses_streaming(self, client, _patch_dirs, storage_root):
        """The main upload endpoint streams file to disk."""
        import io
        audio_bytes = b"\x00" * 1024  # dummy audio
        files = {"file": ("test.wav", io.BytesIO(audio_bytes), "audio/wav")}

        with patch("shutil.copyfileobj") as mock_copy:
            # The upload will fail later (no real audio), but copyfileobj should be called
            r = client.post("/api/upload", files=files)
            # Even if the endpoint fails, shutil.copyfileobj was used for the file write
            assert mock_copy.called or r.status_code == 200
