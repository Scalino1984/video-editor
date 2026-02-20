"""API integration tests — FastAPI TestClient against /api/* endpoints.

Covers: health, files, jobs, segments CRUD, undo/redo, dictionary,
        gaps/overlaps, search-replace, time-shift, snapshots, stats,
        export presets, structure, text-stats, duplicates, speakers,
        normalize-text, remove-short, paste-lyrics, translate, project I/O.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest


# ══════════════════════════════════════════════════════════════════════════════
#  Health & Status
# ══════════════════════════════════════════════════════════════════════════════


class TestHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["version"] == "3.2.0"
        assert "backends" in body

    def test_presets_returns_dict(self, client):
        r = client.get("/api/presets")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)
        assert "classic" in body

    def test_media_queue_status(self, client):
        r = client.get("/api/media-queue")
        assert r.status_code == 200
        body = r.json()
        assert "running" in body or "queued" in body or "max_concurrent" in body

    def test_export_presets_list(self, client):
        r = client.get("/api/export-presets")
        assert r.status_code == 200
        body = r.json()
        assert "youtube" in body
        assert "karaoke" in body

    def test_bpm_params_positive(self, client):
        r = client.get("/api/bpm-params", params={"bpm": 120})
        assert r.status_code == 200
        body = r.json()
        assert "max_cps" in body or "cps" in body or "beat_ms" in body

    def test_bpm_params_zero_rejects(self, client):
        r = client.get("/api/bpm-params", params={"bpm": 0})
        assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  File Upload / List / Delete
# ══════════════════════════════════════════════════════════════════════════════


class TestFileManagement:
    def test_upload_and_list_and_delete(self, client, _patch_dirs, storage_root):
        # Upload
        content = b"RIFF" + b"\x00" * 100  # dummy WAV-like content
        r = client.post("/api/upload", files={"file": ("test.wav", io.BytesIO(content), "audio/wav")})
        assert r.status_code == 200
        body = r.json()
        assert body["filename"] == "test.wav"
        assert body["size"] == len(content)

        # List
        r = client.get("/api/files")
        assert r.status_code == 200
        filenames = [f["filename"] for f in r.json()]
        assert "test.wav" in filenames

        # Delete
        r = client.delete("/api/files/test.wav")
        assert r.status_code == 200
        assert r.json()["deleted"] == "test.wav"

        # Verify gone
        r = client.get("/api/files")
        filenames = [f["filename"] for f in r.json()]
        assert "test.wav" not in filenames

    def test_upload_unsupported_format(self, client, _patch_dirs):
        r = client.post("/api/upload", files={"file": ("test.xyz", io.BytesIO(b"data"), "application/octet-stream")})
        assert r.status_code == 400

    def test_delete_nonexistent_file(self, client, _patch_dirs):
        r = client.delete("/api/files/nonexistent.wav")
        assert r.status_code == 404

    def test_delete_path_traversal(self, client, _patch_dirs):
        r = client.delete("/api/files/..%2F..%2Fetc%2Fpasswd")
        assert r.status_code in (400, 404)

    def test_upload_srt_file(self, client, _patch_dirs):
        content = b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"
        r = client.post("/api/upload", files={"file": ("test.srt", io.BytesIO(content), "text/plain")})
        assert r.status_code == 200

    def test_upload_duplicate_renames(self, client, _patch_dirs, storage_root):
        content = b"RIFF" + b"\x00" * 50
        # Upload first
        r1 = client.post("/api/upload", files={"file": ("dup.wav", io.BytesIO(content), "audio/wav")})
        assert r1.status_code == 200
        # Upload second with same name → should rename
        r2 = client.post("/api/upload", files={"file": ("dup.wav", io.BytesIO(content), "audio/wav")})
        assert r2.status_code == 200
        assert r2.json()["filename"] != r1.json()["filename"]


# ══════════════════════════════════════════════════════════════════════════════
#  Job Lifecycle
# ══════════════════════════════════════════════════════════════════════════════


class TestJobLifecycle:
    def test_list_jobs(self, client, seed_job):
        r = client.get("/api/jobs")
        assert r.status_code == 200
        jobs = r.json()
        assert any(j["job_id"] == seed_job[0] for j in jobs)

    def test_get_job(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["job_id"] == job_id

    def test_get_job_not_found(self, client, _patch_dirs):
        r = client.get("/api/jobs/nonexistent-job-id")
        assert r.status_code == 404

    def test_delete_job(self, client, seed_job):
        job_id, job_dir = seed_job
        r = client.delete(f"/api/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["deleted"] == job_id
        # Verify directory removed
        assert not job_dir.exists()

    def test_delete_job_not_found(self, client, _patch_dirs):
        r = client.delete("/api/jobs/nonexistent-id")
        assert r.status_code == 404

    def test_cancel_completed_job_fails(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/cancel")
        assert r.status_code == 400

    def test_list_job_files(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/files")
        assert r.status_code == 200
        body = r.json()
        assert "files" in body
        assert "srt" in body["files"]


# ══════════════════════════════════════════════════════════════════════════════
#  File Downloads / Content
# ══════════════════════════════════════════════════════════════════════════════


class TestDownloads:
    def test_download_srt(self, client, seed_job):
        job_id, job_dir = seed_job
        r = client.get(f"/api/jobs/{job_id}/download/test_song.srt")
        assert r.status_code == 200
        assert "Hello world" in r.text

    def test_download_not_found(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/download/nonexistent.srt")
        assert r.status_code == 404

    def test_download_path_traversal(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/download/..%2F..%2Fetc%2Fpasswd")
        assert r.status_code in (400, 404)  # 400 if traversal detected, 404 if file not found

    def test_get_file_content(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/content/test_song.srt")
        assert r.status_code == 200
        assert "Hello world" in r.json()["content"]

    def test_content_binary_blocked(self, client, seed_job):
        job_id, job_dir = seed_job
        # Create a fake mp4 file
        (job_dir / "fake.mp4").write_bytes(b"\x00" * 10)
        r = client.get(f"/api/jobs/{job_id}/content/fake.mp4")
        assert r.status_code == 400

    def test_download_zip(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/download-zip")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"


# ══════════════════════════════════════════════════════════════════════════════
#  Segments CRUD
# ══════════════════════════════════════════════════════════════════════════════


class TestSegmentsCRUD:
    def test_get_segments(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/segments")
        assert r.status_code == 200
        segs = r.json()
        assert len(segs) == 3
        assert segs[0]["text"] == "Hello world"

    def test_update_segment_text(self, client, seed_job):
        job_id = seed_job[0]
        r = client.put(f"/api/jobs/{job_id}/segments",
                       json={"index": 0, "text": "Updated text"})
        assert r.status_code == 200
        # Verify
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["text"] == "Updated text"

    def test_update_segment_timing(self, client, seed_job):
        job_id = seed_job[0]
        r = client.put(f"/api/jobs/{job_id}/segments",
                       json={"index": 1, "start": 3.0, "end": 5.5})
        assert r.status_code == 200
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[1]["start"] == 3.0
        assert segs[1]["end"] == 5.5

    def test_update_segment_out_of_range(self, client, seed_job):
        job_id = seed_job[0]
        r = client.put(f"/api/jobs/{job_id}/segments",
                       json={"index": 99, "text": "x"})
        assert r.status_code == 400

    def test_split_segment(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/split",
                        json={"index": 0, "split_at": 1.0})
        assert r.status_code == 200
        assert r.json()["new_count"] == 4

    def test_split_segment_invalid_time(self, client, seed_job):
        job_id = seed_job[0]
        # split_at outside segment bounds
        r = client.post(f"/api/jobs/{job_id}/segments/split",
                        json={"index": 0, "split_at": 10.0})
        assert r.status_code == 400

    def test_merge_segments(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/merge",
                        json={"index_a": 0, "index_b": 1})
        assert r.status_code == 200
        assert r.json()["new_count"] == 2

    def test_merge_out_of_range(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/merge",
                        json={"index_a": 0, "index_b": 99})
        assert r.status_code == 400

    def test_reorder_segment(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/reorder",
                        json={"old_index": 0, "new_index": 2})
        assert r.status_code == 200
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[2]["text"] == "Hello world"

    def test_bulk_replace(self, client, seed_job):
        job_id = seed_job[0]
        new_segs = [{"start": 0, "end": 1, "text": "Only one", "confidence": 1,
                     "has_word_timestamps": False, "words": []}]
        r = client.put(f"/api/jobs/{job_id}/segments/bulk", json=new_segs)
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_segments_not_found(self, client, _patch_dirs):
        r = client.get("/api/jobs/nonexistent/segments")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  Time-shift / Search-Replace
# ══════════════════════════════════════════════════════════════════════════════


class TestSegmentOperations:
    def test_time_shift(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/time-shift",
                        json={"offset_ms": 500})
        assert r.status_code == 200
        assert r.json()["shifted"] == 3

        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["start"] == pytest.approx(0.5, abs=0.01)

    def test_time_shift_range(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/time-shift",
                        json={"offset_ms": 1000, "range_start": 1, "range_end": 1})
        assert r.status_code == 200
        assert r.json()["shifted"] == 1

    def test_search_replace(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/search-replace",
                        json={"search": "world", "replace": "earth"})
        assert r.status_code == 200
        assert r.json()["replaced_in_segments"] == 1

        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["text"] == "Hello earth"

    def test_search_replace_case_insensitive(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/search-replace",
                        json={"search": "HELLO", "replace": "Hi", "case_sensitive": False})
        assert r.status_code == 200
        assert r.json()["replaced_in_segments"] == 1

    def test_search_replace_regex(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/search-replace",
                        json={"search": r"\bworld\b", "replace": "earth", "regex": True})
        assert r.status_code == 200
        assert r.json()["replaced_in_segments"] == 1

    def test_search_replace_invalid_regex(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/search-replace",
                        json={"search": "[invalid", "replace": "x", "regex": True})
        assert r.status_code == 400

    def test_toggle_pin(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/toggle-pin",
                        params={"index": 0})
        assert r.status_code == 200
        assert r.json()["pinned"] is True

        # Toggle again
        r = client.post(f"/api/jobs/{job_id}/segments/toggle-pin",
                        params={"index": 0})
        assert r.json()["pinned"] is False

    def test_toggle_pin_bad_index(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/segments/toggle-pin",
                        params={"index": 99})
        assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  Undo / Redo
# ══════════════════════════════════════════════════════════════════════════════


class TestUndoRedo:
    def test_undo_after_edit(self, client, seed_job):
        job_id = seed_job[0]
        # Edit
        client.put(f"/api/jobs/{job_id}/segments",
                   json={"index": 0, "text": "Changed"})
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["text"] == "Changed"

        # Undo
        r = client.post(f"/api/jobs/{job_id}/undo")
        assert r.status_code == 200
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["text"] == "Hello world"

    def test_redo_after_undo(self, client, seed_job):
        job_id = seed_job[0]
        client.put(f"/api/jobs/{job_id}/segments",
                   json={"index": 0, "text": "Changed"})
        client.post(f"/api/jobs/{job_id}/undo")
        r = client.post(f"/api/jobs/{job_id}/redo")
        assert r.status_code == 200
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["text"] == "Changed"

    def test_undo_empty_stack(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/undo")
        assert r.status_code == 400

    def test_redo_empty_stack(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/redo")
        assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
#  Dictionary
# ══════════════════════════════════════════════════════════════════════════════


class TestDictionary:
    def test_get_dictionary(self, client, _patch_dirs):
        r = client.get("/api/dictionary")
        assert r.status_code == 200
        assert "entries" in r.json()

    def test_update_and_apply_dictionary(self, client, seed_job):
        job_id = seed_job[0]
        # Update dictionary
        r = client.put("/api/dictionary",
                       json=[{"wrong": "world", "correct": "earth"}])
        assert r.status_code == 200

        # Apply to segments
        r = client.post(f"/api/jobs/{job_id}/apply-dictionary")
        assert r.status_code == 200
        assert r.json()["applied"] >= 1

        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert "earth" in segs[0]["text"]


# ══════════════════════════════════════════════════════════════════════════════
#  Gap / Overlap Detection & Fixing
# ══════════════════════════════════════════════════════════════════════════════


class TestGapsOverlaps:
    def test_detect_gaps(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/gaps-overlaps",
                       params={"min_gap_ms": 100})
        assert r.status_code == 200
        issues = r.json()
        # We have a 0.5s gap between seg 1 (end=5.0) and seg 2 (start=5.5)
        assert any(i["type"] == "gap" for i in issues)

    def test_fix_gaps_extend(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/fix-gaps",
                        params={"strategy": "extend"})
        assert r.status_code == 200
        assert r.json()["fixed"] >= 1

    def test_fix_gaps_split(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/fix-gaps",
                        params={"strategy": "split"})
        assert r.status_code == 200

    def test_fix_gaps_invalid_strategy(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/fix-gaps",
                        params={"strategy": "invalid"})
        assert r.status_code == 422  # FastAPI validation


# ══════════════════════════════════════════════════════════════════════════════
#  Speakers
# ══════════════════════════════════════════════════════════════════════════════


class TestSpeakers:
    def test_get_speakers_empty(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/speakers")
        assert r.status_code == 200
        assert r.json()["speakers"] == []

    def test_assign_speaker(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/speakers/assign",
                        params={"indices": [0, 1], "speaker": "Singer A"})
        assert r.status_code == 200

        r = client.get(f"/api/jobs/{job_id}/speakers")
        assert "Singer A" in r.json()["speakers"]


# ══════════════════════════════════════════════════════════════════════════════
#  Stats / Waveform / Report
# ══════════════════════════════════════════════════════════════════════════════


class TestStats:
    def test_get_stats(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["total_segments"] == 3
        assert body["total_words"] > 0

    def test_waveform_not_found(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/waveform")
        assert r.status_code == 404

    def test_waveform_found(self, client, seed_job):
        job_id, job_dir = seed_job
        wf = job_dir / "waveform.json"
        wf.write_text(json.dumps({"peaks": [0.1, 0.5, 0.3]}))
        r = client.get(f"/api/jobs/{job_id}/waveform")
        assert r.status_code == 200

    def test_report_not_found(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/report")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  Translate
# ══════════════════════════════════════════════════════════════════════════════


class TestTranslate:
    def test_translate_creates_file(self, client, seed_job):
        job_id, job_dir = seed_job
        r = client.post(f"/api/jobs/{job_id}/translate",
                        json={"target_language": "en"})
        assert r.status_code == 200
        assert r.json()["translated"] == 3
        assert (job_dir / "segments_en.json").exists()


# ══════════════════════════════════════════════════════════════════════════════
#  Project Export / Import
# ══════════════════════════════════════════════════════════════════════════════


class TestProjectIO:
    def test_export_project(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/project-export")
        assert r.status_code == 200
        body = r.json()
        assert "segments" in body
        assert len(body["segments"]) == 3

    def test_import_project(self, client, seed_job):
        job_id = seed_job[0]
        project = {"segments": [
            {"start": 0, "end": 1, "text": "Imported", "confidence": 1,
             "has_word_timestamps": False, "words": []}
        ]}
        content = json.dumps(project).encode()
        r = client.post(f"/api/jobs/{job_id}/project-import",
                        files={"file": ("project.json", io.BytesIO(content), "application/json")})
        assert r.status_code == 200
        assert r.json()["segments"] == 1

    def test_export_not_found(self, client, _patch_dirs):
        r = client.get("/api/jobs/nonexistent/project-export")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  Snapshots
# ══════════════════════════════════════════════════════════════════════════════


class TestSnapshots:
    def test_snapshot_lifecycle(self, client, seed_job):
        job_id = seed_job[0]

        # Save
        r = client.post(f"/api/jobs/{job_id}/snapshot", params={"name": "v1"})
        assert r.status_code == 200
        assert "v1" in r.json()["label"]

        # List
        r = client.get(f"/api/jobs/{job_id}/snapshots")
        assert r.status_code == 200
        assert len(r.json()["snapshots"]) >= 1

        # Modify segments
        client.put(f"/api/jobs/{job_id}/segments",
                   json={"index": 0, "text": "Modified"})

        # Restore
        r = client.post(f"/api/jobs/{job_id}/snapshot/restore/snap_v1")
        assert r.status_code == 200
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["text"] == "Hello world"

    def test_restore_nonexistent_snapshot(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/snapshot/restore/nonexistent")
        assert r.status_code == 404

    def test_empty_snapshots_list(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/snapshots")
        assert r.status_code == 200
        assert r.json()["snapshots"] == []


# ══════════════════════════════════════════════════════════════════════════════
#  Batch Operations: remove-short, normalize-text
# ══════════════════════════════════════════════════════════════════════════════


class TestBatchOperations:
    def test_remove_short_segments(self, client, seed_job):
        job_id, job_dir = seed_job
        # Add a very short segment
        segs = json.loads((job_dir / "segments.json").read_text())
        segs.append({"start": 9.0, "end": 9.1, "text": "x", "confidence": 0.5,
                     "has_word_timestamps": False, "words": []})
        (job_dir / "segments.json").write_text(json.dumps(segs))

        r = client.post(f"/api/jobs/{job_id}/segments/remove-short",
                        params={"min_chars": 2, "min_duration": 0.3})
        assert r.status_code == 200
        assert r.json()["removed"] >= 1

    def test_normalize_text(self, client, seed_job):
        job_id, job_dir = seed_job
        # Set a segment with bad formatting
        segs = json.loads((job_dir / "segments.json").read_text())
        segs[0]["text"] = "  hello   world  "
        (job_dir / "segments.json").write_text(json.dumps(segs))

        r = client.post(f"/api/jobs/{job_id}/segments/normalize-text")
        assert r.status_code == 200
        segs = client.get(f"/api/jobs/{job_id}/segments").json()
        assert segs[0]["text"] == "Hello world"


# ══════════════════════════════════════════════════════════════════════════════
#  Structure / Text Stats / Duplicates / Rhyme
# ══════════════════════════════════════════════════════════════════════════════


class TestAnalysis:
    def test_song_structure(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/structure")
        assert r.status_code == 200
        assert "sections" in r.json()

    def test_text_stats(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/text-stats")
        assert r.status_code == 200
        body = r.json()
        assert "total_words" in body or "word_count" in body

    def test_duplicates(self, client, seed_job):
        job_id, job_dir = seed_job
        # Add duplicate text
        segs = json.loads((job_dir / "segments.json").read_text())
        segs.append({"start": 10, "end": 12, "text": "Hello world", "confidence": 1,
                     "has_word_timestamps": False, "words": []})
        (job_dir / "segments.json").write_text(json.dumps(segs))

        r = client.get(f"/api/jobs/{job_id}/duplicates", params={"threshold": 0.8})
        assert r.status_code == 200
        assert r.json()["total_duplicates"] >= 2

    def test_rhyme_scheme(self, client, seed_job):
        job_id = seed_job[0]
        r = client.get(f"/api/jobs/{job_id}/rhyme")
        assert r.status_code == 200

    def test_auto_fix_cps(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/auto-fix-cps", params={"max_cps": 5})
        assert r.status_code == 200

    def test_fill_gaps(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/fill-gaps",
                        params={"min_gap": 0.3})
        assert r.status_code == 200

    def test_redistribute_timing(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/redistribute-timing")
        assert r.status_code == 200
        assert r.json()["count"] == 3


# ══════════════════════════════════════════════════════════════════════════════
#  Paste Lyrics
# ══════════════════════════════════════════════════════════════════════════════


class TestPasteLyrics:
    def test_paste_lyrics_align(self, client, seed_job):
        job_id = seed_job[0]
        lyrics = "Line one\nLine two\nLine three"
        r = client.post(f"/api/jobs/{job_id}/paste-lyrics",
                        content=json.dumps(lyrics),
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.json()["replaced"] == 3

    def test_paste_lyrics_empty(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/paste-lyrics",
                        content=json.dumps(""),
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_paste_lyrics_more_than_segments(self, client, seed_job):
        job_id = seed_job[0]
        lyrics = "A\nB\nC\nD\nE"
        r = client.post(f"/api/jobs/{job_id}/paste-lyrics",
                        content=json.dumps(lyrics),
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.json()["segments"] == 5  # 3 existing + 2 new


# ══════════════════════════════════════════════════════════════════════════════
#  Export Presets
# ══════════════════════════════════════════════════════════════════════════════


class TestExportPresets:
    def test_apply_youtube_preset(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/export-preset/youtube")
        assert r.status_code == 200
        exported = r.json()["exported"]
        assert any("srt" in f for f in exported)

    def test_apply_unknown_preset(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/export-preset/nonexistent")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  Regenerate ASS
# ══════════════════════════════════════════════════════════════════════════════


class TestRegenerate:
    def test_regenerate_ass(self, client, seed_job):
        job_id = seed_job[0]
        r = client.post(f"/api/jobs/{job_id}/regenerate-ass",
                        json={"formats": ["srt", "ass"]})
        assert r.status_code == 200
        assert "srt" in r.json()["regenerated"]
        assert "ass" in r.json()["regenerated"]


# ══════════════════════════════════════════════════════════════════════════════
#  Separation (Demucs) Check
# ══════════════════════════════════════════════════════════════════════════════


class TestSeparation:
    def test_check_separation(self, client, _patch_dirs):
        r = client.get("/api/separation/check")
        assert r.status_code == 200
        assert "available" in r.json()

    def test_list_audio_files(self, client, _patch_dirs, storage_root):
        # Create dummy audio file
        (storage_root / "uploads" / "test.mp3").write_bytes(b"\x00" * 10)
        r = client.get("/api/separation/audio-files")
        assert r.status_code == 200
        files = r.json()["files"]
        assert any(f["filename"] == "test.mp3" for f in files)
