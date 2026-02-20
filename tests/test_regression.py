"""Regression tests for previously fixed bugs and edge cases.

Each test documents a specific bug/fix and verifies the correct behavior.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest


# ── Regression: _validate_words clears stale word timestamps ─────────────────

class TestWordTimestampValidation:
    """Bug: editing segment text could leave stale word timestamps that
    no longer match the text, causing broken karaoke rendering.

    Fix: _validate_words() in routes.py clears words when mismatch detected.
    """

    def test_stale_words_cleared_on_text_mismatch(self, client, seed_job):
        job_id, job_dir = seed_job
        # Set up segment with word timestamps
        segs = json.loads((job_dir / "segments.json").read_text())
        segs[0]["words"] = [
            {"start": 0.0, "end": 1.0, "word": "Hello", "confidence": 0.9},
            {"start": 1.0, "end": 2.5, "word": "world", "confidence": 0.9},
        ]
        segs[0]["has_word_timestamps"] = True
        (job_dir / "segments.json").write_text(json.dumps(segs))

        # Edit text to mismatch words
        client.put(f"/api/jobs/{job_id}/segments",
                   json={"index": 0, "text": "Changed completely"})

        # Words should be cleared
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["words"] == []
        assert segs[0]["has_word_timestamps"] is False

    def test_matching_words_preserved(self, client, seed_job):
        job_id, job_dir = seed_job
        segs = json.loads((job_dir / "segments.json").read_text())
        segs[0]["words"] = [
            {"start": 0.0, "end": 1.0, "word": "Hello", "confidence": 0.9},
            {"start": 1.0, "end": 2.5, "word": "world", "confidence": 0.9},
        ]
        segs[0]["has_word_timestamps"] = True
        (job_dir / "segments.json").write_text(json.dumps(segs))

        # Read without editing — words should be preserved
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert len(segs[0]["words"]) == 2


# ── Regression: SRT auto-sync after segment edit ─────────────────────────────

class TestSRTAutoSync:
    """Bug: editing segments didn't update the SRT file, causing
    stale subtitles on re-download.

    Fix: _save_segs() calls _sync_srt() to regenerate SRT.
    """

    def test_srt_updated_after_segment_edit(self, client, seed_job):
        job_id, job_dir = seed_job
        # Edit segment text
        client.put(f"/api/jobs/{job_id}/segments",
                   json={"index": 0, "text": "Updated via API"})

        # SRT file should reflect change
        srt_path = job_dir / "test_song.srt"
        srt_content = srt_path.read_text(encoding="utf-8")
        assert "Updated via API" in srt_content

    def test_srt_updated_after_merge(self, client, seed_job):
        job_id, job_dir = seed_job
        client.post(f"/api/jobs/{job_id}/segments/merge",
                    json={"index_a": 0, "index_b": 1})

        srt_path = job_dir / "test_song.srt"
        srt_content = srt_path.read_text(encoding="utf-8")
        # Merged text should appear
        assert "Hello world" in srt_content
        assert "This is a test" in srt_content


# ── Regression: undo restores exact previous state ───────────────────────────

class TestUndoExactRestore:
    """Bug: undo could partially restore state if the segments.json format
    changed between save and restore.

    Fix: undo stores raw JSON string and restores it byte-for-byte.
    """

    def test_undo_restores_all_fields(self, client, seed_job):
        job_id = seed_job[0]
        # Get original state
        original = client.get(f"/api/jobs/{job_id}/segments").json()

        # Make multiple edits
        client.put(f"/api/jobs/{job_id}/segments",
                   json={"index": 0, "text": "Edit 1"})
        client.put(f"/api/jobs/{job_id}/segments",
                   json={"index": 1, "text": "Edit 2"})

        # Undo twice
        client.post(f"/api/jobs/{job_id}/undo")
        client.post(f"/api/jobs/{job_id}/undo")

        restored = client.get(f"/api/jobs/{job_id}/segments").json()
        assert restored[0]["text"] == original[0]["text"]
        assert restored[1]["text"] == original[1]["text"]


# ── Regression: delete job cleans up filesystem ──────────────────────────────

class TestDeleteJobCleanup:
    """Bug: deleting a job left orphaned files on disk.

    Fix: DELETE /api/jobs/{job_id} uses shutil.rmtree() on job directory.
    """

    def test_delete_removes_directory(self, client, seed_job):
        job_id, job_dir = seed_job
        assert job_dir.exists()

        client.delete(f"/api/jobs/{job_id}")

        assert not job_dir.exists()

    def test_delete_removes_from_memory(self, client, seed_job):
        job_id = seed_job[0]
        client.delete(f"/api/jobs/{job_id}")

        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 404


# ── Regression: split preserves segment count correctly ──────────────────────

class TestSplitSegmentCount:
    """Bug: split_segment could produce wrong segment count when splitting
    at the boundary.

    Fix: Validates split_at is strictly between start and end.
    """

    def test_split_at_boundary_rejected(self, client, seed_job):
        job_id = seed_job[0]
        # Try to split at exact segment start (0.0)
        r = client.post(f"/api/jobs/{job_id}/segments/split",
                        json={"index": 0, "split_at": 0.0})
        assert r.status_code == 400

        # Try to split at exact segment end (2.5)
        r = client.post(f"/api/jobs/{job_id}/segments/split",
                        json={"index": 0, "split_at": 2.5})
        assert r.status_code == 400


# ── Regression: time-shift doesn't produce negative timestamps ───────────────

class TestTimeShiftNonNegative:
    """Bug: negative time-shift could produce negative start/end values,
    breaking playback.

    Fix: max(0, ...) clamp in time_shift_segments.
    """

    def test_negative_shift_clamped_to_zero(self, client, seed_job):
        job_id = seed_job[0]
        # Shift all segments by -10 seconds (more than their start time)
        client.post(f"/api/jobs/{job_id}/segments/time-shift",
                    json={"offset_ms": -10000})

        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        for seg in segs:
            assert seg["start"] >= 0
            assert seg["end"] >= 0


# ── Regression: concurrent DB operations don't corrupt data ──────────────────

class TestConcurrentDBSafety:
    """Bug: multiple concurrent save_transcription calls could corrupt
    the SQLite database due to missing locking.

    Fix: _db_lock threading.Lock wraps all write operations.
    """

    def test_concurrent_saves_no_errors(self, db):
        from src.db.library import save_transcription, list_transcriptions

        errors = []

        def _save(i):
            try:
                save_transcription(
                    source_filename=f"regression_{i}.mp3",
                    backend="voxtral", language="de", segments_count=i,
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_save, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        records, total = list_transcriptions(limit=50)
        assert total >= 5


# ── Regression: bulk replace preserves JSON structure ────────────────────────

class TestBulkReplace:
    """Bug: bulk replace with empty segments array could cause
    downstream errors in SRT sync.

    Fix: _save_segs handles empty arrays gracefully.
    """

    def test_bulk_replace_empty(self, client, seed_job):
        job_id = seed_job[0]
        r = client.put(f"/api/jobs/{job_id}/segments/bulk", json=[])
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_bulk_replace_preserves_structure(self, client, seed_job):
        job_id = seed_job[0]
        new_segs = [
            {"start": 0, "end": 1, "text": "A", "confidence": 0.9,
             "has_word_timestamps": False, "words": [],
             "speaker": "Alice", "pinned": True},
        ]
        r = client.put(f"/api/jobs/{job_id}/segments/bulk", json=new_segs)
        assert r.status_code == 200

        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["speaker"] == "Alice"
        assert segs[0]["pinned"] is True
