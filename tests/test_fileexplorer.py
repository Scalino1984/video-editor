r"""Tests for file explorer, navigation, karaoke fill render, and font/size persistence.

Covers:
- File explorer endpoints (list saved, load, delete)
- Navigation routes (/, /editor, /files)
- Karaoke progressive fill \kf color direction in ASS output
- Font/size persistence via PUT /api/editor/projects/{pid}
- Sub-settings endpoint type coercion
"""

from __future__ import annotations

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
                           data={"name": "Test Project", "width": 1920, "height": 1080, "fps": 30})
    assert r.status_code == 200
    return r.json()["id"]


# ── Navigation routes ────────────────────────────────────────────────────────

class TestNavigationRoutes:
    def test_index_page(self, editor_client):
        r = editor_client.get("/")
        assert r.status_code == 200
        assert "Karaoke" in r.text

    def test_editor_page(self, editor_client):
        r = editor_client.get("/editor")
        assert r.status_code == 200
        assert "Video Editor" in r.text

    def test_fileexplorer_page(self, editor_client):
        r = editor_client.get("/files")
        assert r.status_code == 200
        assert "File Explorer" in r.text

    def test_index_has_files_link(self, editor_client):
        r = editor_client.get("/")
        assert '/files' in r.text

    def test_editor_has_files_link(self, editor_client):
        r = editor_client.get("/editor")
        assert '/files' in r.text

    def test_fileexplorer_has_editor_link(self, editor_client):
        r = editor_client.get("/files")
        assert '/editor' in r.text

    def test_fileexplorer_has_karaoke_link(self, editor_client):
        r = editor_client.get("/files")
        assert 'href="/"' in r.text


# ── File explorer ────────────────────────────────────────────────────────────

class TestFileExplorer:
    def test_list_saved_projects_empty(self, editor_client):
        r = editor_client.get("/api/editor/saved-projects")
        assert r.status_code == 200
        assert r.json() == []

    def test_save_and_list_saved(self, editor_client, project_id, _patch_dirs):
        # Save the project to disk
        r = editor_client.post(f"/api/editor/projects/{project_id}/save")
        assert r.status_code == 200

        # List saved projects
        r = editor_client.get("/api/editor/saved-projects")
        assert r.status_code == 200
        saved = r.json()
        assert len(saved) >= 1
        proj = saved[0]
        assert "filename" in proj
        assert "name" in proj
        assert proj["name"] == "Test Project"

    def test_load_saved_project(self, editor_client, project_id, _patch_dirs):
        # Save
        editor_client.post(f"/api/editor/projects/{project_id}/save")
        saved = editor_client.get("/api/editor/saved-projects").json()
        filename = saved[0]["filename"]

        # Load
        r = editor_client.post(f"/api/editor/load-project/{filename}")
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["name"] == "Test Project"

    def test_delete_saved_project(self, editor_client, project_id, _patch_dirs):
        # Save
        editor_client.post(f"/api/editor/projects/{project_id}/save")
        saved = editor_client.get("/api/editor/saved-projects").json()
        filename = saved[0]["filename"]

        # Delete
        r = editor_client.delete(f"/api/editor/delete-project/{filename}")
        assert r.status_code == 200
        assert r.json()["deleted"] == filename

        # Verify deleted
        saved = editor_client.get("/api/editor/saved-projects").json()
        assert all(s["filename"] != filename for s in saved)

    def test_delete_nonexistent_project(self, editor_client):
        r = editor_client.delete("/api/editor/delete-project/nonexistent.json")
        assert r.status_code == 404

    def test_delete_path_traversal_blocked(self, editor_client):
        r = editor_client.delete("/api/editor/delete-project/..%2F..%2Fetc%2Fpasswd")
        assert r.status_code in (400, 404)

    def test_delete_non_json_blocked(self, editor_client, _patch_dirs, storage_root):
        # Create a non-JSON file in projects dir
        proj_dir = storage_root / "editor" / "projects"
        (proj_dir / "test.txt").write_text("not json")
        r = editor_client.delete("/api/editor/delete-project/test.txt")
        assert r.status_code == 400


# ── Karaoke fill render ─────────────────────────────────────────────────────

class TestKaraokeFillRender:
    def test_styled_ass_has_correct_kf_colors(self, _patch_dirs, storage_root):
        r"""Verify \\kf tags include \\1c (highlight) and \\2c (base) for correct fill direction."""
        from src.video.editor import generate_styled_ass, Project

        p = Project(
            id="test",
            name="test",
            sub_color="&H00FFFFFF",          # white (base)
            sub_highlight_color="&H0000FFFF",  # yellow (highlight)
            sub_font="Arial",
            sub_size=48,
        )

        # Create a subtitle file with word timestamps
        sub_path = storage_root / "editor" / "test.srt"
        sub_path.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello world\n", encoding="utf-8")

        out_path = storage_root / "editor" / "styled.ass"

        # Provide segments with word-level timestamps
        from src.transcription.base import TranscriptSegment, WordInfo
        segs = [
            TranscriptSegment(
                start=0.0, end=2.0, text="Hello world",
                has_word_timestamps=True,
                words=[
                    WordInfo(start=0.0, end=0.8, word="Hello"),
                    WordInfo(start=0.9, end=1.8, word="world"),
                ],
            ),
        ]

        result = generate_styled_ass(sub_path, p, out_path, segments=segs)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        # Every karaoke word must have \1c (highlight=yellow) and \2c (base=white)
        assert "\\1c&H0000FFFF" in content, "Missing \\1c highlight color override"
        assert "\\2c&H00FFFFFF" in content, "Missing \\2c base color override"
        # Verify \kf tags are present
        assert "\\kf" in content, "Missing \\kf karaoke tags"

    def test_styled_ass_non_karaoke_no_color_overrides(self, _patch_dirs, storage_root):
        """Non-karaoke text should not have \1c/\2c overrides."""
        from src.video.editor import generate_styled_ass, Project

        p = Project(id="test2", name="test2")
        sub_path = storage_root / "editor" / "test2.srt"
        sub_path.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

        out_path = storage_root / "editor" / "styled2.ass"
        result = generate_styled_ass(sub_path, p, out_path)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        # Non-karaoke: no inline color overrides
        assert "\\1c" not in content.split("[Events]")[1]
        assert "\\kf" not in content

    def test_kf_fill_direction_matches_preview(self, _patch_dirs, storage_root):
        r"""In ASS, \\kf fills from Secondary to Primary.
        \\1c=highlight (Primary=filled), \\2c=base (Secondary=unfilled).
        This matches the HTML preview behavior."""
        from src.video.editor import generate_styled_ass, Project
        from src.transcription.base import TranscriptSegment, WordInfo

        p = Project(
            id="test3", name="test3",
            sub_color="&H00FFFFFF",
            sub_highlight_color="&H0000FF00",  # green highlight
        )
        sub_path = storage_root / "editor" / "test3.srt"
        sub_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8")
        out_path = storage_root / "editor" / "styled3.ass"

        segs = [TranscriptSegment(
            start=0.0, end=1.0, text="Test",
            has_word_timestamps=True,
            words=[WordInfo(start=0.0, end=1.0, word="Test")],
        )]
        result = generate_styled_ass(sub_path, p, out_path, segments=segs)
        content = result.read_text(encoding="utf-8")

        # \1c should be the highlight (green), \2c should be the base (white)
        assert "\\1c&H0000FF00" in content
        assert "\\2c&H00FFFFFF" in content


# ── Font/Size persistence ────────────────────────────────────────────────────

class TestFontSizePersistence:
    def test_update_sub_font_via_put(self, editor_client, project_id):
        r = editor_client.put(f"/api/editor/projects/{project_id}",
                              json={"sub_font": "DejaVu Sans"})
        assert r.status_code == 200
        assert "sub_font" in r.json()["changed"]

        # Reload and verify
        r = editor_client.get(f"/api/editor/projects/{project_id}")
        assert r.json()["sub_font"] == "DejaVu Sans"

    def test_update_sub_size_via_put(self, editor_client, project_id):
        r = editor_client.put(f"/api/editor/projects/{project_id}",
                              json={"sub_size": 72})
        assert r.status_code == 200

        r = editor_client.get(f"/api/editor/projects/{project_id}")
        assert r.json()["sub_size"] == 72

    def test_sub_size_stored_as_int(self, editor_client, project_id):
        """Even if sub_size comes as string, it should be coerced to int."""
        r = editor_client.put(f"/api/editor/projects/{project_id}",
                              json={"sub_size": "64"})
        assert r.status_code == 200

        r = editor_client.get(f"/api/editor/projects/{project_id}")
        assert r.json()["sub_size"] == 64
        assert isinstance(r.json()["sub_size"], int)

    def test_sub_settings_endpoint(self, editor_client, project_id):
        r = editor_client.put(f"/api/editor/projects/{project_id}/sub-settings",
                              json={"sub_font": "Courier New", "sub_size": 56})
        assert r.status_code == 200
        body = r.json()
        assert body["sub_font"] == "Courier New"
        assert body["sub_size"] == 56

    def test_sub_settings_includes_bg_and_ypercent(self, editor_client, project_id):
        """sub_y_percent, sub_bg_enabled, sub_bg_color should be accepted."""
        r = editor_client.put(f"/api/editor/projects/{project_id}/sub-settings",
                              json={"sub_y_percent": 50, "sub_bg_enabled": False,
                                    "sub_bg_color": "&H00000000"})
        assert r.status_code == 200
        body = r.json()
        assert body["sub_y_percent"] == 50
        assert body["sub_bg_enabled"] is False

    def test_font_in_styled_ass(self, _patch_dirs, storage_root):
        """Font and size from project must appear in generated ASS style line."""
        from src.video.editor import generate_styled_ass, Project

        p = Project(id="ftest", name="ftest", sub_font="Comic Sans MS", sub_size=64)
        sub_path = storage_root / "editor" / "ftest.srt"
        sub_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8")
        out_path = storage_root / "editor" / "ftest.ass"

        result = generate_styled_ass(sub_path, p, out_path)
        content = result.read_text(encoding="utf-8")

        # Check ASS style line contains the font and size
        assert "Comic Sans MS" in content
        assert ",64," in content  # size appears after font name in ASS style


# ── Sync: Karaoke edit persists to editor ────────────────────────────────────

class TestKaraokeEditorSync:
    def test_save_reload_preserves_sub_settings(self, editor_client, project_id, _patch_dirs):
        """Settings changed before save must be present after load."""
        # Update settings
        editor_client.put(f"/api/editor/projects/{project_id}",
                          json={"sub_font": "Noto Sans", "sub_size": 60,
                                "sub_highlight_color": "&H00FF00FF"})

        # Save to disk
        editor_client.post(f"/api/editor/projects/{project_id}/save")

        # List and load
        saved = editor_client.get("/api/editor/saved-projects").json()
        assert len(saved) >= 1
        filename = saved[0]["filename"]

        loaded = editor_client.post(f"/api/editor/load-project/{filename}").json()
        assert loaded["sub_font"] == "Noto Sans"
        assert loaded["sub_size"] == 60
        assert loaded["sub_highlight_color"] == "&H00FF00FF"
