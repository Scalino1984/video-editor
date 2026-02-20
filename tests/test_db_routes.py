"""Library & DB route integration tests — /api/library/*, /api/media/*, /api/render-*, /api/file-registry/*.

Covers: library CRUD, media registry, file registry, render video (429 backpressure).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def lib_client(db, _patch_dirs):
    """TestClient with library DB and patched output dirs initialized."""
    from main import app
    from starlette.testclient import TestClient
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def lib_record(_patch_dirs, storage_root):
    """Seed a project directory with project.json and return its job_id."""
    from src.api.karaoke_project import KaraokeProject, ProcessingSettings, Artifact, save_project
    job_id = "test-lib-0001"
    job_dir = storage_root / "output" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "segments.json").write_text(
        json.dumps([{"start": 0, "end": 2.5, "text": "Hello", "confidence": 0.95,
                      "has_word_timestamps": False, "words": []}]),
        encoding="utf-8",
    )
    srt_text = "1\n00:00:00,000 --> 00:00:02,500\nHello\n"
    (job_dir / "test_song.srt").write_text(srt_text, encoding="utf-8")
    proj = KaraokeProject(
        id=job_id,
        name="test_song",
        source_filename="test_song.mp3",
        backend_used="voxtral",
        language_detected="de",
        segments_count=1,
        duration_sec=10.5,
        avg_confidence=0.95,
        settings=ProcessingSettings(backend="voxtral", language="de"),
        artifacts=[Artifact(filename="test_song.srt", format="srt", size=len(srt_text))],
    )
    save_project(proj)
    return job_id


class TestLibraryCRUD:
    def test_list_library(self, lib_client, lib_record):
        r = lib_client.get("/api/library")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        assert any(item["id"] == lib_record for item in body["items"])

    def test_get_library_item(self, lib_client, lib_record):
        r = lib_client.get(f"/api/library/{lib_record}")
        assert r.status_code == 200
        assert r.json()["id"] == lib_record

    def test_get_library_item_not_found(self, lib_client):
        r = lib_client.get("/api/library/nonexistent-id")
        assert r.status_code == 404

    def test_patch_library_item(self, lib_client, lib_record):
        r = lib_client.patch(f"/api/library/{lib_record}",
                             json={"title": "New Title"})
        assert r.status_code == 200

        r2 = lib_client.get(f"/api/library/{lib_record}")
        assert r2.json()["title"] == "New Title"

    def test_delete_library_item(self, lib_client, lib_record):
        r = lib_client.delete(f"/api/library/{lib_record}")
        assert r.status_code == 200

    def test_library_search(self, lib_client, lib_record):
        r = lib_client.get("/api/library", params={"q": "test_song"})
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_library_pagination(self, lib_client, lib_record):
        r = lib_client.get("/api/library", params={"limit": 1, "offset": 0})
        assert r.status_code == 200
        assert r.json()["limit"] == 1


class TestLibrarySRT:
    def test_download_srt(self, lib_client, lib_record):
        r = lib_client.get(f"/api/library/{lib_record}/srt")
        assert r.status_code == 200
        assert "Hello" in r.text


class TestMediaRegistry:
    def test_list_media(self, lib_client, db):
        r = lib_client.get("/api/media")
        assert r.status_code == 200

    def test_get_media_not_found(self, lib_client, db):
        r = lib_client.get("/api/media/nonexistent-media-id")
        assert r.status_code == 404


class TestRenderVideo:
    def test_render_video_missing_files(self, lib_client):
        """Render without required files returns error."""
        r = lib_client.post("/api/render-video", data={"subtitle_file": "nonexistent.srt"})
        assert r.status_code in (400, 404, 422)


class TestFileRegistry:
    def test_list_file_registry(self, lib_client, db):
        r = lib_client.get("/api/file-registry")
        assert r.status_code == 200

    def test_cleanup_file_registry(self, lib_client, db):
        r = lib_client.post("/api/file-registry/cleanup")
        assert r.status_code == 200
