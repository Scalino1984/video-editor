"""KaraokeProject — unified project metadata for karaoke transcription jobs.

The single source of truth for project listing, search, and metadata.
All data lives on the filesystem at ``data/output/{job_id}/project.json``
alongside ``segments.json`` — no database involved.

Mirrors the Video-Editor's Project pattern (data/editor/projects/*.json).

Usage::

    from src.api.karaoke_project import (
        KaraokeProject, save_project, load_project,
        list_projects, delete_project, ensure_project,
    )

    proj = KaraokeProject.from_pipeline(job_id, audio_path, req, ...)
    save_project(proj)

    projects, total = list_projects(q="song", limit=20)
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, debug

OUTPUT_DIR = Path("data/output")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ProcessingSettings:
    """Snapshot of TranscribeRequest parameters used for this job."""
    backend: str = ""
    language: str = "auto"
    vad: bool = True
    vad_aggressiveness: int = 2
    normalize: bool = True
    target_lufs: float = -16.0
    vocal_isolation: bool = False
    word_timestamps: str = "auto"
    generate_ass: bool = True
    generate_vtt: bool = False
    generate_lrc: bool = False
    generate_txt: bool = False
    karaoke_mode: str = "kf"
    preset: str = "classic"
    highlight_color: str = "&H0000FFFF"
    snap_to_beat: bool = False
    bpm: str | None = None
    ai_correct: bool = False
    cps: float = 18.0
    min_duration: float = 1.0
    max_duration: float = 6.0
    max_chars_per_line: int = 42
    max_lines: int = 2
    lyrics_file: str | None = None
    use_lyrics_template: bool = False
    lyrics_template_mode: str = ""
    match_mode: str = "lenient"
    whisperx_model_size: str = "large-v3"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProcessingSettings:
        # Only pick known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_request(cls, req: Any) -> ProcessingSettings:
        """Build from a TranscribeRequest instance."""
        return cls(
            backend=req.backend.value if hasattr(req.backend, "value") else str(req.backend),
            language=req.language.value if hasattr(req.language, "value") else str(req.language),
            vad=req.vad,
            vad_aggressiveness=req.vad_aggressiveness,
            normalize=req.normalize,
            target_lufs=req.target_lufs,
            vocal_isolation=req.vocal_isolation,
            word_timestamps=req.word_timestamps,
            generate_ass=req.generate_ass,
            generate_vtt=req.generate_vtt,
            generate_lrc=req.generate_lrc,
            generate_txt=req.generate_txt,
            karaoke_mode=req.karaoke_mode.value if hasattr(req.karaoke_mode, "value") else str(req.karaoke_mode),
            preset=req.preset.value if hasattr(req.preset, "value") else str(req.preset),
            highlight_color=req.highlight_color,
            snap_to_beat=req.snap_to_beat,
            bpm=req.bpm,
            ai_correct=req.ai_correct,
            cps=req.cps,
            min_duration=req.min_duration,
            max_duration=req.max_duration,
            max_chars_per_line=req.max_chars_per_line,
            max_lines=req.max_lines,
            lyrics_file=req.lyrics_file,
            use_lyrics_template=req.use_lyrics_template,
            lyrics_template_mode=(
                req.lyrics_template_mode.value
                if hasattr(req.lyrics_template_mode, "value")
                else str(req.lyrics_template_mode)
            ),
            match_mode=req.match_mode.value if hasattr(req.match_mode, "value") else str(req.match_mode),
            whisperx_model_size=req.whisperx_model_size,
        )


@dataclass
class Artifact:
    """A generated output file."""
    filename: str
    format: str  # srt, ass, vtt, lrc, txt, report, waveform, preview, audio
    size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Artifact:
        return cls(filename=d.get("filename", ""), format=d.get("format", ""),
                   size=d.get("size", 0))


@dataclass
class KaraokeProject:
    """Unified project metadata for a karaoke transcription job."""
    # Identity
    id: str  # = job_id
    name: str  # display name (derived from filename)
    version: int = 1
    tool: str = "karaoke-sub-tool"
    tool_version: str = "3.2.0"

    # Timestamps
    created_at: str = ""
    updated_at: str = ""

    # Source
    source_filename: str = ""
    source_hash: str = ""
    duration_sec: float = 0.0

    # Processing
    settings: ProcessingSettings = field(default_factory=ProcessingSettings)

    # Results
    backend_used: str = ""
    language_detected: str = ""
    segments_count: int = 0
    has_word_timestamps: bool = False
    bpm: float = 0.0
    avg_confidence: float = 0.0
    needs_review: int = 0

    # Artifacts
    artifacts: list[Artifact] = field(default_factory=list)

    # User metadata
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_filename": self.source_filename,
            "source_hash": self.source_hash,
            "duration_sec": self.duration_sec,
            "settings": self.settings.to_dict(),
            "backend_used": self.backend_used,
            "language_detected": self.language_detected,
            "segments_count": self.segments_count,
            "has_word_timestamps": self.has_word_timestamps,
            "bpm": self.bpm,
            "avg_confidence": self.avg_confidence,
            "needs_review": self.needs_review,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "tags": self.tags,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KaraokeProject:
        settings = ProcessingSettings.from_dict(d.get("settings", {}))
        artifacts = [Artifact.from_dict(a) for a in d.get("artifacts", [])]
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            version=d.get("version", 1),
            tool=d.get("tool", "karaoke-sub-tool"),
            tool_version=d.get("tool_version", "3.2.0"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            source_filename=d.get("source_filename", ""),
            source_hash=d.get("source_hash", ""),
            duration_sec=d.get("duration_sec", 0.0),
            settings=settings,
            backend_used=d.get("backend_used", ""),
            language_detected=d.get("language_detected", ""),
            segments_count=d.get("segments_count", 0),
            has_word_timestamps=d.get("has_word_timestamps", False),
            bpm=d.get("bpm", 0.0),
            avg_confidence=d.get("avg_confidence", 0.0),
            needs_review=d.get("needs_review", 0),
            artifacts=artifacts,
            tags=d.get("tags", []),
        )

    @classmethod
    def from_pipeline(
        cls,
        job_id: str,
        source_filename: str,
        req: Any,
        *,
        backend_used: str = "",
        language_detected: str = "",
        duration_sec: float = 0.0,
        segments_count: int = 0,
        has_word_timestamps: bool = False,
        bpm: float = 0.0,
        avg_confidence: float = 0.0,
        needs_review: int = 0,
        artifact_files: dict[str, str] | None = None,
    ) -> KaraokeProject:
        """Create a project from pipeline completion data."""
        now = datetime.now(timezone.utc).isoformat()
        name = Path(source_filename).stem.replace("_", " ").replace("-", " ").title()

        settings = ProcessingSettings.from_request(req)

        # Build artifact list from output dir
        artifacts = []
        job_dir = OUTPUT_DIR / job_id
        if artifact_files:
            for fmt, fname in artifact_files.items():
                fpath = job_dir / fname
                size = fpath.stat().st_size if fpath.exists() else 0
                artifacts.append(Artifact(filename=fname, format=fmt, size=size))

        # Always include segments.json
        seg_path = job_dir / "segments.json"
        if seg_path.exists():
            artifacts.append(Artifact(
                filename="segments.json", format="segments",
                size=seg_path.stat().st_size,
            ))

        return cls(
            id=job_id,
            name=name,
            created_at=now,
            updated_at=now,
            source_filename=source_filename,
            duration_sec=duration_sec,
            settings=settings,
            backend_used=backend_used,
            language_detected=language_detected,
            segments_count=segments_count,
            has_word_timestamps=has_word_timestamps,
            bpm=bpm,
            avg_confidence=avg_confidence,
            needs_review=needs_review,
            artifacts=artifacts,
        )


# ── Persistence ───────────────────────────────────────────────────────────────

def _project_path(job_id: str) -> Path:
    return OUTPUT_DIR / job_id / "project.json"


def save_project(project: KaraokeProject) -> Path:
    """Write project.json to the job's output directory."""
    path = _project_path(project.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(project.to_json(), encoding="utf-8")
    debug(f"[{project.id}] project.json saved")
    return path


def load_project(job_id: str) -> KaraokeProject | None:
    """Load project.json from a job's output directory."""
    path = _project_path(job_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return KaraokeProject.from_dict(data)
    except Exception as e:
        warn(f"[{job_id}] Failed to load project.json: {e}")
        return None


def update_project_metadata(job_id: str, **kwargs: Any) -> bool:
    """Update specific fields in project.json (e.g. after segment edits)."""
    proj = load_project(job_id)
    if not proj:
        return False
    proj.updated_at = datetime.now(timezone.utc).isoformat()
    for k, v in kwargs.items():
        if hasattr(proj, k):
            setattr(proj, k, v)
    save_project(proj)
    return True


def ensure_project(job_id: str) -> KaraokeProject | None:
    """Load or lazily generate project.json for a job.

    For jobs created before the project system, this reconstructs a minimal
    project.json from the available artifacts and report data.
    """
    proj = load_project(job_id)
    if proj:
        return proj

    # Lazy migration: try to reconstruct from existing files
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.is_dir():
        return None

    seg_path = job_dir / "segments.json"
    if not seg_path.exists():
        return None

    info(f"[{job_id}] Generating project.json (lazy migration)")

    # Gather info from report.json if available
    report_data: dict[str, Any] = {}
    for rp in job_dir.glob("*.report.json"):
        try:
            report_data = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            pass
        break

    # Gather info from segments.json
    try:
        segs = json.loads(seg_path.read_text(encoding="utf-8"))
        segments_count = len(segs)
        has_words = any(s.get("has_word_timestamps") for s in segs)
    except Exception:
        segments_count = 0
        has_words = False

    # Try to find source filename from audio files
    source_filename = ""
    for ext in (".wav", ".mp3", ".flac", ".m4a", ".ogg"):
        candidates = list(job_dir.glob(f"*{ext}"))
        if candidates:
            source_filename = candidates[0].name
            break

    # Build artifact list
    artifacts = []
    _ext_fmt = {
        ".srt": "srt", ".ass": "ass", ".vtt": "vtt", ".lrc": "lrc",
        ".txt": "txt", ".report.json": "report", ".wav": "audio",
        ".mp3": "audio", ".flac": "audio",
    }
    for f in sorted(job_dir.iterdir()):
        if f.name in ("project.json", "segments.json"):
            continue
        if f.name.startswith("."):
            continue
        fmt = ""
        if f.name == "waveform.json":
            fmt = "waveform"
        elif f.name.endswith(".report.json"):
            fmt = "report"
        else:
            fmt = _ext_fmt.get(f.suffix.lower(), "")
        if fmt:
            artifacts.append(Artifact(filename=f.name, format=fmt, size=f.stat().st_size))
    artifacts.append(Artifact(filename="segments.json", format="segments",
                              size=seg_path.stat().st_size))

    now = datetime.now(timezone.utc).isoformat()
    name = Path(source_filename).stem.replace("_", " ").replace("-", " ").title() if source_filename else job_id

    # Reconstruct settings from report if available
    settings = ProcessingSettings(
        backend=report_data.get("backend", ""),
        language=report_data.get("language", ""),
        vad=report_data.get("vad_active", True),
        normalize=report_data.get("normalize_active", True),
        vocal_isolation=report_data.get("vocal_isolation_active", False),
        karaoke_mode=report_data.get("karaoke_mode", "kf"),
        preset=report_data.get("preset", "classic"),
        snap_to_beat=report_data.get("bpm_snap_active", False),
        ai_correct=report_data.get("ai_correct_active", False),
    )

    proj = KaraokeProject(
        id=job_id,
        name=name,
        created_at=now,
        updated_at=now,
        source_filename=source_filename,
        duration_sec=report_data.get("duration_sec", 0.0),
        settings=settings,
        backend_used=report_data.get("backend", ""),
        language_detected=report_data.get("language", ""),
        segments_count=segments_count,
        has_word_timestamps=has_words,
        bpm=report_data.get("bpm_value", 0.0),
        avg_confidence=report_data.get("avg_confidence", 0.0),
        needs_review=report_data.get("segments_needing_review", 0),
        artifacts=artifacts,
    )
    save_project(proj)
    return proj


# ── Library-compatible dict (for API responses) ──────────────────────────────

def _project_to_library_item(proj: KaraokeProject) -> dict[str, Any]:
    """Convert a KaraokeProject to a dict matching the old LibraryItem shape.

    This allows the frontend to use the same response format for both the
    old SQLite-based library and the new filesystem-based project listing.
    """
    return {
        "id": proj.id,  # = job_id (unified)
        "created_at": proj.created_at,
        "updated_at": proj.updated_at,
        "title": proj.name,
        "source_filename": proj.source_filename,
        "language": proj.language_detected,
        "backend": proj.backend_used,
        "duration_sec": proj.duration_sec,
        "bpm": proj.bpm,
        "segments_count": proj.segments_count,
        "has_word_timestamps": proj.has_word_timestamps,
        "needs_review": proj.needs_review,
        "avg_confidence": proj.avg_confidence,
        "job_id": proj.id,  # id == job_id for projects
        "tags": proj.tags,
    }


def _project_to_library_detail(proj: KaraokeProject) -> dict[str, Any]:
    """Convert a KaraokeProject to a full detail dict (with text content from disk)."""
    d = _project_to_library_item(proj)
    job_dir = OUTPUT_DIR / proj.id

    # Read segments.json
    seg_path = job_dir / "segments.json"
    d["segments_json"] = seg_path.read_text(encoding="utf-8") if seg_path.exists() else None

    # Read SRT text
    srt_text = None
    for f in job_dir.glob("*.srt"):
        srt_text = f.read_text(encoding="utf-8")
        break
    d["srt_text"] = srt_text

    # Read ASS text
    ass_text = None
    for f in job_dir.glob("*.ass"):
        ass_text = f.read_text(encoding="utf-8")
        break
    d["ass_text"] = ass_text

    # Attach full project metadata
    d["project"] = proj.to_dict()
    return d


# ── Filesystem-based project listing ─────────────────────────────────────────

def list_projects(
    q: str = "", limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Scan data/output/*/project.json and return library-compatible list.

    Supports text search across name, source_filename, backend.
    Returns (items_page, total_matching).
    """
    if not OUTPUT_DIR.is_dir():
        return [], 0

    projects: list[KaraokeProject] = []
    q_lower = q.lower().strip()

    for d in OUTPUT_DIR.iterdir():
        if not d.is_dir():
            continue
        proj = ensure_project(d.name)
        if not proj:
            continue
        # Text search filter
        if q_lower:
            searchable = f"{proj.name} {proj.source_filename} {proj.backend_used} {proj.language_detected}".lower()
            if q_lower not in searchable:
                continue
        projects.append(proj)

    # Sort by created_at descending (newest first)
    projects.sort(key=lambda p: p.created_at, reverse=True)
    total = len(projects)
    page = projects[offset:offset + limit]
    return [_project_to_library_item(p) for p in page], total


def delete_project(job_id: str) -> bool:
    """Delete a project by removing its entire output directory."""
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.is_dir():
        return False
    # Safety: only delete if it looks like a job dir (has segments.json or project.json)
    if not (job_dir / "segments.json").exists() and not (job_dir / "project.json").exists():
        warn(f"[{job_id}] Refusing to delete: not a recognized job directory")
        return False
    shutil.rmtree(job_dir)
    info(f"[{job_id}] Project deleted (directory removed)")
    return True

