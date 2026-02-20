"""Overlay API routes — browse, inspect, and serve overlay video assets."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import FileResponse

from src.utils.logging import info
from src.video.overlay_service import (
    ALLOWED_OVERLAY_EXTENSIONS,
    MAX_OVERLAYS_PER_PROJECT,
    VALID_BLEND_MODES,
    get_overlay,
    get_overlay_path,
    scan_overlays,
)

router = APIRouter(prefix="/api/overlays", tags=["overlays"])


# ── List / Get overlays ──────────────────────────────────────────────────────


@router.get("")
async def api_list_overlays(
    q: str = Query("", description="Search filter on name/filename"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List available overlay assets from the overlay library."""
    overlays = scan_overlays()

    if q:
        q_lower = q.lower()
        overlays = [o for o in overlays if q_lower in o.name.lower() or q_lower in o.filename.lower()]

    total = len(overlays)
    page = overlays[offset: offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [o.to_dict() for o in page],
    }


@router.get("/blend-modes")
async def api_list_blend_modes():
    """List supported blend modes for overlay items."""
    return {"blend_modes": sorted(VALID_BLEND_MODES)}


@router.get("/{overlay_id}")
async def api_get_overlay(overlay_id: str):
    """Get details for a single overlay asset."""
    asset = get_overlay(overlay_id)
    if not asset:
        raise HTTPException(404, "Overlay not found")
    return asset.to_dict()


@router.get("/{overlay_id}/file")
async def api_serve_overlay_file(overlay_id: str):
    """Serve the overlay video file for preview/playback."""
    file_path = get_overlay_path(overlay_id)
    if not file_path:
        raise HTTPException(404, "Overlay not found")

    media_types = {".mp4": "video/mp4", ".mov": "video/quicktime"}
    mt = media_types.get(file_path.suffix.lower(), "video/mp4")
    return FileResponse(file_path, media_type=mt, filename=file_path.name)


# ── Import overlay into editor project ────────────────────────────────────────


@router.post("/{overlay_id}/import/{pid}")
async def api_import_overlay_to_project(
    overlay_id: str,
    pid: str,
    start: float = Form(0.0),
    duration: float = Form(0.0),
    opacity: float = Form(1.0),
    blend_mode: str = Form("normal"),
):
    """Import an overlay from the library into an editor project as asset + clip."""
    from src.video.editor import (
        EDITOR_DIR,
        get_project,
        add_asset,
        add_clip,
    )

    # Validate project
    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Project not found")

    # Validate overlay
    file_path = get_overlay_path(overlay_id)
    if not file_path:
        raise HTTPException(404, "Overlay not found")

    # Validate parameters
    if not (0.0 <= opacity <= 1.0):
        raise HTTPException(422, "opacity must be between 0.0 and 1.0")
    if blend_mode not in VALID_BLEND_MODES:
        raise HTTPException(422, f"Invalid blend_mode. Must be one of: {sorted(VALID_BLEND_MODES)}")

    # Check overlay limit
    overlay_clips = [c for c in p.clips if c.track == "overlay"]
    if len(overlay_clips) >= MAX_OVERLAYS_PER_PROJECT:
        raise HTTPException(400, f"Maximum {MAX_OVERLAYS_PER_PROJECT} overlays per project exceeded")

    # Copy file to project assets
    assets_dir = EDITOR_DIR / "assets"
    safe_name = file_path.name.replace("/", "_").replace("\\", "_")
    dest = assets_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    shutil.copy2(file_path, dest)

    # Add as asset
    asset = add_asset(pid, safe_name, dest)
    if not asset:
        raise HTTPException(500, "Failed to add overlay asset")

    # Determine duration
    clip_duration = duration if duration > 0 else asset.duration
    if clip_duration <= 0:
        clip_duration = 5.0

    # Add as overlay clip
    clip = add_clip(
        pid, asset.id, track="overlay", start=start, duration=clip_duration,
        opacity=opacity, blend_mode=blend_mode,
    )
    if not clip:
        raise HTTPException(500, "Failed to add overlay clip")

    info(f"[overlay] Imported {file_path.name} into project {pid} (opacity={opacity}, blend={blend_mode})")
    return {"asset": asset.to_dict(), "clip": clip.to_dict()}
