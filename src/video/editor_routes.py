"""Video Editor API routes — FastAPI endpoints for timeline editing."""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from src.utils.logging import info, warn, error
from src.video.editor import (
    EDITOR_DIR, TRACK_TYPES,
    create_project, get_project, list_projects,
    save_project, load_project,
    add_asset, add_clip, remove_clip, update_clip,
    split_clip, add_effect, remove_effect,
    undo, redo, _push_undo,
    render_project, render_project_with_progress, render_loop_video,
    get_timeline_summary,
    add_track, remove_track, update_track, reorder_tracks,
    legacy_project_to_v2,
)

router = APIRouter(prefix="/api/editor", tags=["editor"])

_INT_FIELDS = {"width", "height", "fps", "crf", "sub_size", "sub_outline_width", "sub_margin_v", "sub_y_percent", "sub_lines"}

LOOP_VIDEOS_DIR = Path("src/library/loop_videos")

# Mapping: project aspect ratio → loop video subfolder
_LOOP_FOLDER_MAP: dict[str, str] = {
    "16:9": "1280x720",
    "9:16": "720x1280",
    "1:1": "1000x1000",
}


def _aspect_ratio(w: int, h: int) -> str:
    """Determine aspect ratio bucket from project dimensions."""
    from math import gcd
    g = gcd(w, h)
    rw, rh = w // g, h // g
    if rw == rh:
        return "1:1"
    if rw / rh > 1:
        return "16:9"  # landscape
    return "9:16"  # portrait


# ── Loop Video Library ────────────────────────────────────────────────────────

@router.get("/loop-videos")
async def api_list_loop_videos(width: int = 0, height: int = 0):
    """List available loop videos, optionally filtered by project resolution."""
    result: dict[str, list[dict]] = {}

    if not LOOP_VIDEOS_DIR.is_dir():
        return {}

    if width > 0 and height > 0:
        folder_name = _LOOP_FOLDER_MAP.get(_aspect_ratio(width, height))
        folders = [folder_name] if folder_name else []
    else:
        folders = sorted(d.name for d in LOOP_VIDEOS_DIR.iterdir() if d.is_dir())

    for fname in folders:
        folder = LOOP_VIDEOS_DIR / fname
        if not folder.is_dir():
            continue
        videos = []
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in (".mp4", ".mov", ".webm"):
                # Extract display name (e.g. "Car_1280x720.mp4" → "Car")
                display = f.stem.rsplit("_", 1)[0] if "_" in f.stem else f.stem
                videos.append({
                    "filename": f.name,
                    "display_name": display,
                    "folder": fname,
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                    "url": f"/api/editor/loop-videos/{fname}/{f.name}",
                    "thumb_url": f"/api/editor/loop-videos/{fname}/{f.name}/thumb",
                })
        if videos:
            result[fname] = videos

    return result


_VIDEO_MTYPE = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}


@router.get("/loop-videos/{folder}/{filename}")
async def api_serve_loop_video(folder: str, filename: str):
    """Serve a loop video file for preview / playback."""
    path = (LOOP_VIDEOS_DIR / folder / filename).resolve()
    if not path.is_relative_to(LOOP_VIDEOS_DIR.resolve()) or not path.exists():
        raise HTTPException(404, "Not found")
    mt = _VIDEO_MTYPE.get(path.suffix.lower(), "video/mp4")
    return FileResponse(path, media_type=mt, filename=filename)


@router.get("/loop-videos/{folder}/{filename}/thumb")
async def api_loop_video_thumb(folder: str, filename: str):
    """Generate and serve a thumbnail for a loop video."""
    path = (LOOP_VIDEOS_DIR / folder / filename).resolve()
    if not path.is_relative_to(LOOP_VIDEOS_DIR.resolve()) or not path.exists():
        raise HTTPException(404, "Not found")
    # Cache thumbnail in EDITOR_DIR/assets
    thumb_name = f"loopthumb_{folder}_{Path(filename).stem}.jpg"
    thumb_path = EDITOR_DIR / "assets" / thumb_name
    if not thumb_path.exists():
        from src.utils.media_executor import run_media_subprocess
        try:
            run_media_subprocess(
                ["ffmpeg", "-y", "-i", str(path), "-ss", "1", "-frames:v", "1",
                 "-vf", "scale=160:-1", str(thumb_path)],
                tool="ffmpeg", description=f"loop thumb {filename}",
                timeout=15, heavy=False,
            )
        except Exception:
            raise HTTPException(500, "Thumbnail generation failed")
    if not thumb_path.exists():
        raise HTTPException(500, "Thumbnail not created")
    return FileResponse(thumb_path, media_type="image/jpeg")


@router.post("/projects/{pid}/import-loop-video")
async def api_import_loop_video(
    pid: str,
    folder: str = Form(...),
    filename: str = Form(...),
    add_to_timeline: bool = Form(True),
):
    """Import a loop video from the library into the project as asset + clip."""
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    src_path = (LOOP_VIDEOS_DIR / folder / filename).resolve()
    if not src_path.is_relative_to(LOOP_VIDEOS_DIR.resolve()) or not src_path.exists():
        raise HTTPException(404, "Loop video not found")

    # Copy to assets dir
    safe_name = filename.replace("/", "_").replace("\\", "_")
    dest = EDITOR_DIR / "assets" / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    shutil.copy2(src_path, dest)

    asset = add_asset(pid, safe_name, dest)
    if not asset:
        raise HTTPException(500, "Failed to add asset")

    clip_data = None
    if add_to_timeline:
        clip = add_clip(pid, asset.id, track="video", start=0, loop=True)
        if clip:
            clip_data = clip.to_dict()

    return {"asset": asset.to_dict(), "clip": clip_data}


# ── Project CRUD ──────────────────────────────────────────────────────────────

@router.get("/projects")
async def api_list_projects():
    return list_projects()


@router.post("/projects")
async def api_create_project(
    name: str = Form("Untitled"),
    width: int = Form(1920),
    height: int = Form(1080),
    fps: float = Form(30),
):
    p = create_project(name, width, height, fps)
    return p.to_dict()


@router.get("/projects/{pid}")
async def api_get_project(pid: str):
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return p.to_dict()


@router.put("/projects/{pid}")
async def api_update_project(pid: str, data: dict):
    """Update project properties (name, width, height, fps, crf, etc.)."""
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    _push_undo(pid)
    allowed = {
        "name", "width", "height", "fps", "preset", "crf", "audio_bitrate",
        "sub_font", "sub_size", "sub_color", "sub_outline_color",
        "sub_outline_width", "sub_position", "sub_margin_v", "sub_y_percent",
        "sub_lines", "sub_bg_enabled", "sub_bg_color", "sub_highlight_color", "video_fit",
    }
    changed = []
    for k, v in data.items():
        if k in allowed:
            if k in _INT_FIELDS:
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    continue
            setattr(p, k, v)
            changed.append(k)
    if not changed:
        raise HTTPException(400, "No valid fields to update")
    return {"ok": True, "changed": changed}


@router.post("/projects/{pid}/save")
async def api_save_project(pid: str):
    path = save_project(pid)
    if not path:
        raise HTTPException(404, "Project not found")
    return {"saved": str(path)}


@router.get("/saved-projects")
async def api_list_saved_projects():
    """List saved project JSON files on disk."""
    proj_dir = EDITOR_DIR / "projects"
    results = []
    for f in sorted(proj_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            from datetime import datetime
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            results.append({
                "filename": f.name,
                "name": data.get("name", f.stem),
                "id": data.get("id", f.stem),
                "size_kb": round(f.stat().st_size / 1024, 1),
                "date": mtime.strftime("%d.%m.%y %H:%M"),
            })
        except Exception:
            pass
    return results


@router.post("/load-project/{filename}")
async def api_load_project(filename: str):
    """Load a saved project from disk."""
    path = (EDITOR_DIR / "projects" / filename).resolve()
    if not path.is_relative_to((EDITOR_DIR / "projects").resolve()) or not path.exists():
        raise HTTPException(404, "Project file not found")
    proj = load_project(path)
    if not proj:
        raise HTTPException(500, "Failed to load project")
    return proj.to_dict()


@router.delete("/delete-project/{filename}")
async def api_delete_saved_project(filename: str):
    """Delete a saved project JSON file from disk (safe: path-traversal protected)."""
    path = (EDITOR_DIR / "projects" / filename).resolve()
    if not path.is_relative_to((EDITOR_DIR / "projects").resolve()):
        raise HTTPException(400, "Invalid filename")
    if not path.exists():
        raise HTTPException(404, "Project file not found")
    if path.suffix.lower() != ".json":
        raise HTTPException(400, "Only JSON project files can be deleted")
    path.unlink()
    return {"deleted": filename}


@router.post("/projects/{pid}/undo")
async def api_undo(pid: str):
    ok = undo(pid)
    p = get_project(pid)
    return {"success": ok, "project": p.to_dict() if p else None}


@router.post("/projects/{pid}/redo")
async def api_redo(pid: str):
    ok = redo(pid)
    p = get_project(pid)
    return {"success": ok, "project": p.to_dict() if p else None}


# ── Assets ────────────────────────────────────────────────────────────────────

@router.post("/projects/{pid}/assets")
async def api_upload_asset(pid: str, file: UploadFile = File(...)):
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")

    # Save uploaded file
    assets_dir = EDITOR_DIR / "assets"
    safe_name = (file.filename or "upload").replace("/", "_").replace("\\", "_")
    dest = assets_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

    asset = add_asset(pid, safe_name, dest)
    if not asset:
        raise HTTPException(500, "Failed to add asset")

    # Register in file registry
    try:
        from src.db.library import register_file, add_file_reference
        file_id = register_file(
            storage_path=str(dest),
            original_name=safe_name,
            file_type="project_asset",
            tool_scope="editor",
            size=len(content),
            project_id=pid,
        )
        add_file_reference(file_id, "project", pid)
    except Exception:
        pass  # non-critical

    return asset.to_dict()


@router.delete("/projects/{pid}/assets/{asset_id}")
async def api_remove_asset(pid: str, asset_id: str):
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    if asset_id not in p.assets:
        raise HTTPException(404, "Asset not found")

    asset_path = p.assets[asset_id].path
    thumb_path = p.assets[asset_id].thumbnail

    _push_undo(pid)
    # Remove clips using this asset
    p.clips = [c for c in p.clips if c.asset_id != asset_id]
    del p.assets[asset_id]

    # Clean up physical file and file registry if in editor assets dir
    try:
        from src.db.library import get_file_by_path, check_file_has_references, delete_registered_file, remove_file_references
        asset_file = Path(asset_path)
        editor_assets = EDITOR_DIR / "assets"
        if asset_file.exists() and asset_file.resolve().is_relative_to(editor_assets.resolve()):
            # Remove project reference from file registry
            frec = get_file_by_path(asset_path)
            if frec:
                remove_file_references("project", pid)
                if not check_file_has_references(frec["id"]):
                    delete_registered_file(frec["id"], hard=True)
                    asset_file.unlink(missing_ok=True)
            else:
                asset_file.unlink(missing_ok=True)
            # Clean up thumbnail
            if thumb_path:
                Path(thumb_path).unlink(missing_ok=True)
    except Exception:
        pass  # non-critical

    return {"removed": asset_id}


@router.get("/projects/{pid}/assets/{asset_id}/thumb")
async def api_asset_thumbnail(pid: str, asset_id: str):
    p = get_project(pid)
    if not p or asset_id not in p.assets:
        raise HTTPException(404)
    thumb = p.assets[asset_id].thumbnail
    if thumb and Path(thumb).exists():
        return FileResponse(thumb)
    raise HTTPException(404, "No thumbnail")


# ── Import from Karaoke Sub Tool ──────────────────────────────────────────────

@router.post("/projects/{pid}/import-job/{job_id}")
async def api_import_from_job(pid: str, job_id: str):
    """Import audio + subtitles from a completed karaoke job.

    Files are copied to editor assets dir so they survive job deletion.
    Cross-references are tracked in the file registry.
    """
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")

    # Validate job_id to prevent path traversal
    job_dir = (Path("data/output") / job_id).resolve()
    if not job_dir.is_relative_to(Path("data/output").resolve()):
        raise HTTPException(400, "Invalid job_id")
    upload_dir = Path("data/uploads")
    assets_dir = EDITOR_DIR / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    if not job_dir.exists():
        raise HTTPException(404, f"Job output not found: {job_id}")

    _push_undo(pid)
    imported = []

    def _copy_and_add(source: Path, track: str) -> dict | None:
        """Copy file to editor assets dir and add as project asset."""
        dest = assets_dir / f"{uuid.uuid4().hex[:8]}_{source.name}"
        shutil.copy2(source, dest)
        asset = add_asset(pid, source.name, dest)
        if asset:
            add_clip(pid, asset.id, track=track, start=0)
            # Register in file registry with cross-reference
            try:
                from src.db.library import register_file, add_file_reference
                file_id = register_file(
                    storage_path=str(dest),
                    original_name=source.name,
                    file_type="project_asset",
                    tool_scope="both",
                    job_id=job_id,
                    project_id=pid,
                )
                add_file_reference(file_id, "project", pid)
                add_file_reference(file_id, "job", job_id)
            except Exception:
                pass  # non-critical
            return asset.to_dict()
        return None

    # Find audio file — check job output dir first, then uploads
    for search_dir in [job_dir, upload_dir]:
        if imported and any(a.get("type") == "audio" for a in imported):
            break
        for ext in (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus"):
            for f in search_dir.glob(f"*{ext}"):
                # For uploads dir, only match files that start with job_id prefix
                if search_dir == upload_dir and not f.name.startswith(job_id[:8]):
                    continue
                result = _copy_and_add(f, "audio")
                if result:
                    imported.append(result)
                break
            if imported and any(a.get("type") == "audio" for a in imported):
                break

    # Find subtitle files — import ALL available formats (.ass, .srt, .vtt, .lrc)
    for ext in (".ass", ".srt", ".vtt", ".lrc"):
        for f in job_dir.glob(f"*{ext}"):
            result = _copy_and_add(f, "subtitle")
            if result:
                imported.append(result)
            break

    # Track linked karaoke job for cross-tool navigation
    if imported:
        p.source_job_id = job_id

    return {"imported": len(imported), "assets": imported}


# ── Clips ─────────────────────────────────────────────────────────────────────

@router.post("/projects/{pid}/clips")
async def api_add_clip(
    pid: str,
    asset_id: str = Form(...),
    track: str = Form("video"),
    start: float = Form(-1),
    duration: float = Form(0),
    loop: bool = Form(False),
    volume: float = Form(1.0),
    speed: float = Form(1.0),
):
    clip = add_clip(
        pid, asset_id, track=track, start=start, duration=duration,
        loop=loop, volume=volume, speed=speed,
    )
    if not clip:
        raise HTTPException(400, "Failed to add clip")
    return clip.to_dict()


_CLIP_ALLOWED = {"start", "duration", "in_point", "out_point", "volume", "speed", "loop", "z_index", "sub_style", "sub_position", "track", "opacity", "blend_mode"}


@router.put("/projects/{pid}/clips/{clip_id}")
async def api_update_clip(pid: str, clip_id: str, body: dict):
    filtered = {k: v for k, v in body.items() if k in _CLIP_ALLOWED}
    if not filtered:
        raise HTTPException(400, "No valid fields")
    _push_undo(pid)
    clip = update_clip(pid, clip_id, **filtered)
    if not clip:
        raise HTTPException(404, "Clip not found")
    return clip.to_dict()


@router.delete("/projects/{pid}/clips/{clip_id}")
async def api_remove_clip(pid: str, clip_id: str):
    _push_undo(pid)
    ok = remove_clip(pid, clip_id)
    if not ok:
        raise HTTPException(404, "Clip not found")
    return {"removed": clip_id}


@router.post("/projects/{pid}/clips/{clip_id}/split")
async def api_split_clip(pid: str, clip_id: str, at_time: float = 0):
    _push_undo(pid)
    result = split_clip(pid, clip_id, at_time)
    if not result:
        raise HTTPException(400, "Cannot split at this position")
    c1, c2 = result
    return {"clip1": c1.to_dict(), "clip2": c2.to_dict()}


@router.post("/projects/{pid}/clips/{clip_id}/effects")
async def api_add_effect(pid: str, clip_id: str, body: dict):
    _push_undo(pid)
    eff = add_effect(pid, clip_id, body.get("type", ""), body.get("params", {}))
    if not eff:
        raise HTTPException(404, "Clip not found")
    return eff.to_dict()


@router.delete("/projects/{pid}/clips/{clip_id}/effects/{idx}")
async def api_remove_effect(pid: str, clip_id: str, idx: int):
    _push_undo(pid)
    ok = remove_effect(pid, clip_id, idx)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"removed": idx}


# ── Tracks (v2) ──────────────────────────────────────────────────────────────

@router.post("/projects/{pid}/tracks")
async def api_add_track(pid: str, body: dict):
    """Add a new track (layer) to the project (+)."""
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    track_type = body.get("type", "")
    if track_type not in TRACK_TYPES:
        raise HTTPException(400, f"Invalid track type: {track_type}. Must be one of: {', '.join(sorted(TRACK_TYPES))}")
    track = add_track(pid, track_type, name=body.get("name", ""), index=body.get("index"))
    if not track:
        raise HTTPException(500, "Failed to add track")
    return track.to_dict()


@router.delete("/projects/{pid}/tracks/{track_id}")
async def api_remove_track(pid: str, track_id: str, force: bool = False,
                           migrate_to_track_id: str | None = None):
    """Remove a track (layer) from the project (-).

    Empty tracks can always be removed. Non-empty tracks require force=True
    or migrate_to_track_id to move clips to another track.
    """
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    ok = remove_track(pid, track_id, force=force, migrate_to_track_id=migrate_to_track_id)
    if not ok:
        raise HTTPException(
            400,
            "Cannot remove track — it may contain clips. Use force=true or migrate_to_track_id.",
        )
    return {"removed": track_id}


@router.put("/projects/{pid}/tracks/{track_id}")
async def api_update_track(pid: str, track_id: str, body: dict):
    """Update track properties (name, index, enabled, locked, mute, solo, opacity, gain_db)."""
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    _ALLOWED = {"name", "index", "enabled", "locked", "mute", "solo", "opacity", "gain_db"}
    filtered = {k: v for k, v in body.items() if k in _ALLOWED}
    if not filtered:
        raise HTTPException(400, "No valid fields to update")
    track = update_track(pid, track_id, **filtered)
    if not track:
        raise HTTPException(404, "Track not found")
    return track.to_dict()


@router.post("/projects/{pid}/tracks/reorder")
async def api_reorder_tracks(pid: str, body: dict):
    """Reorder tracks by providing ordered list of track IDs."""
    track_ids = body.get("track_ids", [])
    if not track_ids or not isinstance(track_ids, list):
        raise HTTPException(400, "Provide track_ids as a list")
    ok = reorder_tracks(pid, track_ids)
    if not ok:
        raise HTTPException(400, "Invalid track IDs")
    p = get_project(pid)
    return {"tracks": [t.to_dict() for t in p.tracks]}


# ── Render ────────────────────────────────────────────────────────────────────

@router.put("/projects/{pid}/sub-settings")
async def api_update_sub_settings(pid: str, data: dict | None = None):
    """Update subtitle rendering settings."""
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    if not data:
        raise HTTPException(400, "No data")
    _push_undo(pid)
    allowed = {
        "sub_font", "sub_size", "sub_color", "sub_outline_color",
        "sub_outline_width", "sub_position", "sub_margin_v", "sub_lines",
        "sub_highlight_color", "sub_y_percent", "sub_bg_enabled", "sub_bg_color",
    }
    for k, v in data.items():
        if k in allowed:
            if k in _INT_FIELDS:
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    continue
            setattr(p, k, v)
    return {"ok": True, **{k: getattr(p, k) for k in allowed}}


@router.post("/projects/{pid}/render")
async def api_render_project(pid: str):
    from src.utils.media_executor import check_media_capacity
    has_cap, running, queued = check_media_capacity()
    if not has_cap:
        raise HTTPException(429, f"System ausgelastet — {running} laufende, {queued} wartende Jobs. Bitte später erneut versuchen.")
    p = get_project(pid)
    if not p or not p.clips:
        raise HTTPException(400, "No clips to render")
    output, err = render_project(pid)
    if not output:
        raise HTTPException(500, f"Render failed: {err}")
    return {
        "file": output.name,
        "path": str(output),
        "size_mb": round(output.stat().st_size / (1024 * 1024), 1),
        "download_url": f"/api/editor/renders/{output.name}",
    }


_render_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="render")


@router.post("/projects/{pid}/render-stream")
async def api_render_stream(pid: str):
    """Render with real-time SSE progress (percent + phase text)."""
    from src.utils.media_executor import check_media_capacity
    has_cap, running, queued = check_media_capacity()
    if not has_cap:
        raise HTTPException(429, f"System ausgelastet — {running} laufende, {queued} wartende Jobs. Bitte später erneut versuchen.")
    p = get_project(pid)
    if not p or not p.clips:
        raise HTTPException(400, "No clips to render")

    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()

    def _progress_cb(phase: str, pct: int) -> None:
        loop.call_soon_threadsafe(q.put_nowait, {"phase": phase, "percent": pct})

    def _run() -> tuple[Path | None, str]:
        return render_project_with_progress(pid, progress_cb=_progress_cb)

    async def _generate():
        future = loop.run_in_executor(_render_pool, _run)
        try:
            while not future.done():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'phase': '', 'percent': -1})}\n\n"
            # Drain remaining events
            while not q.empty():
                ev = q.get_nowait()
                yield f"data: {json.dumps(ev)}\n\n"
            # Get result
            output, err = future.result()
            if output and output.exists():
                mb = round(output.stat().st_size / (1024 * 1024), 1)
                yield f"data: {json.dumps({'status': 'done', 'percent': 100, 'phase': 'Fertig', 'file': output.name, 'size_mb': mb, 'download_url': f'/api/editor/renders/{output.name}'})}\n\n"
            else:
                yield f"data: {json.dumps({'status': 'error', 'percent': -1, 'phase': 'Fehler', 'message': err or 'Unbekannter Fehler'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'percent': -1, 'phase': 'Fehler', 'message': str(e)})}\n\n"

    return StreamingResponse(
        _generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/projects/{pid}/render-loop")
async def api_render_loop(
    pid: str,
    asset_id: str = Form(...),
    loop_count: int = Form(3),
    duration: float = Form(0),
    effects: str = Form("[]"),
    width: int = Form(1920),
    height: int = Form(1080),
):
    from src.utils.media_executor import check_media_capacity
    has_cap, running, queued = check_media_capacity()
    if not has_cap:
        raise HTTPException(429, f"System ausgelastet — {running} laufende, {queued} wartende Jobs. Bitte später erneut versuchen.")
    p = get_project(pid)
    if not p or asset_id not in p.assets:
        raise HTTPException(404, "Asset not found")
    asset = p.assets[asset_id]
    output = EDITOR_DIR / "renders" / f"loop_{uuid.uuid4().hex[:8]}.mp4"
    try:
        efx = json.loads(effects)
    except json.JSONDecodeError:
        efx = []
    result = render_loop_video(
        Path(asset.path), output,
        loop_count=loop_count, duration=duration,
        effects=efx, width=width, height=height,
    )
    if not result:
        raise HTTPException(500, "Loop render failed")
    return {"file": output.name, "size_mb": round(output.stat().st_size / (1024 * 1024), 1)}


@router.get("/renders/{filename}")
async def api_download_render(filename: str):
    path = (EDITOR_DIR / "renders" / filename).resolve()
    if not path.is_relative_to((EDITOR_DIR / "renders").resolve()) or not path.exists():
        raise HTTPException(404)
    return FileResponse(
        path, media_type="video/mp4", filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{pid}/assets/{asset_id}/file")
async def api_asset_file(pid: str, asset_id: str):
    """Serve the actual asset file for media playback."""
    p = get_project(pid)
    if not p or asset_id not in p.assets:
        raise HTTPException(404)
    asset = p.assets[asset_id]
    path = Path(asset.path).resolve()
    # Validate path is within allowed directories
    editor_root = EDITOR_DIR.resolve()
    output_root = Path("data/output").resolve()
    if not (path.is_relative_to(editor_root) or path.is_relative_to(output_root)):
        raise HTTPException(403, "Access denied")
    if not path.exists():
        raise HTTPException(404, "File not found")
    # Determine media type
    ext = path.suffix.lower()
    media_types = {
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
        ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".aac": "audio/aac",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".gif": "image/gif",
        ".srt": "text/plain", ".ass": "text/plain", ".vtt": "text/plain",
    }
    mt = media_types.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=mt, filename=asset.filename)


# ── AI Chat for Editor ────────────────────────────────────────────────────────

@router.get("/projects/{pid}/summary")
async def api_timeline_summary(pid: str):
    return {"summary": get_timeline_summary(pid)}


@router.post("/projects/{pid}/ai-chat")
async def api_editor_ai_chat(pid: str, body: dict):
    """AI chat with full editor access — streaming response."""
    message = body.get("message", "")
    history = body.get("history", [])

    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")

    async def generate():
        try:
            from src.video.ai_tools import run_editor_chat
            async for chunk in run_editor_chat(pid, message, history):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except ImportError as e:
            yield f"data: {json.dumps({'text': f'AI not available: {e}'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'text': f'Error: {e}'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
