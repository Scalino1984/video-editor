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
    EDITOR_DIR,
    create_project, get_project, list_projects,
    save_project, load_project,
    add_asset, add_clip, remove_clip, update_clip,
    split_clip, add_effect, remove_effect,
    undo, redo, _push_undo,
    render_project, render_project_with_progress, render_loop_video,
    get_timeline_summary,
)

router = APIRouter(prefix="/api/editor", tags=["editor"])


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
        "sub_lines", "sub_bg_enabled", "sub_bg_color", "video_fit",
    }
    changed = []
    for k, v in data.items():
        if k in allowed:
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
    path = EDITOR_DIR / "projects" / filename
    if not path.exists():
        raise HTTPException(404, "Project file not found")
    proj = load_project(path)
    if not proj:
        raise HTTPException(500, "Failed to load project")
    return proj.to_dict()


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
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    dest = assets_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

    asset = add_asset(pid, safe_name, dest)
    if not asset:
        raise HTTPException(500, "Failed to add asset")
    return asset.to_dict()


@router.delete("/projects/{pid}/assets/{asset_id}")
async def api_remove_asset(pid: str, asset_id: str):
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    if asset_id not in p.assets:
        raise HTTPException(404, "Asset not found")
    _push_undo(pid)
    # Remove clips using this asset
    p.clips = [c for c in p.clips if c.asset_id != asset_id]
    del p.assets[asset_id]
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
    """Import audio + subtitles from a completed karaoke job."""
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")

    # Check both output dir and uploads dir
    job_dir = Path("data/output") / job_id
    upload_dir = Path("data/uploads")

    if not job_dir.exists():
        raise HTTPException(404, f"Job output not found: {job_id}")

    imported = []

    # Find audio file — check job output dir first, then uploads
    for search_dir in [job_dir, upload_dir]:
        if imported and any(a.get("type") == "audio" for a in imported):
            break
        for ext in (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".opus"):
            for f in search_dir.glob(f"*{ext}"):
                # For uploads dir, only match files that start with job_id prefix
                if search_dir == upload_dir and not f.name.startswith(job_id[:8]):
                    continue
                asset = add_asset(pid, f.name, f)
                if asset:
                    imported.append(asset.to_dict())
                    add_clip(pid, asset.id, track="audio", start=0)
                break
            if imported and any(a.get("type") == "audio" for a in imported):
                break

    # Find subtitle files — prefer .ass over .srt, only import ONE format
    sub_imported = False
    for ext in (".ass", ".srt"):
        if sub_imported:
            break
        for f in job_dir.glob(f"*{ext}"):
            asset = add_asset(pid, f.name, f)
            if asset:
                imported.append(asset.to_dict())
                add_clip(pid, asset.id, track="subtitle", start=0)
                sub_imported = True
            break

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


@router.put("/projects/{pid}/clips/{clip_id}")
async def api_update_clip(pid: str, clip_id: str, body: dict):
    clip = update_clip(pid, clip_id, **body)
    if not clip:
        raise HTTPException(404, "Clip not found")
    return clip.to_dict()


@router.delete("/projects/{pid}/clips/{clip_id}")
async def api_remove_clip(pid: str, clip_id: str):
    ok = remove_clip(pid, clip_id)
    if not ok:
        raise HTTPException(404, "Clip not found")
    return {"removed": clip_id}


@router.post("/projects/{pid}/clips/{clip_id}/split")
async def api_split_clip(pid: str, clip_id: str, at_time: float = 0):
    result = split_clip(pid, clip_id, at_time)
    if not result:
        raise HTTPException(400, "Cannot split at this position")
    c1, c2 = result
    return {"clip1": c1.to_dict(), "clip2": c2.to_dict()}


@router.post("/projects/{pid}/clips/{clip_id}/effects")
async def api_add_effect(pid: str, clip_id: str, body: dict):
    eff = add_effect(pid, clip_id, body.get("type", ""), body.get("params", {}))
    if not eff:
        raise HTTPException(404, "Clip not found")
    return eff.to_dict()


@router.delete("/projects/{pid}/clips/{clip_id}/effects/{idx}")
async def api_remove_effect(pid: str, clip_id: str, idx: int):
    ok = remove_effect(pid, clip_id, idx)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"removed": idx}


# ── Render ────────────────────────────────────────────────────────────────────

@router.put("/projects/{pid}/sub-settings")
async def api_update_sub_settings(pid: str, data: dict = None):
    """Update subtitle rendering settings."""
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    if not data:
        raise HTTPException(400, "No data")
    allowed = {
        "sub_font", "sub_size", "sub_color", "sub_outline_color",
        "sub_outline_width", "sub_position", "sub_margin_v", "sub_lines",
    }
    for k, v in data.items():
        if k in allowed:
            setattr(p, k, v)
    return {"ok": True, **{k: getattr(p, k) for k in allowed}}


@router.post("/projects/{pid}/render")
async def api_render_project(pid: str):
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
    path = EDITOR_DIR / "renders" / filename
    if not path.exists():
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
    path = Path(asset.path)
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
