"""Tests for KaraokeProject — unified project metadata system."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── KaraokeProject dataclass ─────────────────────────────────────────────────

class TestKaraokeProject:
    """Tests for KaraokeProject dataclass serialization and creation."""

    def test_roundtrip(self):
        from src.api.karaoke_project import KaraokeProject, ProcessingSettings, Artifact
        proj = KaraokeProject(
            id="abc123",
            name="Test Song",
            created_at="2026-02-20T10:00:00+00:00",
            updated_at="2026-02-20T10:00:00+00:00",
            source_filename="test.mp3",
            duration_sec=180.0,
            settings=ProcessingSettings(backend="voxtral", language="de", cps=20.0),
            backend_used="voxtral",
            language_detected="de",
            segments_count=42,
            has_word_timestamps=True,
            bpm=120.0,
            avg_confidence=0.92,
            needs_review=3,
            artifacts=[Artifact(filename="test.srt", format="srt", size=1234)],
        )
        d = proj.to_dict()
        restored = KaraokeProject.from_dict(d)
        assert restored.id == "abc123"
        assert restored.name == "Test Song"
        assert restored.duration_sec == 180.0
        assert restored.settings.backend == "voxtral"
        assert restored.settings.cps == 20.0
        assert restored.segments_count == 42
        assert restored.bpm == 120.0
        assert len(restored.artifacts) == 1
        assert restored.artifacts[0].filename == "test.srt"

    def test_to_json(self):
        from src.api.karaoke_project import KaraokeProject
        proj = KaraokeProject(id="x", name="Y")
        text = proj.to_json()
        parsed = json.loads(text)
        assert parsed["id"] == "x"
        assert parsed["name"] == "Y"
        assert "settings" in parsed
        assert "artifacts" in parsed

    def test_defaults(self):
        from src.api.karaoke_project import KaraokeProject
        proj = KaraokeProject(id="d", name="Defaults")
        assert proj.version == 1
        assert proj.tool == "karaoke-sub-tool"
        assert proj.tool_version == "3.2.0"
        assert proj.settings.cps == 18.0
        assert proj.artifacts == []

    def test_from_dict_missing_fields(self):
        """from_dict should handle missing/extra fields gracefully."""
        from src.api.karaoke_project import KaraokeProject
        d = {"id": "partial", "name": "Partial", "extra_field": True}
        proj = KaraokeProject.from_dict(d)
        assert proj.id == "partial"
        assert proj.segments_count == 0
        assert proj.settings.backend == ""


class TestProcessingSettings:
    """Tests for ProcessingSettings creation and conversion."""

    def test_from_dict(self):
        from src.api.karaoke_project import ProcessingSettings
        s = ProcessingSettings.from_dict({
            "backend": "whisperx", "cps": 22.0, "unknown_field": 42,
        })
        assert s.backend == "whisperx"
        assert s.cps == 22.0
        # unknown_field should be ignored

    def test_from_request_mock(self):
        """Simulate a TranscribeRequest-like object."""
        from src.api.karaoke_project import ProcessingSettings
        from src.api.models import TranscribeRequest
        req = TranscribeRequest(backend="voxtral", language="de", cps=25.0,
                                snap_to_beat=True, bpm="120")
        s = ProcessingSettings.from_request(req)
        assert s.backend == "voxtral"
        assert s.language == "de"
        assert s.cps == 25.0
        assert s.snap_to_beat is True
        assert s.bpm == "120"
        assert s.karaoke_mode == "kf"  # default

    def test_roundtrip(self):
        from src.api.karaoke_project import ProcessingSettings
        s = ProcessingSettings(backend="whisperx", vocal_isolation=True, cps=15.0)
        d = s.to_dict()
        restored = ProcessingSettings.from_dict(d)
        assert restored.backend == "whisperx"
        assert restored.vocal_isolation is True
        assert restored.cps == 15.0


class TestArtifact:
    """Tests for Artifact serialization."""

    def test_roundtrip(self):
        from src.api.karaoke_project import Artifact
        a = Artifact(filename="song.ass", format="ass", size=5678)
        d = a.to_dict()
        restored = Artifact.from_dict(d)
        assert restored.filename == "song.ass"
        assert restored.format == "ass"
        assert restored.size == 5678


# ── Persistence ───────────────────────────────────────────────────────────────

class TestPersistence:
    """Tests for save/load/update project.json."""

    def test_save_and_load(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)

        proj = kp.KaraokeProject(id="j1", name="Test")
        proj.segments_count = 10
        path = kp.save_project(proj)
        assert path.exists()
        assert path.name == "project.json"

        loaded = kp.load_project("j1")
        assert loaded is not None
        assert loaded.id == "j1"
        assert loaded.segments_count == 10

    def test_load_nonexistent(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        assert kp.load_project("nonexistent") is None

    def test_update_metadata(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)

        proj = kp.KaraokeProject(id="j2", name="Before", segments_count=5)
        kp.save_project(proj)

        ok = kp.update_project_metadata("j2", segments_count=10, name="After")
        assert ok is True

        reloaded = kp.load_project("j2")
        assert reloaded.segments_count == 10
        assert reloaded.name == "After"
        assert reloaded.updated_at != ""

    def test_update_nonexistent(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        assert kp.update_project_metadata("ghost", segments_count=1) is False


class TestFromPipeline:
    """Test KaraokeProject.from_pipeline factory method."""

    def test_basic(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        from src.api.models import TranscribeRequest
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)

        # Create job dir with segments.json
        job_dir = tmp_path / "testjob"
        job_dir.mkdir()
        seg_path = job_dir / "segments.json"
        seg_path.write_text('[{"start":0,"end":1,"text":"Hi"}]', encoding="utf-8")
        srt_path = job_dir / "test.srt"
        srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")

        req = TranscribeRequest(backend="voxtral", language="de")
        proj = kp.KaraokeProject.from_pipeline(
            job_id="testjob",
            source_filename="test.mp3",
            req=req,
            backend_used="voxtral",
            language_detected="de",
            duration_sec=60.0,
            segments_count=1,
            has_word_timestamps=False,
            artifact_files={"srt": "test.srt"},
        )
        assert proj.id == "testjob"
        assert proj.source_filename == "test.mp3"
        assert proj.settings.backend == "voxtral"
        assert proj.duration_sec == 60.0
        # segments.json is always added
        fmts = [a.format for a in proj.artifacts]
        assert "srt" in fmts
        assert "segments" in fmts


# ── Lazy Migration ────────────────────────────────────────────────────────────

class TestEnsureProject:
    """Tests for ensure_project (lazy migration)."""

    def test_existing_project(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)

        proj = kp.KaraokeProject(id="exist", name="Existing")
        kp.save_project(proj)

        result = kp.ensure_project("exist")
        assert result is not None
        assert result.name == "Existing"

    def test_lazy_migration(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)

        # Create a legacy job directory without project.json
        job_dir = tmp_path / "legacy1"
        job_dir.mkdir()
        (job_dir / "segments.json").write_text(
            json.dumps([
                {"start": 0, "end": 2, "text": "Hello", "has_word_timestamps": True, "words": []},
                {"start": 2, "end": 4, "text": "World", "has_word_timestamps": False, "words": []},
            ]),
            encoding="utf-8",
        )
        (job_dir / "song.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        (job_dir / "song.ass").write_text("[Script Info]\nTitle: test", encoding="utf-8")
        (job_dir / "song.report.json").write_text(
            json.dumps({"backend": "whisperx", "language": "de", "duration_sec": 180.0,
                         "avg_confidence": 0.91, "karaoke_mode": "kf", "preset": "neon"}),
            encoding="utf-8",
        )
        (job_dir / "song.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)
        (job_dir / "waveform.json").write_text('{"peaks":[],"duration":180}', encoding="utf-8")

        # ensure_project should generate project.json
        result = kp.ensure_project("legacy1")
        assert result is not None
        assert result.id == "legacy1"
        assert result.backend_used == "whisperx"
        assert result.language_detected == "de"
        assert result.segments_count == 2
        assert result.has_word_timestamps is True  # at least one segment has it
        assert result.settings.karaoke_mode == "kf"
        assert result.settings.preset == "neon"
        assert result.duration_sec == 180.0
        # Verify project.json was written to disk
        assert (job_dir / "project.json").exists()
        # Artifacts
        fmts = {a.format for a in result.artifacts}
        assert "srt" in fmts
        assert "ass" in fmts
        assert "report" in fmts
        assert "waveform" in fmts
        assert "audio" in fmts
        assert "segments" in fmts

    def test_lazy_no_segments(self, tmp_path, monkeypatch):
        """No segments.json → should return None."""
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        job_dir = tmp_path / "empty"
        job_dir.mkdir()
        assert kp.ensure_project("empty") is None

    def test_nonexistent_dir(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        assert kp.ensure_project("ghost") is None


# ── Library-compatible dict converters ────────────────────────────────────────

class TestLibraryCompatDicts:
    """Tests for _project_to_library_item and _project_to_library_detail."""

    def _make_proj(self, tmp_path, job_id="proj1"):
        from src.api.karaoke_project import KaraokeProject, ProcessingSettings, Artifact
        return KaraokeProject(
            id=job_id,
            name="My Song",
            created_at="2026-03-01T12:00:00+00:00",
            updated_at="2026-03-01T12:00:00+00:00",
            source_filename="song.mp3",
            duration_sec=200.0,
            settings=ProcessingSettings(backend="voxtral", language="de"),
            backend_used="voxtral",
            language_detected="de",
            segments_count=10,
            has_word_timestamps=True,
            bpm=128.0,
            avg_confidence=0.95,
            needs_review=1,
            artifacts=[Artifact(filename="song.srt", format="srt", size=500)],
            tags=["rap", "deutsch"],
        )

    def test_library_item_shape(self, tmp_path):
        from src.api.karaoke_project import _project_to_library_item
        proj = self._make_proj(tmp_path)
        item = _project_to_library_item(proj)
        assert item["id"] == "proj1"
        assert item["job_id"] == "proj1"  # id == job_id
        assert item["title"] == "My Song"
        assert item["backend"] == "voxtral"
        assert item["language"] == "de"
        assert item["bpm"] == 128.0
        assert item["tags"] == ["rap", "deutsch"]
        assert item["segments_count"] == 10
        assert "srt_text" not in item  # item has no text fields

    def test_library_detail_reads_disk(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        job_dir = tmp_path / "proj1"
        job_dir.mkdir()
        (job_dir / "segments.json").write_text('[{"start":0,"end":1,"text":"Hi"}]', encoding="utf-8")
        (job_dir / "song.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
        (job_dir / "song.ass").write_text("[Script Info]\nTitle: test\n", encoding="utf-8")

        proj = self._make_proj(tmp_path)
        detail = kp._project_to_library_detail(proj)
        assert detail["id"] == "proj1"
        assert detail["srt_text"] is not None
        assert "Hi" in detail["srt_text"]
        assert detail["ass_text"] is not None
        assert "Script Info" in detail["ass_text"]
        assert detail["segments_json"] is not None
        assert "project" in detail
        assert detail["project"]["id"] == "proj1"

    def test_library_detail_missing_files(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        job_dir = tmp_path / "proj1"
        job_dir.mkdir()
        proj = self._make_proj(tmp_path)
        detail = kp._project_to_library_detail(proj)
        assert detail["srt_text"] is None
        assert detail["ass_text"] is None
        assert detail["segments_json"] is None


# ── list_projects ─────────────────────────────────────────────────────────────

class TestListProjects:
    """Tests for filesystem-based project listing."""

    def _create_job(self, base_dir, job_id, name="Song", created_at="2026-01-01T00:00:00+00:00"):
        from src.api.karaoke_project import KaraokeProject, ProcessingSettings, save_project
        job_dir = base_dir / job_id
        job_dir.mkdir(exist_ok=True)
        (job_dir / "segments.json").write_text("[]", encoding="utf-8")
        proj = KaraokeProject(
            id=job_id,
            name=name,
            created_at=created_at,
            updated_at=created_at,
            source_filename=f"{name.lower()}.mp3",
            backend_used="voxtral",
            language_detected="de",
        )
        save_project(proj)
        return proj

    def test_list_empty(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        items, total = kp.list_projects()
        assert total == 0
        assert items == []

    def test_list_all(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        self._create_job(tmp_path, "j1", "Alpha", "2026-01-01T00:00:00+00:00")
        self._create_job(tmp_path, "j2", "Beta", "2026-02-01T00:00:00+00:00")
        items, total = kp.list_projects()
        assert total == 2
        assert items[0]["title"] == "Beta"  # newest first
        assert items[1]["title"] == "Alpha"

    def test_search_filter(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        self._create_job(tmp_path, "j1", "Rock Anthem")
        self._create_job(tmp_path, "j2", "Jazz Ballad")
        items, total = kp.list_projects(q="jazz")
        assert total == 1
        assert items[0]["title"] == "Jazz Ballad"

    def test_pagination(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        for i in range(5):
            self._create_job(tmp_path, f"j{i}", f"Song {i}", f"2026-01-0{i+1}T00:00:00+00:00")
        items, total = kp.list_projects(limit=2, offset=0)
        assert total == 5
        assert len(items) == 2
        items2, _ = kp.list_projects(limit=2, offset=2)
        assert len(items2) == 2
        items3, _ = kp.list_projects(limit=2, offset=4)
        assert len(items3) == 1

    def test_skips_non_dirs(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        (tmp_path / "random.txt").write_text("not a dir", encoding="utf-8")
        self._create_job(tmp_path, "j1", "Test")
        items, total = kp.list_projects()
        assert total == 1


# ── delete_project ────────────────────────────────────────────────────────────

class TestDeleteProject:
    """Tests for project deletion (filesystem removal)."""

    def test_delete_existing(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        job_dir = tmp_path / "del1"
        job_dir.mkdir()
        (job_dir / "segments.json").write_text("[]", encoding="utf-8")
        assert kp.delete_project("del1") is True
        assert not job_dir.exists()

    def test_delete_nonexistent(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        assert kp.delete_project("ghost") is False

    def test_delete_refuses_non_job_dir(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        rogue = tmp_path / "not_a_job"
        rogue.mkdir()
        (rogue / "readme.txt").write_text("nope", encoding="utf-8")
        assert kp.delete_project("not_a_job") is False
        assert rogue.exists()  # should NOT be deleted

    def test_delete_with_project_json_only(self, tmp_path, monkeypatch):
        from src.api import karaoke_project as kp
        monkeypatch.setattr(kp, "OUTPUT_DIR", tmp_path)
        job_dir = tmp_path / "del2"
        job_dir.mkdir()
        (job_dir / "project.json").write_text("{}", encoding="utf-8")
        assert kp.delete_project("del2") is True
        assert not job_dir.exists()
