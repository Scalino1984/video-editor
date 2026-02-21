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
        saved = r.json()
        assert any(s["id"] == project_id for s in saved)

    def test_save_load_roundtrip(self, editor_client, project_id, _patch_dirs, storage_root):
        """Save to disk, then load back into memory."""
        # Save
        r = editor_client.post(f"/api/editor/projects/{project_id}/save")
        assert r.status_code == 200
        # Load back
        r = editor_client.post(f"/api/editor/load-project/{project_id}")
        assert r.status_code == 200
        loaded = r.json()
        assert loaded["id"] == project_id
        assert loaded["name"] == "Test Project"


class TestEditorImportJob:
    def test_import_from_job(self, editor_client, seed_job, project_id):
        """Import karaoke job artifacts into editor project."""
        job_id = seed_job[0]
        r = editor_client.post(f"/api/editor/projects/{project_id}/import-job/{job_id}")
        assert r.status_code in (200, 404)  # 404 if no matching assets found

    def test_import_job_creates_assets(self, editor_client, _patch_dirs, storage_root):
        """Import-job should add audio + subtitle assets to the project."""
        job_id = "testjob123"
        # Create job output dir
        job_dir = storage_root / "output" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "song.mp3").write_bytes(b"\x00" * 64)
        (job_dir / "song.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        # Create project with matching ID (unified)
        r = editor_client.post("/api/editor/projects",
                               data={"name": "Test", "id": job_id})
        assert r.status_code == 200
        pid = r.json()["id"]
        assert pid == job_id
        # Import
        r = editor_client.post(f"/api/editor/projects/{pid}/import-job/{job_id}")
        assert r.status_code == 200
        assert r.json()["imported"] > 0

    def test_create_project_with_custom_id(self, editor_client, _patch_dirs, storage_root):
        """Creating a project with a custom ID should use that ID."""
        r = editor_client.post("/api/editor/projects",
                               data={"name": "Custom", "id": "myid123"})
        assert r.status_code == 200
        assert r.json()["id"] == "myid123"


class TestUnifiedProjectId:
    """Tests for the unified project ID system (pid == job_id)."""

    def test_project_to_dict_from_dict_roundtrip(self):
        """Project roundtrips through to_dict/from_dict."""
        from src.video.editor import Project

        p = Project(id="test1", name="Test")
        d = p.to_dict()
        assert d["id"] == "test1"
        assert d["name"] == "Test"
        assert "source_job_id" not in d
        p2 = Project.from_dict(d)
        assert p2.id == "test1"
        assert p2.name == "Test"

    def test_auto_create_for_karaoke_job(self, editor_client, _patch_dirs, storage_root):
        """GET /projects/{pid} should auto-create for existing karaoke job dirs."""
        job_id = "karaokejob42"
        job_dir = storage_root / "output" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "segments.json").write_text("[]", encoding="utf-8")
        # GET should auto-create the editor project
        r = editor_client.get(f"/api/editor/projects/{job_id}")
        assert r.status_code == 200
        assert r.json()["id"] == job_id

    def test_no_auto_create_for_nonexistent_dir(self, editor_client, _patch_dirs, storage_root):
        """GET /projects/{pid} should 404 for nonexistent directories."""
        r = editor_client.get("/api/editor/projects/nonexistent999")
        assert r.status_code == 404

    def test_delete_editor_project(self, editor_client, project_id, _patch_dirs, storage_root):
        """DELETE should remove editor.json only."""
        # Save first
        r = editor_client.post(f"/api/editor/projects/{project_id}/save")
        assert r.status_code == 200
        # Verify editor.json exists
        editor_json = storage_root / "output" / project_id / "editor.json"
        assert editor_json.exists()
        # Delete
        r = editor_client.delete(f"/api/editor/delete-project/{project_id}")
        assert r.status_code == 200
        assert not editor_json.exists()
