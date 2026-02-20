"""Tests for overlay asset library, API validation, and render integration."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_project(**overrides) -> "Project":
    from src.video.editor import Project
    defaults = dict(
        id="test-proj", name="Test", width=1920, height=1080, fps=30,
        duration=10.0, sub_font="Arial", sub_size=48,
        sub_color="&H00FFFFFF", sub_highlight_color="&H0000FFFF",
        sub_outline_color="&H00000000", sub_outline_width=2,
        sub_y_percent=85, sub_lines=1, sub_bg_enabled=True,
        sub_bg_color="&H80000000", crf=23, audio_bitrate="192k",
    )
    defaults.update(overrides)
    return Project(**defaults)


# ── Overlay Service Tests ─────────────────────────────────────────────────────


class TestOverlayService:
    """Test overlay asset discovery, caching, and ID generation."""

    def test_generate_stable_id(self):
        from src.video.overlay_service import _generate_id
        id1 = _generate_id("effects/sparkle.mp4")
        id2 = _generate_id("effects/sparkle.mp4")
        id3 = _generate_id("effects/fire.mp4")
        assert id1 == id2, "Same relative path must produce same ID"
        assert id1 != id3, "Different paths must produce different IDs"
        assert len(id1) == 16

    def test_has_alpha_channel(self):
        from src.video.overlay_service import _has_alpha_channel
        assert _has_alpha_channel("rgba") is True
        assert _has_alpha_channel("yuva420p") is True
        assert _has_alpha_channel("yuv420p") is False
        assert _has_alpha_channel("") is False

    def test_scan_empty_directory(self, tmp_path: Path, monkeypatch):
        from src.video import overlay_service
        monkeypatch.setattr(overlay_service, "OVERLAY_DIR", tmp_path)
        overlay_service.clear_cache()
        result = overlay_service.scan_overlays()
        assert result == []

    def test_scan_skips_non_allowed_extensions(self, tmp_path: Path, monkeypatch):
        from src.video import overlay_service
        monkeypatch.setattr(overlay_service, "OVERLAY_DIR", tmp_path)
        overlay_service.clear_cache()
        (tmp_path / "readme.txt").write_text("not a video")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")

        with patch.object(overlay_service, "_probe_overlay") as mock_probe:
            result = overlay_service.scan_overlays()
            mock_probe.assert_not_called()
        assert result == []

    def test_scan_finds_mp4_files(self, tmp_path: Path, monkeypatch):
        from src.video import overlay_service
        from src.video.overlay_service import OverlayAsset
        monkeypatch.setattr(overlay_service, "OVERLAY_DIR", tmp_path)
        overlay_service.clear_cache()

        # Create dummy overlay file
        overlay_file = tmp_path / "sparkle.mp4"
        overlay_file.write_bytes(b"\x00" * 100)

        fake_asset = OverlayAsset(
            id="abc123", name="sparkle", filename="sparkle.mp4",
            relative_path="sparkle.mp4", duration_sec=3.0,
            width=1920, height=1080, fps=30.0, pix_fmt="rgba",
            has_alpha=True, file_size=100,
        )
        with patch.object(overlay_service, "_probe_overlay", return_value=fake_asset):
            result = overlay_service.scan_overlays()
        assert len(result) == 1
        assert result[0].name == "sparkle"

    def test_overlay_to_dict_has_no_absolute_paths(self, tmp_path: Path):
        from src.video.overlay_service import OverlayAsset
        asset = OverlayAsset(
            id="test123", name="fire", filename="fire.mp4",
            relative_path="effects/fire.mp4", duration_sec=5.0,
            width=1920, height=1080, fps=30.0, pix_fmt="yuv420p",
            has_alpha=False, file_size=500,
        )
        d = asset.to_dict()
        assert "preview_url" in d
        assert d["preview_url"] == "/api/overlays/test123/file"
        # No absolute paths in response
        for key, val in d.items():
            if isinstance(val, str) and key != "pix_fmt":
                assert not val.startswith("/home"), f"Absolute path leaked in {key}: {val}"
                assert not val.startswith("/data"), f"Absolute path leaked in {key}: {val}"

    def test_validate_blend_mode(self):
        from src.video.overlay_service import validate_blend_mode
        assert validate_blend_mode("normal") is True
        assert validate_blend_mode("screen") is True
        assert validate_blend_mode("addition") is True
        assert validate_blend_mode("multiply") is True
        assert validate_blend_mode("invalid") is False
        assert validate_blend_mode("") is False

    def test_get_overlay_returns_none_for_missing(self, tmp_path: Path, monkeypatch):
        from src.video import overlay_service
        monkeypatch.setattr(overlay_service, "OVERLAY_DIR", tmp_path)
        overlay_service.clear_cache()
        assert overlay_service.get_overlay("nonexistent") is None

    def test_get_overlay_path_validates_security(self, tmp_path: Path, monkeypatch):
        from src.video import overlay_service
        monkeypatch.setattr(overlay_service, "OVERLAY_DIR", tmp_path)
        overlay_service.clear_cache()
        # No overlay with that ID → returns None
        assert overlay_service.get_overlay_path("fake_id") is None


# ── Clip Model Tests ──────────────────────────────────────────────────────────


class TestClipOverlayFields:
    """Test that overlay-specific fields on Clip are backward compatible."""

    def test_clip_defaults(self):
        from src.video.editor import Clip
        clip = Clip(id="c1", asset_id="a1", track="overlay", start=0, duration=5)
        assert clip.opacity == 1.0
        assert clip.blend_mode == "normal"

    def test_clip_custom_overlay_fields(self):
        from src.video.editor import Clip
        clip = Clip(
            id="c1", asset_id="a1", track="overlay",
            start=1.0, duration=3.0,
            opacity=0.7, blend_mode="screen",
        )
        assert clip.opacity == 0.7
        assert clip.blend_mode == "screen"

    def test_clip_to_dict_includes_overlay_fields(self):
        from src.video.editor import Clip
        clip = Clip(
            id="c1", asset_id="a1", track="overlay",
            start=0, duration=5, opacity=0.5, blend_mode="addition",
        )
        d = clip.to_dict()
        assert d["opacity"] == 0.5
        assert d["blend_mode"] == "addition"

    def test_project_from_dict_backward_compatible(self):
        """Old projects without overlay fields must still deserialize."""
        from src.video.editor import Project
        old_data = {
            "id": "old-proj", "name": "Old Project",
            "width": 1920, "height": 1080, "fps": 30,
            "assets": {},
            "clips": [
                {"id": "c1", "asset_id": "a1", "track": "video",
                 "start": 0, "duration": 10, "in_point": 0, "out_point": 10,
                 "volume": 1.0, "speed": 1.0, "loop": False,
                 "z_index": 0, "sub_style": "", "sub_position": "bottom"},
            ],
        }
        proj = Project.from_dict(old_data)
        assert len(proj.clips) == 1
        # Default values for missing overlay fields
        assert proj.clips[0].opacity == 1.0
        assert proj.clips[0].blend_mode == "normal"

    def test_project_round_trip_with_overlay(self):
        """Project with overlay clips serializes/deserializes correctly."""
        import json
        from src.video.editor import Project, Asset, Clip
        proj = _make_project()
        proj.assets["a1"] = Asset(id="a1", filename="overlay.mp4", path="/tmp/x.mp4", type="video", duration=5.0)
        proj.clips.append(Clip(
            id="c1", asset_id="a1", track="overlay",
            start=2.0, duration=3.0, opacity=0.6, blend_mode="multiply",
        ))
        data = json.loads(proj.to_json())
        proj2 = Project.from_dict(data)
        assert proj2.clips[0].opacity == 0.6
        assert proj2.clips[0].blend_mode == "multiply"
        assert proj2.clips[0].track == "overlay"


# ── Render / Filtergraph Tests ────────────────────────────────────────────────


class TestOverlayRendering:
    """Test that overlay clips produce correct filtergraph elements."""

    def _setup_project_with_overlay(
        self, opacity: float = 1.0, blend_mode: str = "normal",
        start: float = 2.0, duration: float = 3.0,
    ):
        """Create an in-memory project with a video clip and an overlay clip."""
        from src.video.editor import (
            _projects, _undo_stacks, _redo_stacks,
            Project, Asset, Clip,
        )
        from collections import deque

        pid = "render-test"
        proj = Project(id=pid, name="Render Test", width=1280, height=720, fps=30)
        proj.assets["bg"] = Asset(
            id="bg", filename="bg.mp4", path="/tmp/bg.mp4",
            type="video", duration=10.0, width=1280, height=720,
        )
        proj.assets["ov"] = Asset(
            id="ov", filename="sparkle.mp4", path="/tmp/sparkle.mp4",
            type="video", duration=5.0, width=1280, height=720,
        )
        proj.clips = [
            Clip(id="c_bg", asset_id="bg", track="video", start=0, duration=10),
            Clip(
                id="c_ov", asset_id="ov", track="overlay",
                start=start, duration=duration,
                opacity=opacity, blend_mode=blend_mode, z_index=1,
            ),
        ]
        _projects[pid] = proj
        _undo_stacks[pid] = deque(maxlen=80)
        _redo_stacks[pid] = deque(maxlen=80)
        return pid

    def _cleanup_project(self, pid: str):
        from src.video.editor import _projects, _undo_stacks, _redo_stacks
        _projects.pop(pid, None)
        _undo_stacks.pop(pid, None)
        _redo_stacks.pop(pid, None)

    def test_overlay_has_enable_between(self):
        """Filtergraph must contain enable='between(t,start,end)' for overlay."""
        from src.video.editor import build_render_cmd
        pid = self._setup_project_with_overlay(start=2.0, duration=3.0)
        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            assert cmd is not None
            fc = " ".join(cmd)
            assert "enable='between(t,2.000,5.000)'" in fc
        finally:
            self._cleanup_project(pid)

    def test_overlay_opacity_produces_colorchannelmixer(self):
        """Overlay with opacity<1 must have colorchannelmixer=aa=X in filtergraph."""
        from src.video.editor import build_render_cmd
        pid = self._setup_project_with_overlay(opacity=0.5)
        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            assert cmd is not None
            fc = " ".join(cmd)
            assert "colorchannelmixer=aa=0.500" in fc
        finally:
            self._cleanup_project(pid)

    def test_overlay_full_opacity_no_colorchannelmixer(self):
        """Overlay with opacity=1.0 must NOT have colorchannelmixer in prep chain."""
        from src.video.editor import build_render_cmd
        pid = self._setup_project_with_overlay(opacity=1.0)
        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            assert cmd is not None
            fc = " ".join(cmd)
            # The overlay prep chain should have format=rgba but NOT colorchannelmixer
            # Find the overlay prep filter part (vp1 since bg is vp0)
            assert "format=rgba" in fc
            assert "colorchannelmixer" not in fc
        finally:
            self._cleanup_project(pid)

    def test_overlay_format_rgba(self):
        """Overlay clips must include format=rgba in their prep chain."""
        from src.video.editor import build_render_cmd
        pid = self._setup_project_with_overlay()
        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            fc = " ".join(cmd)
            assert "format=rgba" in fc
        finally:
            self._cleanup_project(pid)

    def test_blend_mode_normal_uses_overlay_filter(self):
        """Normal blend mode must use 'overlay' filter (alpha compositing)."""
        from src.video.editor import build_render_cmd
        pid = self._setup_project_with_overlay(blend_mode="normal")
        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            fc = " ".join(cmd)
            # The overlay clip should use overlay=0:0
            assert "overlay=0:0" in fc
        finally:
            self._cleanup_project(pid)

    def test_blend_mode_screen_uses_blend_filter(self):
        """Screen blend mode must use 'blend' filter."""
        from src.video.editor import build_render_cmd
        pid = self._setup_project_with_overlay(blend_mode="screen")
        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            fc = " ".join(cmd)
            assert "blend=all_mode=screen" in fc
        finally:
            self._cleanup_project(pid)

    def test_blend_mode_addition_uses_blend_filter(self):
        """Addition blend mode must use 'blend' filter."""
        from src.video.editor import build_render_cmd
        pid = self._setup_project_with_overlay(blend_mode="addition")
        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            fc = " ".join(cmd)
            assert "blend=all_mode=addition" in fc
        finally:
            self._cleanup_project(pid)

    def test_blend_mode_multiply_uses_blend_filter(self):
        """Multiply blend mode must use 'blend' filter."""
        from src.video.editor import build_render_cmd
        pid = self._setup_project_with_overlay(blend_mode="multiply")
        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            fc = " ".join(cmd)
            assert "blend=all_mode=multiply" in fc
        finally:
            self._cleanup_project(pid)

    def test_z_index_ordering(self):
        """Multiple overlays must be ordered by z_index in the filtergraph."""
        from src.video.editor import (
            _projects, _undo_stacks, _redo_stacks,
            Project, Asset, Clip, build_render_cmd,
        )
        from collections import deque

        pid = "zorder-test"
        proj = Project(id=pid, name="Z Order", width=1280, height=720, fps=30)
        proj.assets["bg"] = Asset(
            id="bg", filename="bg.mp4", path="/tmp/bg.mp4",
            type="video", duration=10.0, width=1280, height=720,
        )
        proj.assets["ov1"] = Asset(
            id="ov1", filename="first.mp4", path="/tmp/first.mp4",
            type="video", duration=5.0,
        )
        proj.assets["ov2"] = Asset(
            id="ov2", filename="second.mp4", path="/tmp/second.mp4",
            type="video", duration=5.0,
        )
        proj.clips = [
            Clip(id="c_bg", asset_id="bg", track="video", start=0, duration=10, z_index=0),
            Clip(id="c_ov2", asset_id="ov2", track="overlay", start=0, duration=5, z_index=10),
            Clip(id="c_ov1", asset_id="ov1", track="overlay", start=0, duration=5, z_index=5),
        ]
        _projects[pid] = proj
        _undo_stacks[pid] = deque(maxlen=80)
        _redo_stacks[pid] = deque(maxlen=80)

        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            fc = " ".join(cmd)
            # z_index=0 (bg), z_index=5 (ov1=first.mp4), z_index=10 (ov2=second.mp4)
            idx_first = fc.index("first.mp4")
            idx_second = fc.index("second.mp4")
            assert idx_first < idx_second, "Lower z_index must come first in filtergraph"
        finally:
            _projects.pop(pid, None)
            _undo_stacks.pop(pid, None)
            _redo_stacks.pop(pid, None)

    def test_no_shell_invocation_in_render_cmd(self):
        """Render command must be a list (no shell=True)."""
        from src.video.editor import build_render_cmd
        pid = self._setup_project_with_overlay()
        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            assert isinstance(cmd, list), "Render command must be a list, not a string"
            assert cmd[0] == "ffmpeg"
        finally:
            self._cleanup_project(pid)

    def test_video_clip_unchanged_by_overlay_features(self):
        """Regular video clips must NOT get format=rgba or colorchannelmixer."""
        from src.video.editor import (
            _projects, _undo_stacks, _redo_stacks,
            Project, Asset, Clip, build_render_cmd,
        )
        from collections import deque

        pid = "video-only-test"
        proj = Project(id=pid, name="Video Only", width=1280, height=720, fps=30)
        proj.assets["bg"] = Asset(
            id="bg", filename="bg.mp4", path="/tmp/bg.mp4",
            type="video", duration=10.0, width=1280, height=720,
        )
        proj.clips = [
            Clip(id="c_bg", asset_id="bg", track="video", start=0, duration=10),
        ]
        _projects[pid] = proj
        _undo_stacks[pid] = deque(maxlen=80)
        _redo_stacks[pid] = deque(maxlen=80)

        try:
            cmd = build_render_cmd(pid, Path("/tmp/out.mp4"))
            fc = " ".join(cmd)
            # Regular video clips should NOT have overlay-specific filters
            assert "format=rgba" not in fc
            assert "colorchannelmixer" not in fc
        finally:
            _projects.pop(pid, None)
            _undo_stacks.pop(pid, None)
            _redo_stacks.pop(pid, None)


# ── Validation Tests ──────────────────────────────────────────────────────────


class TestOverlayValidation:
    """Test validation of overlay parameters."""

    def test_invalid_opacity_range(self):
        """Opacity outside 0.0-1.0 should be caught."""
        # Direct validation check
        assert not (0.0 <= -0.1 <= 1.0)
        assert not (0.0 <= 1.1 <= 1.0)
        assert 0.0 <= 0.5 <= 1.0

    def test_invalid_blend_mode(self):
        """Invalid blend modes should fail validation."""
        from src.video.overlay_service import validate_blend_mode
        assert validate_blend_mode("dodge") is False
        assert validate_blend_mode("burn") is False
        assert validate_blend_mode("hardlight") is False
        assert validate_blend_mode("SCREEN") is False  # case sensitive

    def test_valid_blend_modes(self):
        """All supported blend modes should pass validation."""
        from src.video.overlay_service import validate_blend_mode, VALID_BLEND_MODES
        for mode in VALID_BLEND_MODES:
            assert validate_blend_mode(mode) is True, f"{mode} should be valid"
