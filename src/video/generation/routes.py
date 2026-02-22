"""Generation API routes — FastAPI endpoints for AI video/image generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.utils.logging import info, warn, error
from src.video.generation.base import GenType

router = APIRouter(prefix="/api/editor", tags=["generation"])


# ── Request/Response schemas ──────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    """Request to start a generation."""
    gen_type: str = Field(..., description="'video' or 'image'")
    prompt: str = Field(..., min_length=1, max_length=2000)
    project_id: str = ""
    model: str = ""
    aspect_ratio: str = "16:9"
    # Video
    duration: str = "5s"
    loop: bool = False
    resolution: str = "1080p"
    keyframe_image_url: str = ""
    keyframe_end_url: str = ""
    # Image
    image_format: str = "jpg"
    style_ref_url: str = ""
    modify_image_url: str = ""


class GenerateResponse(BaseModel):
    gen_id: str
    status: str
    gen_type: str
    prompt: str
    model: str = ""


class GenJobResponse(BaseModel):
    id: str
    provider: str
    gen_type: str
    prompt: str
    status: str
    progress: float
    model: str = ""
    aspect_ratio: str = ""
    error: str = ""
    local_path: str = ""
    asset_id: str = ""
    project_id: str = ""
    created_at: str = ""
    completed_at: str = ""
    result_url: str = ""
    metadata: dict = {}


class ImportResponse(BaseModel):
    asset_id: str
    filename: str = ""


class ProviderStatusResponse(BaseModel):
    available: bool
    message: str
    provider: str


# ── Check provider ────────────────────────────────────────────────────────────

@router.get("/generation/status")
async def api_generation_status(provider: str = "luma") -> ProviderStatusResponse:
    """Check if a generation provider is available."""
    from src.video.generation.manager import check_provider
    ok, msg = await check_provider(provider)
    return ProviderStatusResponse(available=ok, message=msg, provider=provider)


# ── Submit generation ─────────────────────────────────────────────────────────

@router.post("/generate")
async def api_generate(body: GenerateRequest) -> GenerateResponse:
    """Start a new AI generation (video or image)."""
    from src.video.generation.base import GenRequest
    from src.video.generation.manager import submit_generation

    # Validate gen_type
    try:
        gen_type = GenType(body.gen_type)
    except ValueError:
        raise HTTPException(400, f"Ungültiger gen_type: {body.gen_type}. Erlaubt: video, image")

    request = GenRequest(
        gen_type=gen_type,
        prompt=body.prompt,
        project_id=body.project_id,
        model=body.model,
        aspect_ratio=body.aspect_ratio,
        duration=body.duration,
        loop=body.loop,
        resolution=body.resolution,
        keyframe_image_url=body.keyframe_image_url,
        keyframe_end_url=body.keyframe_end_url,
        image_format=body.image_format,
        style_ref_url=body.style_ref_url,
        modify_image_url=body.modify_image_url,
    )

    try:
        job = await submit_generation(request)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    return GenerateResponse(
        gen_id=job.id,
        status=job.status.value,
        gen_type=job.gen_type.value,
        prompt=job.prompt,
        model=job.model,
    )


# ── List generations ──────────────────────────────────────────────────────────

@router.get("/generations")
async def api_list_generations(project_id: str = "") -> list[GenJobResponse]:
    """List all generation jobs, optionally filtered by project."""
    from src.video.generation.manager import list_jobs
    jobs = list_jobs(project_id)
    return [
        GenJobResponse(
            id=j.id, provider=j.provider, gen_type=j.gen_type.value,
            prompt=j.prompt, status=j.status.value, progress=j.progress,
            model=j.model, aspect_ratio=j.aspect_ratio, error=j.error,
            local_path=j.local_path, asset_id=j.asset_id,
            project_id=j.project_id, created_at=j.created_at,
            completed_at=j.completed_at, result_url=j.result_url,
            metadata=j.metadata,
        )
        for j in jobs
    ]


# ── Get single generation ────────────────────────────────────────────────────

@router.get("/generations/{gen_id}")
async def api_get_generation(gen_id: str) -> GenJobResponse:
    """Get details of a specific generation job."""
    from src.video.generation.manager import get_job
    job = get_job(gen_id)
    if not job:
        raise HTTPException(404, "Generation nicht gefunden")
    return GenJobResponse(
        id=job.id, provider=job.provider, gen_type=job.gen_type.value,
        prompt=job.prompt, status=job.status.value, progress=job.progress,
        model=job.model, aspect_ratio=job.aspect_ratio, error=job.error,
        local_path=job.local_path, asset_id=job.asset_id,
        project_id=job.project_id, created_at=job.created_at,
        completed_at=job.completed_at, result_url=job.result_url,
        metadata=job.metadata,
    )


# ── Cancel generation ─────────────────────────────────────────────────────────

@router.delete("/generations/{gen_id}")
async def api_cancel_generation(gen_id: str):
    """Cancel or delete a generation job."""
    from src.video.generation.manager import delete_generation
    ok = await delete_generation(gen_id)
    if not ok:
        raise HTTPException(404, "Generation nicht gefunden")
    return {"ok": True, "deleted": gen_id}


# ── Import into project ──────────────────────────────────────────────────────

@router.post("/generations/{gen_id}/import")
async def api_import_generation(gen_id: str, body: dict | None = None):
    """Import a completed generation into an editor project as asset."""
    from src.video.generation.manager import import_generation, get_job

    job = get_job(gen_id)
    if not job:
        raise HTTPException(404, "Generation nicht gefunden")

    if job.status.value != "completed":
        raise HTTPException(400, f"Generation noch nicht abgeschlossen (Status: {job.status.value})")

    project_id = (body or {}).get("project_id", "") or job.project_id
    if not project_id:
        raise HTTPException(400, "project_id erforderlich")

    asset_id = import_generation(gen_id, project_id)
    if not asset_id:
        raise HTTPException(500, "Import fehlgeschlagen")

    return ImportResponse(asset_id=asset_id, filename=Path(job.local_path).name if job.local_path else "")


# ── Auto-scene suggestions ───────────────────────────────────────────────────

class AutoScenesRequest(BaseModel):
    gen_type: str = "video"
    aspect_ratio: str = "16:9"


class SceneSuggestion(BaseModel):
    title: str
    prompt: str
    mood: str = ""
    lyrics_ref: str = ""


@router.post("/projects/{pid}/auto-scenes")
async def api_auto_scenes(pid: str, body: AutoScenesRequest | None = None):
    """Analyze project lyrics and generate 5 AI scene suggestions."""
    from src.video.generation.scenes import generate_auto_scenes
    from src.video.editor import get_project

    p = get_project(pid)
    if not p:
        raise HTTPException(404, "Projekt nicht gefunden")

    req = body or AutoScenesRequest()
    try:
        scenes = await generate_auto_scenes(pid, req.gen_type, req.aspect_ratio)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    return {"scenes": scenes, "count": len(scenes)}

