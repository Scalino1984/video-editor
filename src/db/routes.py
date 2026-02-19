"""Library & Video API routes.

- /api/library/* — Transcriptions Library (CRUD, search, pagination)
- /api/render-video — Video rendering job (file upload or source_job_id)
- /api/render/{job_id}/download — Download rendered video
"""

from __future__ import annotations

import asyncio
import json
import shutil
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.api import tasks
from src.api.models import JobStatus, JobResult
from src.utils.logging import info, warn, error, debug

router = APIRouter(tags=["library", "video"])


# ══════════════════════════════════════════════════════════════════════════════
#  LIBRARY — Transcriptions CRUD
# ══════════════════════════════════════════════════════════════════════════════

class LibraryItem(BaseModel):
    id: str
    created_at: str
    updated_at: str
    title: str
    source_filename: str
    language: str
    backend: str
    duration_sec: float
    bpm: float
    segments_count: int
    has_word_timestamps: bool
    needs_review: int
    avg_confidence: float
    job_id: str | None
    tags: list[str]


class LibraryDetail(LibraryItem):
    srt_text: str | None
    ass_text: str | None
    segments_json: str | None


class LibraryListResponse(BaseModel):
    items: list[LibraryItem]
    total: int
    limit: int
    offset: int


class LibraryUpdateRequest(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    bpm: float | None = None


@router.get("/api/library")
async def list_library(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query("", description="Search title/filename/backend"),
) -> LibraryListResponse:
    """List transcriptions with pagination + search."""
    from src.db.library import list_transcriptions
    records, total = list_transcriptions(limit=limit, offset=offset, q=q)
    return LibraryListResponse(
        items=[LibraryItem(**r.to_dict()) for r in records],
        total=total, limit=limit, offset=offset,
    )


@router.get("/api/library/{rec_id}")
async def get_library_item(rec_id: str) -> LibraryDetail:
    """Get full transcription record including SRT/ASS text."""
    from src.db.library import get_transcription
    rec = get_transcription(rec_id)
    if not rec:
        raise HTTPException(404, "Not found")
    return LibraryDetail(**rec.to_dict(include_text=True))


@router.patch("/api/library/{rec_id}")
async def update_library_item(rec_id: str, req: LibraryUpdateRequest):
    """Update title, tags, or BPM of a library entry."""
    from src.db.library import update_transcription
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    if not kwargs:
        raise HTTPException(400, "No fields to update")
    ok = update_transcription(rec_id, **kwargs)
    if not ok:
        raise HTTPException(404, "Not found or invalid fields")
    return {"ok": True}


@router.delete("/api/library/{rec_id}")
async def delete_library_item(rec_id: str, hard: bool = Query(False)):
    """Delete transcription (soft by default, hard=true for permanent).

    Cascades: removes file registry references for the associated job.
    """
    from src.db.library import delete_transcription, get_transcription, remove_file_references
    rec = get_transcription(rec_id)
    if not rec:
        raise HTTPException(404, "Not found")

    # Remove file references for this transcription
    try:
        remove_file_references("transcription", rec_id)
        if rec.job_id:
            remove_file_references("job", rec.job_id)
    except Exception:
        pass  # non-critical

    ok = delete_transcription(rec_id, hard=hard)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"ok": True, "hard": hard}


@router.get("/api/library/{rec_id}/srt")
async def get_library_srt(rec_id: str):
    """Download SRT text as file."""
    from src.db.library import get_transcription
    rec = get_transcription(rec_id)
    if not rec or not rec.srt_text:
        raise HTTPException(404, "SRT not found")
    from fastapi.responses import PlainTextResponse
    filename = f"{rec.title or rec.source_filename}.srt"
    return PlainTextResponse(
        rec.srt_text, media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ══════════════════════════════════════════════════════════════════════════════
#  VIDEO RENDERING
# ══════════════════════════════════════════════════════════════════════════════

ALLOWED_SUB_EXT = {".srt", ".ass"}
ALLOWED_BG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm", ".avi"}
ALLOWED_AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}


class RenderRequestOpts(BaseModel):
    preset: str = "youtube"
    position: str = "bottom"
    crf: int | None = None
    x264_preset: str | None = None
    audio_bitrate: str | None = None
    fps: int | None = None
    target_resolution: str | None = None
    duration: float | None = None
    font_size: int = 48


class RenderJobResponse(BaseModel):
    job_id: str
    status: str


def _validate_ext(filename: str, allowed: set[str], label: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            400,
            f"Invalid {label} format: {ext}. Allowed: {', '.join(sorted(allowed))}",
        )
    return ext


@router.post("/api/render-video")
async def render_video_endpoint(
    background_file: UploadFile = File(...),
    audio_file: UploadFile | None = File(None),
    subtitle_file: UploadFile | None = File(None),
    source_job_id: str = Form(""),
    options: str = Form("{}"),
) -> RenderJobResponse:
    """Start a video rendering job.

    Subtitle source (one required):
      - subtitle_file: upload .srt/.ass directly
      - source_job_id: use subtitle from existing transcription job

    background_file: image (jpg/png/webp) or video (mp4/mov/webm)
    audio_file: optional audio track (or auto-found from source job)
    options: JSON string with preset, position, crf, etc.
    """
    from src.utils.media_executor import check_media_capacity
    has_cap, running, queued = check_media_capacity()
    if not has_cap:
        raise HTTPException(429, f"System ausgelastet — {running} laufende, {queued} wartende Jobs. Bitte später erneut versuchen.")
    # Validate background
    _validate_ext(background_file.filename, ALLOWED_BG_EXT, "background")

    # Validate subtitle source
    has_sub_file = subtitle_file and subtitle_file.filename
    if has_sub_file:
        _validate_ext(subtitle_file.filename, ALLOWED_SUB_EXT, "subtitle")
    elif not source_job_id:
        raise HTTPException(400, "Provide subtitle_file or source_job_id")

    # Validate audio
    has_audio_file = audio_file and audio_file.filename
    if has_audio_file:
        _validate_ext(audio_file.filename, ALLOWED_AUDIO_EXT, "audio")

    # Parse options
    try:
        opts = RenderRequestOpts(**json.loads(options))
    except Exception as e:
        raise HTTPException(400, f"Invalid options: {e}")

    # Create job — uses same OUTPUT_DIR as transcription jobs for unified download
    job = tasks.create_job(f"render_{Path(background_file.filename).stem}")
    job_id = job.job_id
    job_dir = tasks.OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save background
    bg_name = _safe_filename(f"bg_{background_file.filename}")
    bg_path = job_dir / bg_name
    bg_path.write_bytes(await background_file.read())

    # Resolve subtitle path
    if has_sub_file:
        sub_name = _safe_filename(subtitle_file.filename)
        sub_path = job_dir / sub_name
        sub_path.write_bytes(await subtitle_file.read())
    else:
        sub_path = _copy_subtitle_from_job(source_job_id, job_dir)
        if not sub_path:
            raise HTTPException(404, f"No subtitle found in job {source_job_id}")

    # Resolve audio path
    audio_path = None
    if has_audio_file:
        audio_name = _safe_filename(audio_file.filename)
        audio_path = job_dir / audio_name
        audio_path.write_bytes(await audio_file.read())
    elif source_job_id:
        audio_path = _find_audio_from_job(source_job_id)

    # Start render in background thread
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        tasks._executor,
        _render_job_sync,
        job_id, sub_path, bg_path, audio_path, opts,
    )

    return RenderJobResponse(job_id=job_id, status="started")


def _safe_filename(name: str) -> str:
    """Sanitize filename — no path traversal."""
    return Path(name).name.replace("..", "").replace("/", "_").replace("\\", "_")


def _copy_subtitle_from_job(job_id: str, dest_dir: Path) -> Path | None:
    """Find and copy .ass or .srt from existing job output."""
    job_out = tasks.OUTPUT_DIR / job_id
    if not job_out.exists():
        return None
    for ext in (".ass", ".srt"):
        for f in job_out.glob(f"*{ext}"):
            dest = dest_dir / f.name
            shutil.copy2(f, dest)
            info(f"Copied subtitle {f.name} from job {job_id}")
            return dest
    return None


def _find_audio_from_job(job_id: str) -> Path | None:
    """Find audio file from existing job output."""
    job_out = tasks.OUTPUT_DIR / job_id
    if not job_out.exists():
        return None
    for ext in (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".wma"):
        for f in job_out.glob(f"*{ext}"):
            return f
    return None


def _render_job_sync(
    job_id: str,
    sub_path: Path,
    bg_path: Path,
    audio_path: Path | None,
    opts: RenderRequestOpts,
) -> None:
    """Synchronous render job — runs in thread pool."""
    from src.video.render import render_video, RenderOptions as VROpts

    job_dir = tasks.OUTPUT_DIR / job_id
    output_path = job_dir / f"{sub_path.stem}_video.mp4"

    def progress_cb(stage: str, pct: float):
        progress = 0.05 + pct * 0.90
        tasks.update_job(job_id, progress=progress, stage=stage)

    try:
        tasks.update_job(
            job_id, status=JobStatus.exporting, progress=0.05, stage="Probing"
        )

        render_opts = VROpts(
            preset=opts.preset,
            position=opts.position,
            crf=opts.crf,
            x264_preset=opts.x264_preset,
            audio_bitrate=opts.audio_bitrate,
            fps=opts.fps,
            target_resolution=opts.target_resolution,
            duration=opts.duration,
            font_size=opts.font_size,
        )

        result_path = render_video(
            subtitle_path=sub_path,
            background_path=bg_path,
            output_path=output_path,
            audio_path=audio_path,
            options=render_opts,
            progress_callback=progress_cb,
        )

        if not result_path or not result_path.exists():
            raise RuntimeError("Video rendering failed — check ffmpeg logs")

        size_mb = result_path.stat().st_size / (1024 * 1024)

        # Probe actual duration
        actual_dur = 0.0
        try:
            from src.video.render import get_audio_duration
            actual_dur = get_audio_duration(result_path)
        except Exception:
            pass

        result = JobResult(
            srt_file=sub_path.name,
            preview_file=result_path.name,
            segments_count=0,
            duration_sec=actual_dur or opts.duration or 0,
            backend="render",
            language="",
        )

        tasks.update_job(
            job_id, status=JobStatus.completed, progress=1.0,
            stage=f"Done ({size_mb:.1f} MB)",
            completed_at=datetime.now(timezone.utc), result=result,
        )
        info(f"[{job_id}] ✅ Video render: {result_path.name} ({size_mb:.1f} MB)")

    except Exception as e:
        error(f"[{job_id}] ❌ Render failed: {e}")
        traceback.print_exc()
        tasks.update_job(
            job_id, status=JobStatus.failed, stage="Error",
            error=str(e), completed_at=datetime.now(timezone.utc),
        )


@router.get("/api/render/{job_id}/download")
async def download_rendered_video(job_id: str):
    """Download the rendered video file."""
    job_dir = tasks.OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Render job not found")
    videos = list(job_dir.glob("*_video.mp4"))
    if not videos:
        raise HTTPException(404, "No video file found — render may still be in progress")
    return FileResponse(videos[0], media_type="video/mp4", filename=videos[0].name)


# ══════════════════════════════════════════════════════════════════════════════
#  MEDIA REGISTRY & TAGS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/api/media")
async def list_media_endpoint(file_type: str = Query(""), limit: int = Query(50, ge=1, le=200)):
    """List registered media files."""
    from src.db.library import list_media
    items = list_media(file_type=file_type, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/api/media/{media_id}")
async def get_media_endpoint(media_id: str):
    """Get media record by ID."""
    from src.db.library import get_media
    rec = get_media(media_id)
    if not rec:
        raise HTTPException(404, "Media not found")
    return rec


@router.get("/api/media/by-filename/{filename:path}")
async def get_media_by_filename_endpoint(filename: str):
    """Get media record by filename (for upload response enrichment)."""
    from src.db.library import get_media_by_filename
    rec = get_media_by_filename(filename)
    if not rec:
        raise HTTPException(404, "Media not found")
    return rec


@router.get("/api/media/{media_id}/tags")
async def get_media_tags(media_id: str):
    """Read metadata tags from a media file.

    Returns tags dict + editable flag + supported_fields list.
    """
    from src.db.library import get_media
    from src.media.tags import read_tags, is_taggable
    from src.api.models import MediaTagsResponse

    rec = get_media(media_id)
    if not rec:
        raise HTTPException(404, "Media not found")

    file_path = Path(rec["path"])
    if not file_path.exists():
        raise HTTPException(404, "Media file not found on disk")

    if not is_taggable(file_path):
        return MediaTagsResponse(
            media_id=media_id, filename=rec["filename"],
            tags={}, editable=False, supported_fields=[], has_cover=False,
        )

    result = read_tags(file_path)
    return MediaTagsResponse(
        media_id=media_id, filename=rec["filename"],
        tags=result.tags, editable=result.editable,
        supported_fields=result.supported_fields, has_cover=result.has_cover,
    )


@router.put("/api/media/{media_id}/tags")
async def update_media_tags(media_id: str, req: dict):
    """Write metadata tags to a media file.

    Body: {"tags": {"title": "...", "artist": "...", ...}}
    Copy-on-write: creates *_tagged.ext as new artifact.
    """
    from src.db.library import get_media, register_media
    from src.media.tags import write_tags, is_taggable

    rec = get_media(media_id)
    if not rec:
        raise HTTPException(404, "Media not found")

    file_path = Path(rec["path"])
    if not file_path.exists():
        raise HTTPException(404, "Media file not found on disk")

    if not is_taggable(file_path):
        raise HTTPException(400, f"Format {file_path.suffix} does not support tagging")

    new_tags = req.get("tags", {})
    if not new_tags:
        raise HTTPException(400, "No tags provided")

    # Validate tag values: max length
    for k, v in new_tags.items():
        if not isinstance(v, str):
            raise HTTPException(400, f"Tag value for '{k}' must be a string")
        if len(v) > 1000:
            raise HTTPException(400, f"Tag value for '{k}' too long (max 1000 chars)")

    try:
        tagged_path = write_tags(file_path, new_tags, copy_on_write=True)

        # Register the tagged copy as new media
        tagged_id = register_media(
            filename=tagged_path.name,
            path=str(tagged_path),
            size=tagged_path.stat().st_size,
        )

        return {
            "ok": True,
            "media_id": tagged_id,
            "filename": tagged_path.name,
            "tags_written": list(new_tags.keys()),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        error(f"Tag write failed: {e}")
        raise HTTPException(500, f"Tag write error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  FILE REGISTRY — Central file tracking & cleanup
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/api/file-registry")
async def list_file_registry(
    tool_scope: str = Query("", description="Filter: karaoke, editor, both"),
    file_type: str = Query("", description="Filter: original, derived, project_asset"),
    state: str = Query("active", description="Filter: active, deleted, orphaned"),
    limit: int = Query(100, ge=1, le=500),
):
    """List all files tracked in the central file registry."""
    from src.db.library import list_registered_files
    files = list_registered_files(
        tool_scope=tool_scope, file_type=file_type, state=state, limit=limit
    )
    return {"items": files, "total": len(files)}


@router.get("/api/file-registry/{file_id}")
async def get_file_registry_item(file_id: str):
    """Get a file registry entry with its references."""
    from src.db.library import get_registered_file, get_file_references
    frec = get_registered_file(file_id)
    if not frec:
        raise HTTPException(404, "File not found in registry")
    refs = get_file_references(file_id)
    return {**frec, "references": refs}


@router.get("/api/file-registry/orphaned/list")
async def list_orphaned_files():
    """Find files with no remaining references (cleanup candidates)."""
    from src.db.library import find_orphaned_files
    orphans = find_orphaned_files()
    return {"items": orphans, "total": len(orphans)}


_SAFE_BASES = [Path("data").resolve()]


@router.post("/api/file-registry/cleanup")
async def cleanup_orphaned_files(dry_run: bool = Query(True)):
    """Clean up orphaned files (no references). Use dry_run=false to actually delete."""
    from src.db.library import find_orphaned_files, delete_registered_file
    orphans = find_orphaned_files()
    cleaned = []
    errors = []

    for f in orphans:
        file_path = Path(f["storage_path"]).resolve()
        # Safety: only delete files within allowed base directories
        if not any(file_path.is_relative_to(base) for base in _SAFE_BASES):
            errors.append({"id": f["id"], "path": f["storage_path"], "error": "Outside allowed directory"})
            continue
        if dry_run:
            cleaned.append({"id": f["id"], "path": f["storage_path"], "action": "would_delete"})
        else:
            try:
                if file_path.exists():
                    file_path.unlink()
                delete_registered_file(f["id"], hard=True)
                cleaned.append({"id": f["id"], "path": f["storage_path"], "action": "deleted"})
                info(f"Cleanup: deleted orphaned file {f['storage_path']}")
            except Exception as e:
                errors.append({"id": f["id"], "path": f["storage_path"], "error": str(e)})

    return {"dry_run": dry_run, "cleaned": cleaned, "errors": errors, "total": len(cleaned)}
