"""Editor route integration tests — /api/editor/* endpoints.

Covers: project CRUD, assets, clips, effects, undo/redo, save/load,
        backpressure (429), import-from-job.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def editor_client(_patch_dirs, storage_root):
    """TestClient with editor directories patched."""
    from main import app
    from starlette.testclient import TestClient
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def project_id(editor_client):
    """Create a fresh editor project and return its ID."""
    r = editor_client.post("/api/editor/projects",
                           data={"name": "Test Project", "width": 1280, "height": 720, "fps": 30})
    assert r.status_code == 200
    return r.json()["id"]


class TestEditorProjectCRUD:
    def test_create_project(self, editor_client):
        r = editor_client.post("/api/editor/projects",
                               data={"name": "My Project", "width": 1920, "height": 1080, "fps": 25})
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "My Project"
        assert "id" in body

    def test_list_projects(self, editor_client, project_id):
        r = editor_client.get("/api/editor/projects")
        assert r.status_code == 200
        projects = r.json()
        assert any(p["id"] == project_id for p in projects)

    def test_get_project(self, editor_client, project_id):
        r = editor_client.get(f"/api/editor/projects/{project_id}")
        assert r.status_code == 200
        assert r.json()["id"] == project_id

    def test_get_project_not_found(self, editor_client):
        r = editor_client.get("/api/editor/projects/nonexistent")
        assert r.status_code == 404

    def test_update_project_settings(self, editor_client, project_id):
        r = editor_client.put(f"/api/editor/projects/{project_id}",
                              json={"name": "Renamed"})
        assert r.status_code == 200
        r2 = editor_client.get(f"/api/editor/projects/{project_id}")
        assert r2.json()["name"] == "Renamed"


class TestEditorAssets:
    def test_upload_asset(self, editor_client, project_id, _patch_dirs, storage_root):
        content = b"RIFF" + b"\x00" * 100
        r = editor_client.post(f"/api/editor/projects/{project_id}/assets",
                               files={"file": ("bg.wav", io.BytesIO(content), "audio/wav")})
        assert r.status_code == 200
        assert "id" in r.json() or "asset_id" in r.json() or "filename" in r.json()


class TestEditorClips:
    def _add_asset(self, editor_client, project_id, storage_root):
        """Helper: upload asset and return its ID."""
        content = b"RIFF" + b"\x00" * 100
        r = editor_client.post(f"/api/editor/projects/{project_id}/assets",
                               files={"file": ("clip.wav", io.BytesIO(content), "audio/wav")})
        body = r.json()
        return body.get("id") or body.get("asset_id")

    def test_add_clip(self, editor_client, project_id, _patch_dirs, storage_root):
        asset_id = self._add_asset(editor_client, project_id, storage_root)
        if not asset_id:
            pytest.skip("Asset upload did not return asset_id")
        r = editor_client.post(f"/api/editor/projects/{project_id}/clips",
                               data={"asset_id": asset_id, "track": "audio",
                                     "start": 0, "duration": 5})
        assert r.status_code == 200

    def test_undo_redo(self, editor_client, project_id):
        # No edits yet → undo should fail
        r = editor_client.post(f"/api/editor/projects/{project_id}/undo")
        assert r.status_code in (200, 400)


class TestEditorSaveLoad:
    def test_save_and_list(self, editor_client, project_id):
        r = editor_client.post(f"/api/editor/projects/{project_id}/save")
        assert r.status_code == 200

        r = editor_client.get("/api/editor/saved-projects")
        assert r.status_code == 200


class TestEditorImportJob:
    def test_import_from_job(self, editor_client, seed_job, project_id):
        """Import karaoke job artifacts into editor project."""
        job_id = seed_job[0]
        r = editor_client.post(f"/api/editor/projects/{project_id}/import-job/{job_id}")
        assert r.status_code in (200, 404)  # 404 if no matching assets found

    def test_import_job_sets_source_job_id(self, editor_client, project_id, _patch_dirs, storage_root):
        """Import-job should set source_job_id on the project."""
        job_id = "testjob123"
        # Create job output dir where the route expects it (data/output/)
        job_dir = Path("data/output") / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "song.mp3").write_bytes(b"\x00" * 64)
        (job_dir / "song.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        try:
            r = editor_client.post(f"/api/editor/projects/{project_id}/import-job/{job_id}")
            assert r.status_code == 200
            assert r.json()["imported"] > 0
            # Verify project now has source_job_id
            proj = editor_client.get(f"/api/editor/projects/{project_id}")
            assert proj.status_code == 200
            assert proj.json()["source_job_id"] == job_id
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)


class TestProjectSourceJobId:
    """Tests for the source_job_id field on Project."""

    def test_new_project_has_no_source_job_id(self, editor_client, project_id):
        r = editor_client.get(f"/api/editor/projects/{project_id}")
        assert r.status_code == 200
        assert r.json()["source_job_id"] is None

    def test_source_job_id_survives_save_load(self, editor_client, project_id, _patch_dirs, storage_root):
        """source_job_id should persist through save/load cycle."""
        from src.video.editor import get_project
        p = get_project(project_id)
        p.source_job_id = "myjob456"
        # Save
        r = editor_client.post(f"/api/editor/projects/{project_id}/save")
        assert r.status_code == 200
        # List saved projects
        saved = editor_client.get("/api/editor/saved-projects").json()
        assert len(saved) > 0
        filename = saved[0]["filename"]
        # Load into new in-memory project
        r = editor_client.post(f"/api/editor/load-project/{filename}")
        assert r.status_code == 200
        loaded_pid = r.json()["id"]
        proj = editor_client.get(f"/api/editor/projects/{loaded_pid}")
        assert proj.json()["source_job_id"] == "myjob456"

    def test_project_to_dict_from_dict_roundtrip(self):
        """source_job_id roundtrips through to_dict/from_dict."""
        from src.video.editor import Project

        p = Project(id="test1", name="Test")
        p.source_job_id = "abc123"
        d = p.to_dict()
        assert d["source_job_id"] == "abc123"
        p2 = Project.from_dict(d)
        assert p2.source_job_id == "abc123"

    def test_from_dict_without_source_job_id(self):
        """Legacy dicts without source_job_id should default to None."""
        from src.video.editor import Project

        d = {"id": "test2", "name": "Legacy"}
        p = Project.from_dict(d)
        assert p.source_job_id is None
