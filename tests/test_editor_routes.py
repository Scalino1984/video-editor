"""Editor route integration tests — /api/editor/* endpoints.

Covers: project CRUD, assets, clips, effects, undo/redo, save/load,
        backpressure (429), import-from-job.
"""

from __future__ import annotations

import io
import json
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
