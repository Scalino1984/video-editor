"""Tests for AI video/image generation module."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.video.generation.base import (
    GenerationProvider, GenRequest, GenJob, GenStatus, GenType,
)


# ══════════════════════════════════════════════════════════════════════════════
# Data model tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGenRequest:
    def test_defaults(self):
        r = GenRequest(gen_type=GenType.video, prompt="test")
        assert r.gen_type == GenType.video
        assert r.prompt == "test"
        assert r.aspect_ratio == "16:9"
        assert r.duration == "5s"
        assert r.resolution == "1080p"
        assert r.loop is False

    def test_image_request(self):
        r = GenRequest(gen_type=GenType.image, prompt="a cat", image_format="png")
        assert r.gen_type == GenType.image
        assert r.image_format == "png"

    def test_to_dict(self):
        r = GenRequest(gen_type=GenType.video, prompt="test", duration="9s")
        d = r.to_dict()
        assert d["gen_type"] == "video"
        assert d["duration"] == "9s"
        assert d["prompt"] == "test"


class TestGenJob:
    def test_defaults(self):
        j = GenJob()
        assert len(j.id) == 12
        assert j.status == GenStatus.pending
        assert j.gen_type == GenType.video
        assert j.progress == 0.0

    def test_to_dict(self):
        j = GenJob(provider="luma", gen_type=GenType.image, prompt="cat", status=GenStatus.completed)
        d = j.to_dict()
        assert d["gen_type"] == "image"
        assert d["status"] == "completed"
        assert d["provider"] == "luma"

    def test_from_dict(self):
        d = {
            "id": "abc123",
            "provider": "luma",
            "provider_id": "luma-xyz",
            "gen_type": "video",
            "prompt": "sunset",
            "status": "processing",
            "progress": 0.5,
            "result_url": "",
            "local_path": "",
            "error": "",
            "created_at": "2025-01-01T00:00:00Z",
            "completed_at": "",
            "project_id": "p1",
            "asset_id": "",
            "model": "ray-2",
            "aspect_ratio": "16:9",
            "metadata": {},
        }
        j = GenJob.from_dict(d)
        assert j.id == "abc123"
        assert j.gen_type == GenType.video
        assert j.status == GenStatus.processing
        assert j.progress == 0.5


class TestGenStatus:
    def test_all_values(self):
        for v in ("pending", "processing", "downloading", "completed", "failed", "cancelled"):
            assert GenStatus(v).value == v


# ══════════════════════════════════════════════════════════════════════════════
# Luma provider tests (mocked)
# ══════════════════════════════════════════════════════════════════════════════

class TestLumaProvider:
    @pytest.fixture
    def provider(self):
        from src.video.generation.luma import LumaProvider
        return LumaProvider()

    async def test_check_available_no_key(self, provider, monkeypatch):
        monkeypatch.delenv("LUMA_API_KEY", raising=False)
        ok, msg = await provider.check_available()
        assert ok is False
        assert "LUMA_API_KEY" in msg

    async def test_check_available_no_package(self, provider, monkeypatch):
        monkeypatch.setenv("LUMA_API_KEY", "test-key")
        with patch.dict("sys.modules", {"lumaai": None}):
            ok, msg = await provider.check_available()
            # May succeed if lumaai is installed, or fail if not
            assert isinstance(ok, bool)

    async def test_generate_video_no_key(self, provider, monkeypatch):
        monkeypatch.delenv("LUMA_API_KEY", raising=False)
        req = GenRequest(gen_type=GenType.video, prompt="test")
        with pytest.raises(RuntimeError, match="LUMA_API_KEY"):
            await provider.generate_video(req)

    async def test_generate_image_no_key(self, provider, monkeypatch):
        monkeypatch.delenv("LUMA_API_KEY", raising=False)
        req = GenRequest(gen_type=GenType.image, prompt="test")
        with pytest.raises(RuntimeError, match="LUMA_API_KEY"):
            await provider.generate_image(req)

    async def test_poll_no_key(self, provider, monkeypatch):
        monkeypatch.delenv("LUMA_API_KEY", raising=False)
        status, prog, url, err = await provider.poll_status("fake-id")
        assert status == GenStatus.failed

    async def test_cancel_no_key(self, provider, monkeypatch):
        monkeypatch.delenv("LUMA_API_KEY", raising=False)
        ok = await provider.cancel("fake-id")
        assert ok is False


# ══════════════════════════════════════════════════════════════════════════════
# Manager tests (mocked provider)
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerationManager:
    @pytest.fixture(autouse=True)
    def _reset_manager(self):
        """Reset manager state between tests."""
        from src.video.generation import manager
        saved_jobs = dict(manager._jobs)
        saved_providers = dict(manager._providers)
        saved_tasks = dict(manager._poll_tasks)
        manager._jobs.clear()
        manager._providers.clear()
        manager._poll_tasks.clear()
        yield
        # Cancel any running tasks
        for t in manager._poll_tasks.values():
            if not t.done():
                t.cancel()
        manager._jobs.clear()
        manager._jobs.update(saved_jobs)
        manager._providers.clear()
        manager._providers.update(saved_providers)
        manager._poll_tasks.clear()
        manager._poll_tasks.update(saved_tasks)

    def _make_mock_provider(self):
        """Create a mock provider that returns immediately."""
        prov = MagicMock(spec=GenerationProvider)
        prov.name = "mock"
        prov.check_available = AsyncMock(return_value=(True, "ok"))
        prov.generate_video = AsyncMock(return_value=("mock-vid-123", "mock-model"))
        prov.generate_image = AsyncMock(return_value=("mock-img-456", "mock-model"))
        prov.poll_status = AsyncMock(return_value=(GenStatus.completed, 1.0, "https://example.com/result.mp4", ""))
        prov.cancel = AsyncMock(return_value=True)
        prov.download = AsyncMock(return_value=Path("/tmp/test.mp4"))
        return prov

    def test_register_provider(self):
        from src.video.generation.manager import register_provider, get_provider
        prov = self._make_mock_provider()
        register_provider(prov)
        assert get_provider("mock") is prov

    async def test_submit_video(self, tmp_path):
        from src.video.generation.manager import register_provider, submit_generation, _jobs

        prov = self._make_mock_provider()
        # Make download write a real file
        async def fake_download(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("fake video data")
            return dest
        prov.download = AsyncMock(side_effect=fake_download)
        register_provider(prov)

        req = GenRequest(gen_type=GenType.video, prompt="test video", project_id="p1")
        job = await submit_generation(req, provider_name="mock")

        assert job.provider == "mock"
        assert job.gen_type == GenType.video
        assert job.prompt == "test video"
        # Job should be in store
        assert job.id in _jobs

    async def test_submit_image(self, tmp_path):
        from src.video.generation.manager import register_provider, submit_generation, _jobs

        prov = self._make_mock_provider()
        async def fake_download(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("fake image data")
            return dest
        prov.download = AsyncMock(side_effect=fake_download)
        register_provider(prov)

        req = GenRequest(gen_type=GenType.image, prompt="a cat", project_id="p1")
        job = await submit_generation(req, provider_name="mock")

        assert job.gen_type == GenType.image
        assert job.id in _jobs

    async def test_submit_unavailable_provider(self):
        from src.video.generation.manager import register_provider, submit_generation
        prov = self._make_mock_provider()
        prov.check_available = AsyncMock(return_value=(False, "no key"))
        register_provider(prov)

        req = GenRequest(gen_type=GenType.video, prompt="test")
        with pytest.raises(RuntimeError, match="nicht verfügbar"):
            await submit_generation(req, provider_name="mock")

    async def test_submit_unknown_provider(self):
        from src.video.generation.manager import submit_generation
        req = GenRequest(gen_type=GenType.video, prompt="test")
        with pytest.raises(RuntimeError, match="nicht registriert"):
            await submit_generation(req, provider_name="nonexistent")

    def test_list_jobs_empty(self):
        from src.video.generation.manager import list_jobs
        assert list_jobs() == []

    def test_get_job_missing(self):
        from src.video.generation.manager import get_job
        assert get_job("nonexistent") is None

    async def test_cancel_missing(self):
        from src.video.generation.manager import cancel_generation
        ok = await cancel_generation("nonexistent")
        assert ok is False

    async def test_delete_missing(self):
        from src.video.generation.manager import delete_generation
        ok = await delete_generation("nonexistent")
        assert ok is False


# ══════════════════════════════════════════════════════════════════════════════
# Route tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerationRoutes:
    @pytest.fixture
    def gen_client(self, _patch_dirs):
        """FastAPI TestClient with generation routes."""
        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_status_endpoint(self, gen_client):
        r = gen_client.get("/api/editor/generation/status")
        assert r.status_code == 200
        data = r.json()
        assert "available" in data
        assert "message" in data
        assert "provider" in data

    def test_list_empty(self, gen_client):
        r = gen_client.get("/api/editor/generations")
        assert r.status_code == 200
        assert r.json() == []

    def test_get_missing(self, gen_client):
        r = gen_client.get("/api/editor/generations/nonexistent")
        assert r.status_code == 404

    def test_delete_missing(self, gen_client):
        r = gen_client.delete("/api/editor/generations/nonexistent")
        assert r.status_code == 404

    def test_import_missing(self, gen_client):
        r = gen_client.post("/api/editor/generations/nonexistent/import")
        assert r.status_code == 404

    def test_generate_bad_type(self, gen_client):
        r = gen_client.post("/api/editor/generate", json={
            "gen_type": "invalid",
            "prompt": "test",
        })
        assert r.status_code == 400

    def test_generate_empty_prompt(self, gen_client):
        r = gen_client.post("/api/editor/generate", json={
            "gen_type": "video",
            "prompt": "",
        })
        assert r.status_code == 422  # pydantic validation


# ══════════════════════════════════════════════════════════════════════════════
# Auto-scenes tests
# ══════════════════════════════════════════════════════════════════════════════

class TestLyricsExtraction:
    """Test lyrics extraction from various subtitle formats."""

    def test_extract_from_srt(self):
        from src.video.generation.scenes import _lyrics_from_srt
        srt = (
            "1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n"
            "2\n00:00:05,000 --> 00:00:08,000\nSecond line\n"
        )
        result = _lyrics_from_srt(srt)
        assert "Hello world" in result
        assert "Second line" in result

    def test_extract_from_ass(self):
        from src.video.generation.scenes import _lyrics_from_ass
        ass = (
            "[Script Info]\nTitle: Test\n\n[Events]\n"
            "Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,Hello world\n"
            "Dialogue: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,Second line\n"
        )
        result = _lyrics_from_ass(ass)
        assert "Hello world" in result
        assert "Second line" in result

    def test_extract_from_ass_with_tags(self):
        from src.video.generation.scenes import _lyrics_from_ass
        ass = (
            "[Events]\n"
            "Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,{\\kf50}Hel{\\kf50}lo world\n"
        )
        result = _lyrics_from_ass(ass)
        assert "Hello world" in result
        assert "\\kf" not in result

    def test_extract_from_vtt(self):
        from src.video.generation.scenes import _lyrics_from_vtt
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nHello world\n\n00:00:05.000 --> 00:00:08.000\nSecond line\n"
        result = _lyrics_from_vtt(vtt)
        assert "Hello world" in result
        assert "Second line" in result

    def test_extract_from_lrc(self):
        from src.video.generation.scenes import _lyrics_from_lrc
        lrc = "[ti:Test Song]\n[ar:Artist]\n[00:01.00]Hello world\n[00:05.00]Second line\n"
        result = _lyrics_from_lrc(lrc)
        assert "Hello world" in result
        assert "Second line" in result
        assert "Test Song" not in result

    def test_empty_input(self):
        from src.video.generation.scenes import _lyrics_from_srt, _lyrics_from_ass
        assert _lyrics_from_srt("") == ""
        assert _lyrics_from_ass("") == ""


class TestSceneJsonParsing:
    """Test parsing of AI response into scene suggestions."""

    def test_parse_direct_json(self):
        from src.video.generation.scenes import _parse_scenes_json
        data = json.dumps([
            {"title": "Scene 1", "prompt": "A sunset", "mood": "warm", "lyrics_ref": "line 1"},
            {"title": "Scene 2", "prompt": "A forest", "mood": "calm", "lyrics_ref": "line 2"},
        ])
        result = _parse_scenes_json(data)
        assert len(result) == 2
        assert result[0]["title"] == "Scene 1"

    def test_parse_markdown_wrapped(self):
        from src.video.generation.scenes import _parse_scenes_json
        data = '```json\n[{"title":"S1","prompt":"P1","mood":"M1","lyrics_ref":"L1"}]\n```'
        result = _parse_scenes_json(data)
        assert len(result) == 1
        assert result[0]["title"] == "S1"

    def test_parse_with_surrounding_text(self):
        from src.video.generation.scenes import _parse_scenes_json
        data = 'Here are the scenes:\n[{"title":"S1","prompt":"P1","mood":"M1","lyrics_ref":"L1"}]\nHope you like them!'
        result = _parse_scenes_json(data)
        assert len(result) == 1

    def test_parse_invalid_json(self):
        from src.video.generation.scenes import _parse_scenes_json
        result = _parse_scenes_json("this is not json at all")
        assert result == []


class TestAutoScenesRoute:
    """Test the auto-scenes API endpoint."""

    @pytest.fixture
    def gen_client(self, _patch_dirs):
        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_auto_scenes_no_project(self, gen_client):
        r = gen_client.post("/api/editor/projects/nonexistent/auto-scenes", json={})
        assert r.status_code == 404

    def test_auto_scenes_no_lyrics(self, gen_client):
        """Project without subtitle assets returns error."""
        # Create a project first
        r = gen_client.post("/api/editor/projects", json={"name": "Test Gen"})
        assert r.status_code == 200
        pid = r.json()["id"]

        r = gen_client.post(f"/api/editor/projects/{pid}/auto-scenes", json={
            "gen_type": "video",
            "aspect_ratio": "16:9",
        })
        assert r.status_code == 400
        assert "Lyrics" in r.json()["detail"] or "Untertitel" in r.json()["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# Config tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerationConfig:
    def test_default_config(self):
        from src.utils.config import AppConfig
        cfg = AppConfig()
        assert cfg.generation.provider == "luma"
        assert cfg.generation.luma_model_video == "ray-2"
        assert cfg.generation.luma_model_image == "photon-1"
        assert cfg.generation.default_aspect_ratio == "16:9"
        assert cfg.generation.default_duration == "5s"
        assert cfg.generation.default_resolution == "1080p"
        assert cfg.generation.poll_interval_s == 3.0
        assert cfg.generation.max_concurrent == 3
        assert cfg.generation.auto_import is True

    def test_override_config(self):
        from src.utils.config import AppConfig, merge_cli_overrides
        cfg = AppConfig()
        cfg2 = merge_cli_overrides(cfg, {
            "generation.provider": "luma",
            "generation.luma_model_video": "ray-flash-2",
            "generation.max_concurrent": 5,
        })
        assert cfg2.generation.luma_model_video == "ray-flash-2"
        assert cfg2.generation.max_concurrent == 5
