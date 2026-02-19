"""Central media job executor with concurrency limits, CPU/IO priority, and thread control.

All ffmpeg and Demucs subprocess calls MUST go through this module to prevent
resource exhaustion on laptops / low-core machines.

ENV configuration:
    MAX_MEDIA_JOBS         — max concurrent heavy media jobs (default 1)
    MAX_PENDING_MEDIA_JOBS — max queued+running jobs before 429 backpressure (default 3)
    FFMPEG_THREADS         — -threads flag for ffmpeg (default 2)
    MEDIA_NICE             — nice value for subprocesses (default 10, Linux only)
    MEDIA_IONICE_CLASS     — ionice class (default 2 = best-effort, Linux only)
    MEDIA_IONICE_LEVEL     — ionice level (default 7, Linux only)
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, debug, render_log

# ── Configuration via ENV ─────────────────────────────────────────────────────

MAX_MEDIA_JOBS: int = int(os.environ.get("MAX_MEDIA_JOBS", "1"))
MAX_PENDING_MEDIA_JOBS: int = int(os.environ.get("MAX_PENDING_MEDIA_JOBS", "3"))
FFMPEG_THREADS: int = int(os.environ.get("FFMPEG_THREADS", "2"))
MEDIA_NICE: int = int(os.environ.get("MEDIA_NICE", "10"))
MEDIA_IONICE_CLASS: int = int(os.environ.get("MEDIA_IONICE_CLASS", "2"))
MEDIA_IONICE_LEVEL: int = int(os.environ.get("MEDIA_IONICE_LEVEL", "7"))

IS_LINUX: bool = platform.system() == "Linux"


# ── Global semaphore (singleton) ──────────────────────────────────────────────

_semaphore: threading.Semaphore = threading.Semaphore(MAX_MEDIA_JOBS)
_async_semaphore: asyncio.Semaphore | None = None
_stats_lock = threading.Lock()


def _get_async_semaphore() -> asyncio.Semaphore:
    """Lazy-init asyncio semaphore (must be created inside event loop)."""
    global _async_semaphore
    if _async_semaphore is None:
        _async_semaphore = asyncio.Semaphore(MAX_MEDIA_JOBS)
    return _async_semaphore


# ── Job tracking ──────────────────────────────────────────────────────────────

class MediaJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


@dataclass
class MediaJobInfo:
    """Lightweight tracking for media subprocess jobs."""
    id: str
    tool: str  # "ffmpeg", "ffprobe", "demucs"
    description: str
    status: MediaJobStatus = MediaJobStatus.queued
    started_at: float = 0.0
    finished_at: float = 0.0
    pid: int = 0
    error: str = ""


_active_jobs: dict[str, MediaJobInfo] = {}
_job_counter: int = 0


def _next_job_id(tool: str) -> str:
    global _job_counter
    with _stats_lock:
        _job_counter += 1
        return f"media-{tool}-{_job_counter}"


def get_media_queue_status() -> dict[str, Any]:
    """Return current media executor status for API consumption."""
    with _stats_lock:
        jobs = list(_active_jobs.values())
    queued = sum(1 for j in jobs if j.status == MediaJobStatus.queued)
    running = sum(1 for j in jobs if j.status == MediaJobStatus.running)
    return {
        "max_concurrent": MAX_MEDIA_JOBS,
        "max_pending": MAX_PENDING_MEDIA_JOBS,
        "ffmpeg_threads": FFMPEG_THREADS,
        "nice": MEDIA_NICE,
        "queued": queued,
        "running": running,
        "total_tracked": len(jobs),
        "jobs": [
            {"id": j.id, "tool": j.tool, "description": j.description,
             "status": j.status.value, "pid": j.pid}
            for j in jobs if j.status in (MediaJobStatus.queued, MediaJobStatus.running)
        ],
    }


def check_media_capacity() -> tuple[bool, int, int]:
    """Check if the media queue can accept a new heavy job.

    Returns:
        (has_capacity, running_count, queued_count)
        has_capacity is False when queued + running >= MAX_PENDING_MEDIA_JOBS.
    """
    with _stats_lock:
        jobs = list(_active_jobs.values())
    queued = sum(1 for j in jobs if j.status == MediaJobStatus.queued)
    running = sum(1 for j in jobs if j.status == MediaJobStatus.running)
    has_capacity = (queued + running) < MAX_PENDING_MEDIA_JOBS
    return has_capacity, running, queued


# ── Nice / IONice prefix ─────────────────────────────────────────────────────

def _build_nice_prefix() -> list[str]:
    """Build nice + ionice command prefix for Linux, empty list otherwise."""
    if not IS_LINUX:
        return []
    prefix: list[str] = []
    if MEDIA_NICE > 0 and shutil.which("nice"):
        prefix.extend(["nice", "-n", str(MEDIA_NICE)])
    if shutil.which("ionice"):
        prefix.extend(["ionice", "-c", str(MEDIA_IONICE_CLASS), "-n", str(MEDIA_IONICE_LEVEL)])
    return prefix


# ── ffmpeg thread flags ──────────────────────────────────────────────────────

def inject_ffmpeg_thread_flags(cmd: list[str]) -> list[str]:
    """Insert -threads flag into an ffmpeg command if not already present.

    Inserts right after 'ffmpeg' (position 1) so it applies globally.
    Also adds -filter_threads and -filter_complex_threads where applicable.
    """
    if not cmd or cmd[0] not in ("ffmpeg", "ffprobe"):
        return cmd

    cmd = list(cmd)  # copy

    # Skip if user already specified -threads
    if "-threads" in cmd:
        return cmd

    t = str(FFMPEG_THREADS)
    insert_pos = 1  # after "ffmpeg"

    # For ffmpeg (not ffprobe), add thread limits
    if cmd[0] == "ffmpeg":
        cmd.insert(insert_pos, t)
        cmd.insert(insert_pos, "-threads")
        # Also limit filter threads if filter_complex is used
        if "-filter_complex" in cmd:
            cmd.insert(insert_pos + 2, t)
            cmd.insert(insert_pos + 2, "-filter_complex_threads")

    return cmd


# ── Core subprocess runner ────────────────────────────────────────────────────

def run_media_subprocess(
    cmd: list[str],
    *,
    description: str = "",
    tool: str = "ffmpeg",
    timeout: int | None = None,
    capture_output: bool = True,
    text: bool = True,
    env: dict[str, str] | None = None,
    heavy: bool = True,
    **subprocess_kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run a media subprocess with concurrency limiting, nice, and thread control.

    Args:
        cmd: Command to run (e.g. ["ffmpeg", "-y", ...])
        description: Human-readable description for logging
        tool: "ffmpeg", "ffprobe", or "demucs"
        timeout: Subprocess timeout in seconds
        capture_output: Capture stdout/stderr
        text: Decode output as text
        env: Custom environment dict
        heavy: If True, acquire global semaphore (use False for fast probes)
        **subprocess_kwargs: Passed through to subprocess.run

    Returns:
        subprocess.CompletedProcess

    Raises:
        subprocess.TimeoutExpired, RuntimeError, FileNotFoundError
    """
    # Inject thread flags for ffmpeg
    if tool in ("ffmpeg", "ffprobe") and cmd and cmd[0] in ("ffmpeg", "ffprobe"):
        cmd = inject_ffmpeg_thread_flags(cmd)

    # Build nice prefix
    nice_prefix = _build_nice_prefix() if heavy else []
    full_cmd = nice_prefix + cmd

    job_id = _next_job_id(tool)
    job_info = MediaJobInfo(id=job_id, tool=tool, description=description or " ".join(cmd[:4]))
    with _stats_lock:
        _active_jobs[job_id] = job_info

    desc = description or f"{tool} job"

    if heavy:
        debug(f"[media-exec] {desc} — waiting for semaphore (max {MAX_MEDIA_JOBS})")
        render_log(f"Queued: {desc} (max_concurrent={MAX_MEDIA_JOBS})")

    acquired = False
    try:
        if heavy:
            _semaphore.acquire()
            acquired = True

        job_info.status = MediaJobStatus.running
        job_info.started_at = time.monotonic()

        debug(f"[media-exec] {desc} — running (pid will follow)")
        render_log(f"Running: {desc}")

        result = subprocess.run(
            full_cmd,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            env=env,
            **subprocess_kwargs,
        )

        job_info.finished_at = time.monotonic()
        elapsed = job_info.finished_at - job_info.started_at

        if result.returncode == 0:
            job_info.status = MediaJobStatus.done
            debug(f"[media-exec] {desc} — done ({elapsed:.1f}s)")
            render_log(f"Done: {desc} ({elapsed:.1f}s)")
        else:
            job_info.status = MediaJobStatus.failed
            job_info.error = (result.stderr or "")[-500:]
            render_log(f"Failed: {desc} (exit={result.returncode}, {elapsed:.1f}s)", level="error")

        return result

    except subprocess.TimeoutExpired:
        job_info.status = MediaJobStatus.failed
        job_info.error = f"Timeout after {timeout}s"
        render_log(f"Timeout: {desc} ({timeout}s)", level="error")
        raise
    except Exception as e:
        job_info.status = MediaJobStatus.failed
        job_info.error = str(e)
        render_log(f"Error: {desc}: {e}", level="error")
        raise
    finally:
        if acquired:
            _semaphore.release()
        # Clean up old finished jobs (keep last 50)
        _cleanup_finished_jobs()


def run_media_popen(
    cmd: list[str],
    *,
    description: str = "",
    tool: str = "ffmpeg",
    heavy: bool = True,
    env: dict[str, str] | None = None,
    **popen_kwargs: Any,
) -> tuple[subprocess.Popen, str, bool]:
    """Start a media subprocess via Popen with concurrency limiting.

    The caller is responsible for:
    1. Reading stdout/stderr
    2. Calling release_media_popen(job_id) when done

    Returns:
        (Popen process, job_id, semaphore_acquired)
    """
    if tool in ("ffmpeg", "ffprobe") and cmd and cmd[0] in ("ffmpeg", "ffprobe"):
        cmd = inject_ffmpeg_thread_flags(cmd)

    nice_prefix = _build_nice_prefix() if heavy else []
    full_cmd = nice_prefix + cmd

    job_id = _next_job_id(tool)
    job_info = MediaJobInfo(id=job_id, tool=tool, description=description or " ".join(cmd[:4]))
    with _stats_lock:
        _active_jobs[job_id] = job_info

    acquired = False
    if heavy:
        desc = description or f"{tool} popen"
        debug(f"[media-exec] {desc} — waiting for semaphore")
        render_log(f"Queued (popen): {desc}")
        _semaphore.acquire()
        acquired = True

    job_info.status = MediaJobStatus.running
    job_info.started_at = time.monotonic()

    proc = subprocess.Popen(full_cmd, env=env, **popen_kwargs)
    job_info.pid = proc.pid
    debug(f"[media-exec] {description} — started (pid={proc.pid})")
    render_log(f"Running (popen): {description} (pid={proc.pid})")

    return proc, job_id, acquired


def release_media_popen(job_id: str, acquired: bool, returncode: int = 0, error_msg: str = "") -> None:
    """Release semaphore and update job tracking after Popen completes."""
    with _stats_lock:
        job = _active_jobs.get(job_id)
        if job:
            job.finished_at = time.monotonic()
            elapsed = job.finished_at - job.started_at
            if returncode == 0:
                job.status = MediaJobStatus.done
                render_log(f"Done (popen): {job.description} ({elapsed:.1f}s)")
            else:
                job.status = MediaJobStatus.failed
                job.error = error_msg[:500]
                render_log(f"Failed (popen): {job.description} (exit={returncode}, {elapsed:.1f}s)",
                           level="error")
    if acquired:
        _semaphore.release()
    _cleanup_finished_jobs()


def _cleanup_finished_jobs(max_keep: int = 50) -> None:
    """Remove old finished jobs from tracking dict."""
    with _stats_lock:
        finished = [
            (jid, j) for jid, j in _active_jobs.items()
            if j.status in (MediaJobStatus.done, MediaJobStatus.failed)
        ]
        if len(finished) > max_keep:
            # Remove oldest
            finished.sort(key=lambda x: x[1].finished_at)
            for jid, _ in finished[:-max_keep]:
                del _active_jobs[jid]
