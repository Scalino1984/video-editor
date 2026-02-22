"""Generation job manager — submit, poll, download, auto-import, SSE events."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, error, debug
from src.video.generation.base import (
    GenerationProvider, GenRequest, GenJob, GenStatus, GenType,
)

# ── Directories ───────────────────────────────────────────────────────────────

ASSETS_DIR = Path("data/editor/assets")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# ── In-memory job store ───────────────────────────────────────────────────────

_jobs: dict[str, GenJob] = {}
_providers: dict[str, GenerationProvider] = {}
_poll_tasks: dict[str, asyncio.Task] = {}

# SSE callback — set from routes to emit events to the editor
_sse_callback: Any = None

POLL_INTERVAL_S = 3.0
MAX_CONCURRENT = 5


# ── Provider registry ─────────────────────────────────────────────────────────

def register_provider(provider: GenerationProvider) -> None:
    """Register a generation provider."""
    _providers[provider.name] = provider
    info(f"[gen-manager] Provider registered: {provider.name}")


def get_provider(name: str = "luma") -> GenerationProvider | None:
    """Get a registered provider by name."""
    if not _providers and name == "luma":
        # Lazy-register default Luma provider
        try:
            from src.video.generation.luma import LumaProvider
            register_provider(LumaProvider())
        except ImportError:
            pass
    return _providers.get(name)


def _ensure_luma() -> GenerationProvider:
    """Get the Luma provider or raise."""
    p = get_provider("luma")
    if not p:
        raise RuntimeError("Luma Provider nicht verfügbar")
    return p


# ── SSE helpers ───────────────────────────────────────────────────────────────

def set_sse_callback(cb: Any) -> None:
    """Set the SSE emit callback: cb(event_dict)."""
    global _sse_callback
    _sse_callback = cb


def _emit(event_type: str, job: GenJob, **extra: Any) -> None:
    """Emit a generation SSE event."""
    data = {
        "type": event_type,
        "gen_id": job.id,
        "gen_type": job.gen_type.value,
        "status": job.status.value,
        "progress": job.progress,
        "prompt": job.prompt[:80],
        "project_id": job.project_id,
        **extra,
    }
    if _sse_callback:
        try:
            _sse_callback(data)
        except Exception:
            pass
    debug(f"[gen-manager] SSE {event_type}: {job.id} → {job.status.value}")


# ── Submit ────────────────────────────────────────────────────────────────────

async def submit_generation(request: GenRequest, provider_name: str = "luma") -> GenJob:
    """Submit a new generation request. Returns the GenJob immediately."""
    provider = get_provider(provider_name)
    if not provider:
        raise RuntimeError(f"Provider '{provider_name}' nicht registriert")

    # Check availability
    ok, msg = await provider.check_available()
    if not ok:
        raise RuntimeError(f"Provider '{provider_name}' nicht verfügbar: {msg}")

    # Check concurrency limit
    active = sum(1 for j in _jobs.values() if j.status in (GenStatus.pending, GenStatus.processing, GenStatus.downloading))
    if active >= MAX_CONCURRENT:
        raise RuntimeError(f"Maximale parallele Generierungen erreicht ({MAX_CONCURRENT})")

    # Create job
    job = GenJob(
        provider=provider_name,
        gen_type=request.gen_type,
        prompt=request.prompt,
        status=GenStatus.pending,
        project_id=request.project_id,
        aspect_ratio=request.aspect_ratio,
        model=request.model,
        metadata={
            "duration": request.duration,
            "resolution": request.resolution,
            "loop": request.loop,
            "image_format": request.image_format,
        },
    )
    _jobs[job.id] = job
    _emit("gen_started", job)

    # Submit to provider
    try:
        if request.gen_type == GenType.video:
            provider_id, model_used = await provider.generate_video(request)
        else:
            provider_id, model_used = await provider.generate_image(request)

        job.provider_id = provider_id
        job.model = model_used
        job.status = GenStatus.processing
        _emit("gen_processing", job)

    except Exception as e:
        job.status = GenStatus.failed
        job.error = str(e)
        _emit("gen_failed", job, error=str(e))
        return job

    # Start background polling
    task = asyncio.create_task(_poll_loop(job.id))
    _poll_tasks[job.id] = task

    info(f"[gen-manager] Job {job.id} submitted: {request.gen_type.value} provider={provider_name}")
    return job


# ── Poll loop ─────────────────────────────────────────────────────────────────

async def _poll_loop(job_id: str) -> None:
    """Background coroutine that polls provider status until completion."""
    job = _jobs.get(job_id)
    if not job:
        return

    provider = get_provider(job.provider)
    if not provider:
        job.status = GenStatus.failed
        job.error = "Provider nicht verfügbar"
        _emit("gen_failed", job, error=job.error)
        return

    try:
        while job.status == GenStatus.processing:
            await asyncio.sleep(POLL_INTERVAL_S)

            if job.status in (GenStatus.cancelled, GenStatus.failed):
                break

            status, progress, result_url, err = await provider.poll_status(job.provider_id)

            if status == GenStatus.completed and result_url:
                job.progress = 1.0
                job.result_url = result_url
                job.status = GenStatus.downloading
                _emit("gen_downloading", job)

                # Download
                try:
                    ext = "mp4" if job.gen_type == GenType.video else job.metadata.get("image_format", "jpg")
                    dest = ASSETS_DIR / f"gen_{job.id}.{ext}"
                    await provider.download(result_url, dest)
                    job.local_path = str(dest)
                    job.status = GenStatus.completed
                    job.completed_at = datetime.now(timezone.utc).isoformat()
                    _emit("gen_completed", job, local_path=str(dest))
                    info(f"[gen-manager] Job {job.id} completed → {dest.name}")

                    # Auto-import into project if project_id is set
                    if job.project_id:
                        _auto_import(job)

                except Exception as e:
                    job.status = GenStatus.failed
                    job.error = f"Download fehlgeschlagen: {e}"
                    _emit("gen_failed", job, error=job.error)
                    error(f"[gen-manager] Download failed for {job.id}: {e}")
                break

            elif status == GenStatus.failed:
                job.status = GenStatus.failed
                job.error = err or "Generation fehlgeschlagen"
                _emit("gen_failed", job, error=job.error)
                error(f"[gen-manager] Job {job.id} failed: {job.error}")
                break

            else:
                # Still processing
                job.progress = progress
                _emit("gen_progress", job)

    except asyncio.CancelledError:
        job.status = GenStatus.cancelled
        _emit("gen_cancelled", job)
    except Exception as e:
        job.status = GenStatus.failed
        job.error = str(e)
        _emit("gen_failed", job, error=str(e))
        error(f"[gen-manager] Poll error for {job.id}: {e}")
    finally:
        _poll_tasks.pop(job_id, None)


# ── Auto-import ───────────────────────────────────────────────────────────────

def _auto_import(job: GenJob) -> None:
    """Import completed generation as asset into editor project."""
    if not job.local_path or not job.project_id:
        return
    try:
        from src.video.editor import add_asset
        dest = Path(job.local_path)
        if not dest.exists():
            return
        filename = f"AI_{job.gen_type.value}_{job.prompt[:30].replace(' ', '_')}{dest.suffix}"
        # Sanitize filename
        filename = "".join(c for c in filename if c.isalnum() or c in "._-").strip("._")
        if not filename:
            filename = dest.name
        asset = add_asset(job.project_id, filename, dest)
        if asset:
            job.asset_id = asset.id
            info(f"[gen-manager] Auto-imported {dest.name} as asset {asset.id} in project {job.project_id}")
            _emit("gen_imported", job, asset_id=asset.id, filename=filename)
    except Exception as e:
        warn(f"[gen-manager] Auto-import failed for {job.id}: {e}")


# ── Query ─────────────────────────────────────────────────────────────────────

def get_job(job_id: str) -> GenJob | None:
    """Get a generation job by ID."""
    return _jobs.get(job_id)


def list_jobs(project_id: str = "") -> list[GenJob]:
    """List generation jobs, optionally filtered by project."""
    jobs = list(_jobs.values())
    if project_id:
        jobs = [j for j in jobs if j.project_id == project_id]
    return sorted(jobs, key=lambda j: j.created_at, reverse=True)


# ── Cancel ────────────────────────────────────────────────────────────────────

async def cancel_generation(job_id: str) -> bool:
    """Cancel a running generation."""
    job = _jobs.get(job_id)
    if not job:
        return False
    if job.status in (GenStatus.completed, GenStatus.failed, GenStatus.cancelled):
        return False

    # Cancel polling task
    task = _poll_tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()

    # Cancel on provider side
    provider = get_provider(job.provider)
    if provider and job.provider_id:
        await provider.cancel(job.provider_id)

    job.status = GenStatus.cancelled
    _emit("gen_cancelled", job)
    info(f"[gen-manager] Job {job.id} cancelled")
    return True


# ── Delete ────────────────────────────────────────────────────────────────────

async def delete_generation(job_id: str) -> bool:
    """Delete a generation job and its local file."""
    job = _jobs.get(job_id)
    if not job:
        return False

    # Cancel if still running
    if job.status in (GenStatus.pending, GenStatus.processing, GenStatus.downloading):
        await cancel_generation(job_id)

    # Remove local file
    if job.local_path:
        try:
            p = Path(job.local_path)
            if p.exists():
                p.unlink()
                debug(f"[gen-manager] Deleted local file: {p}")
        except Exception as e:
            warn(f"[gen-manager] Failed to delete {job.local_path}: {e}")

    _jobs.pop(job_id, None)
    return True


# ── Manual import ─────────────────────────────────────────────────────────────

def import_generation(job_id: str, project_id: str) -> str | None:
    """Manually import a completed generation into a project.

    Returns the asset_id on success, None on failure.
    """
    job = _jobs.get(job_id)
    if not job or job.status != GenStatus.completed or not job.local_path:
        return None

    old_pid = job.project_id
    job.project_id = project_id
    _auto_import(job)
    if not job.asset_id:
        job.project_id = old_pid  # restore
        return None
    return job.asset_id


# ── Provider status ───────────────────────────────────────────────────────────

async def check_provider(name: str = "luma") -> tuple[bool, str]:
    """Check if a generation provider is available."""
    provider = get_provider(name)
    if not provider:
        return False, f"Provider '{name}' nicht registriert"
    return await provider.check_available()
