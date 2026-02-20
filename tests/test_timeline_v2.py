"""Tests for Timeline v2: tracks, layers, upgrade-on-read, chat parser, and API endpoints."""

from __future__ import annotations

import json

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
                           data={"name": "Test V2", "width": 1280, "height": 720, "fps": 30})
    assert r.status_code == 200
    return r.json()["id"]


# ── Data model tests ──────────────────────────────────────────────────────────

class TestTimelineV2DataModel:
    """Test v2 data model: Track dataclass, Project with tracks."""

    def test_new_project_has_default_tracks(self):
        from src.video.editor import create_project
        p = create_project("Test")
        assert p.timeline_version == 2
        assert len(p.tracks) == 3  # V1, A1, S1
        types = {t.type for t in p.tracks}
        assert types == {"video", "audio", "subtitle"}

    def test_project_to_dict_includes_tracks(self):
        from src.video.editor import create_project
        p = create_project("Test")
        d = p.to_dict()
        assert "timeline_version" in d
        assert d["timeline_version"] == 2
        assert "tracks" in d
        assert len(d["tracks"]) == 3

    def test_project_from_dict_roundtrip(self):
        from src.video.editor import create_project, Project
        p = create_project("Roundtrip")
        d = p.to_dict()
        p2 = Project.from_dict(d)
        assert p2.timeline_version == 2
        assert len(p2.tracks) == len(p.tracks)
        for t1, t2 in zip(p.tracks, p2.tracks):
            assert t1.id == t2.id
            assert t1.type == t2.type
            assert t1.name == t2.name

    def test_track_to_dict(self):
        from src.video.editor import Track
        t = Track(id="abc", type="video", name="V1", index=0)
        d = t.to_dict()
        assert d["id"] == "abc"
        assert d["type"] == "video"
        assert d["enabled"] is True
        assert d["locked"] is False


# ── Legacy v1 → v2 upgrade tests ─────────────────────────────────────────────

class TestLegacyUpgrade:
    """Test v1 → v2 upgrade-on-read (legacy_project_to_v2)."""

    def test_v1_project_gets_upgraded(self):
        from src.video.editor import legacy_project_to_v2
        v1 = {
            "id": "test1",
            "name": "Old Project",
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "assets": {},
            "clips": [
                {"id": "c1", "asset_id": "a1", "track": "video",
                 "start": 0, "duration": 5, "effects": []},
                {"id": "c2", "asset_id": "a2", "track": "audio",
                 "start": 0, "duration": 5, "effects": []},
            ],
        }
        v2 = legacy_project_to_v2(v1)
        assert v2["timeline_version"] == 2
        assert "tracks" in v2
        assert len(v2["tracks"]) >= 2  # at least video + audio
        track_types = {t["type"] for t in v2["tracks"]}
        assert "video" in track_types
        assert "audio" in track_types

    def test_v2_project_unchanged(self):
        from src.video.editor import legacy_project_to_v2
        v2 = {
            "id": "test2",
            "name": "New Project",
            "timeline_version": 2,
            "tracks": [{"id": "t1", "type": "video", "name": "V1", "index": 0,
                         "enabled": True, "locked": False, "mute": False,
                         "solo": False, "opacity": 1.0, "gain_db": 0.0}],
            "clips": [],
            "assets": {},
        }
        result = legacy_project_to_v2(v2)
        assert result["timeline_version"] == 2
        assert len(result["tracks"]) == 1
        assert result["tracks"][0]["id"] == "t1"

    def test_from_dict_creates_default_tracks_for_legacy(self):
        from src.video.editor import Project
        v1 = {
            "id": "legacy1",
            "name": "Legacy",
            "clips": [],
            "assets": {},
        }
        p = Project.from_dict(v1)
        assert p.timeline_version == 2
        assert len(p.tracks) == 3  # default V1 + A1 + S1


# ── Track management tests ───────────────────────────────────────────────────

class TestTrackManagement:
    """Test add_track, remove_track, update_track, reorder_tracks functions."""

    def test_add_track(self):
        from src.video.editor import create_project, add_track
        p = create_project("Track Test")
        initial_count = len(p.tracks)
        t = add_track(p.id, "video", name="V2")
        assert t is not None
        assert t.type == "video"
        assert t.name == "V2"
        assert len(p.tracks) == initial_count + 1

    def test_add_track_auto_name(self):
        from src.video.editor import create_project, add_track
        p = create_project("Auto Name")
        t = add_track(p.id, "audio")
        assert t is not None
        assert t.name == "A2"  # A1 already exists from defaults

    def test_add_track_invalid_type(self):
        from src.video.editor import create_project, add_track
        p = create_project("Invalid")
        t = add_track(p.id, "invalid_type")
        assert t is None

    def test_remove_empty_track(self):
        from src.video.editor import create_project, add_track, remove_track
        p = create_project("Remove Test")
        t = add_track(p.id, "video", name="V2")
        count_before = len(p.tracks)
        ok = remove_track(p.id, t.id)
        assert ok is True
        assert len(p.tracks) == count_before - 1

    def test_remove_nonempty_track_requires_force(self):
        from src.video.editor import (
            create_project, add_track, add_clip, remove_track, add_asset,
        )
        from pathlib import Path
        p = create_project("Force Test")
        # Add an asset and clip to video track
        # Note: since clips use track type string, and we have only one video track,
        # removing it with clips present requires force
        # We simulate by having only 1 video track
        vid_tracks = [t for t in p.tracks if t.type == "video"]
        assert len(vid_tracks) == 1
        # Without actual clips, track is empty — add a dummy
        from src.video.editor import Clip, _push_undo
        _push_undo(p.id)
        p.clips.append(Clip(id="dummy", asset_id="a1", track="video", start=0, duration=5))

        ok = remove_track(p.id, vid_tracks[0].id, force=False)
        assert ok is False  # Can't remove non-empty track without force

        ok = remove_track(p.id, vid_tracks[0].id, force=True)
        assert ok is True

    def test_update_track(self):
        from src.video.editor import create_project, update_track
        p = create_project("Update Test")
        t = p.tracks[0]
        result = update_track(p.id, t.id, name="Renamed", locked=True)
        assert result is not None
        assert result.name == "Renamed"
        assert result.locked is True

    def test_reorder_tracks(self):
        from src.video.editor import create_project, reorder_tracks
        p = create_project("Reorder")
        ids = [t.id for t in sorted(p.tracks, key=lambda t: t.index)]
        # Reverse order
        ok = reorder_tracks(p.id, list(reversed(ids)))
        assert ok is True
        new_order = [t.id for t in sorted(p.tracks, key=lambda t: t.index)]
        assert new_order == list(reversed(ids))

    def test_undo_after_add_track(self):
        from src.video.editor import create_project, add_track, undo
        p = create_project("Undo Track")
        initial_count = len(p.tracks)
        add_track(p.id, "audio", name="A2")
        assert len(p.tracks) == initial_count + 1
        ok = undo(p.id)
        assert ok is True
        from src.video.editor import get_project
        p2 = get_project(p.id)
        assert len(p2.tracks) == initial_count


# ── Track API endpoint tests ─────────────────────────────────────────────────

class TestTrackAPI:
    """Test REST API endpoints for track management."""

    def test_add_track_endpoint(self, editor_client, project_id):
        r = editor_client.post(
            f"/api/editor/projects/{project_id}/tracks",
            json={"type": "video", "name": "V2"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["type"] == "video"
        assert body["name"] == "V2"
        assert "id" in body

    def test_add_track_invalid_type(self, editor_client, project_id):
        r = editor_client.post(
            f"/api/editor/projects/{project_id}/tracks",
            json={"type": "invalid"},
        )
        assert r.status_code == 400

    def test_remove_track_endpoint(self, editor_client, project_id):
        # Add a track first
        r = editor_client.post(
            f"/api/editor/projects/{project_id}/tracks",
            json={"type": "audio", "name": "A2"},
        )
        track_id = r.json()["id"]

        # Remove it
        r = editor_client.delete(
            f"/api/editor/projects/{project_id}/tracks/{track_id}",
        )
        assert r.status_code == 200
        assert r.json()["removed"] == track_id

    def test_update_track_endpoint(self, editor_client, project_id):
        # Get project to find a track
        r = editor_client.get(f"/api/editor/projects/{project_id}")
        tracks = r.json()["tracks"]
        track_id = tracks[0]["id"]

        r = editor_client.put(
            f"/api/editor/projects/{project_id}/tracks/{track_id}",
            json={"name": "Renamed Track", "locked": True},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Renamed Track"
        assert r.json()["locked"] is True

    def test_reorder_tracks_endpoint(self, editor_client, project_id):
        r = editor_client.get(f"/api/editor/projects/{project_id}")
        tracks = r.json()["tracks"]
        track_ids = [t["id"] for t in tracks]

        # Reverse order
        r = editor_client.post(
            f"/api/editor/projects/{project_id}/tracks/reorder",
            json={"track_ids": list(reversed(track_ids))},
        )
        assert r.status_code == 200
        result_ids = [t["id"] for t in r.json()["tracks"]]
        assert result_ids == list(reversed(track_ids))

    def test_project_includes_timeline_version(self, editor_client, project_id):
        r = editor_client.get(f"/api/editor/projects/{project_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["timeline_version"] == 2
        assert "tracks" in body
        assert len(body["tracks"]) == 3


# ── Chat parser tests ────────────────────────────────────────────────────────

class TestChatParser:
    """Test rule-based chat command parser for track/layer commands."""

    def test_parse_add_video(self):
        from src.video.editor import create_project
        from src.video.ai_tools import parse_chat_command
        p = create_project("Parse Test")
        result = parse_chat_command("+ video", p.id)
        assert result is not None
        assert len(result) == 1
        assert result[0]["action"] == "add_track"
        assert result[0]["type"] == "video"

    def test_parse_add_audio_german(self):
        from src.video.editor import create_project
        from src.video.ai_tools import parse_chat_command
        p = create_project("Parse DE")
        result = parse_chat_command("füge eine audio spur hinzu", p.id)
        assert result is not None
        assert result[0]["action"] == "add_track"
        assert result[0]["type"] == "audio"

    def test_parse_add_subtitle_english(self):
        from src.video.editor import create_project
        from src.video.ai_tools import parse_chat_command
        p = create_project("Parse EN")
        result = parse_chat_command("add subtitle track", p.id)
        assert result is not None
        assert result[0]["action"] == "add_track"
        assert result[0]["type"] == "subtitle"

    def test_parse_neue_video_ebene(self):
        from src.video.editor import create_project
        from src.video.ai_tools import parse_chat_command
        p = create_project("Ebene")
        result = parse_chat_command("neue video ebene", p.id)
        assert result is not None
        assert result[0]["action"] == "add_track"
        assert result[0]["type"] == "video"

    def test_parse_remove_by_index(self):
        from src.video.editor import create_project
        from src.video.ai_tools import parse_chat_command
        p = create_project("Remove Idx")
        result = parse_chat_command("- ebene 1", p.id)
        assert result is not None
        assert result[0]["action"] == "remove_track"

    def test_parse_remove_subtitle(self):
        from src.video.editor import create_project
        from src.video.ai_tools import parse_chat_command
        p = create_project("Remove Sub")
        result = parse_chat_command("- subtitle", p.id)
        assert result is not None
        assert result[0]["action"] == "remove_track"

    def test_parse_undo(self):
        from src.video.editor import create_project
        from src.video.ai_tools import parse_chat_command
        p = create_project("Undo")
        result = parse_chat_command("undo", p.id)
        assert result is not None
        assert result[0]["action"] == "undo"

    def test_parse_unknown_returns_none(self):
        from src.video.editor import create_project
        from src.video.ai_tools import parse_chat_command
        p = create_project("Unknown")
        result = parse_chat_command("make this video look cool", p.id)
        assert result is None

    def test_parse_remove_with_force(self):
        from src.video.editor import create_project
        from src.video.ai_tools import parse_chat_command
        p = create_project("Force Remove")
        result = parse_chat_command("- ebene 1 force", p.id)
        assert result is not None
        assert result[0]["action"] == "remove_track"
        assert result[0]["force"] is True


# ── Chat executor tests ──────────────────────────────────────────────────────

class TestChatExecutor:
    """Test that _execute_action handles track actions correctly."""

    def test_execute_add_track(self):
        from src.video.editor import create_project, get_project
        from src.video.ai_tools import _execute_action
        p = create_project("Exec Add")
        initial_count = len(p.tracks)
        result = _execute_action(p.id, {"action": "add_track", "type": "video"})
        assert "hinzugefügt" in result
        p2 = get_project(p.id)
        assert len(p2.tracks) == initial_count + 1

    def test_execute_remove_track(self):
        from src.video.editor import create_project, add_track, get_project
        from src.video.ai_tools import _execute_action
        p = create_project("Exec Remove")
        t = add_track(p.id, "audio", name="A2")
        result = _execute_action(p.id, {"action": "remove_track", "track_id": t.id})
        assert "entfernt" in result

    def test_execute_rename_track(self):
        from src.video.editor import create_project, get_project
        from src.video.ai_tools import _execute_action
        p = create_project("Exec Rename")
        tid = p.tracks[0].id
        result = _execute_action(p.id, {"action": "rename_track", "track_id": tid, "name": "My Track"})
        assert "umbenannt" in result

    def test_execute_unknown_action(self):
        from src.video.editor import create_project
        from src.video.ai_tools import _execute_action
        p = create_project("Unknown")
        result = _execute_action(p.id, {"action": "destroy_everything"})
        assert "Unbekannte" in result

    def test_execute_invalid_track_type(self):
        from src.video.editor import create_project
        from src.video.ai_tools import _execute_action
        p = create_project("Invalid Type")
        result = _execute_action(p.id, {"action": "add_track", "type": "magic"})
        assert "Ungültig" in result


# ── Undo/redo for chat-triggered changes ──────────────────────────────────────

class TestChatUndoRedo:
    """Test that undo/redo works after chat-triggered actions."""

    def test_undo_after_chat_add_track(self):
        from src.video.editor import create_project, get_project, undo
        from src.video.ai_tools import _execute_action
        p = create_project("Chat Undo")
        initial = len(p.tracks)
        _execute_action(p.id, {"action": "add_track", "type": "video"})
        assert len(get_project(p.id).tracks) == initial + 1
        ok = undo(p.id)
        assert ok is True
        assert len(get_project(p.id).tracks) == initial

    def test_undo_redo_cycle(self):
        from src.video.editor import create_project, get_project, undo, redo
        from src.video.ai_tools import _execute_action
        p = create_project("Cycle")
        initial = len(p.tracks)
        _execute_action(p.id, {"action": "add_track", "type": "audio"})
        assert len(get_project(p.id).tracks) == initial + 1
        undo(p.id)
        assert len(get_project(p.id).tracks) == initial
        redo(p.id)
        assert len(get_project(p.id).tracks) == initial + 1


# ── Deterministic sorting test ────────────────────────────────────────────────

class TestDeterministicSorting:
    """Test that tracks and clips are sorted deterministically."""

    def test_tracks_sorted_by_index(self):
        from src.video.editor import create_project, add_track
        p = create_project("Sort")
        add_track(p.id, "video", name="V2", index=10)
        add_track(p.id, "audio", name="A2", index=5)
        indices = [t.index for t in p.tracks]
        assert indices == sorted(indices)
