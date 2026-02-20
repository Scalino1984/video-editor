"""Overlay Asset Library — discover, probe, and serve overlay video files.

Overlays are MP4/MOV files stored in a configurable directory (OVERLAY_DIR).
They can be browsed via API and imported into editor projects as timeline items.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, debug

# ── Configuration ─────────────────────────────────────────────────────────────

OVERLAY_DIR = Path(os.environ.get("OVERLAY_DIR", "data/editor/overlays"))
OVERLAY_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_OVERLAY_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov"})
MAX_OVERLAYS_PER_PROJECT: int = int(os.environ.get("MAX_OVERLAYS_PER_PROJECT", "8"))

VALID_BLEND_MODES: frozenset[str] = frozenset({
    "normal", "screen", "addition", "multiply",
})

# ── Overlay Asset model ───────────────────────────────────────────────────────


@dataclass
class OverlayAsset:
    """Metadata for a single overlay video file."""
    id: str
    name: str           # filename without extension
    filename: str       # full filename
    relative_path: str  # path relative to OVERLAY_DIR
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 30.0
    pix_fmt: str = ""
    has_alpha: bool = False
    file_size: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["preview_url"] = f"/api/overlays/{self.id}/file"
        return d


# ── Cache ─────────────────────────────────────────────────────────────────────

_cache: dict[str, OverlayAsset] = {}
_cache_lock = threading.Lock()
_cache_mtime: dict[str, float] = {}  # id → file mtime at probe time


def _generate_id(relative_path: str) -> str:
    """Generate a stable ID from the relative path (deterministic across reboots)."""
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def _has_alpha_channel(pix_fmt: str) -> bool:
    """Detect if a pixel format has an alpha channel."""
    alpha_fmts = {"rgba", "yuva420p", "yuva422p", "yuva444p", "argb", "abgr", "bgra", "gbrap", "ya8", "pal8"}
    return pix_fmt.lower() in alpha_fmts


def _probe_overlay(file_path: Path) -> OverlayAsset:
    """Probe an overlay file with ffprobe for metadata."""
    from src.video.render import probe_media

    relative = str(file_path.relative_to(OVERLAY_DIR.resolve()))
    oid = _generate_id(relative)
    probe = probe_media(file_path)

    # Get pix_fmt via ffprobe (not available in ProbeResult)
    pix_fmt = ""
    try:
        from src.utils.media_executor import run_media_subprocess
        r = run_media_subprocess(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt", "-of", "csv=p=0",
             str(file_path)],
            tool="ffprobe", description=f"overlay pix_fmt {file_path.name}",
            timeout=15, heavy=False,
        )
        pix_fmt = r.stdout.strip()
    except Exception:
        pass

    stat = file_path.stat()
    return OverlayAsset(
        id=oid,
        name=file_path.stem,
        filename=file_path.name,
        relative_path=relative,
        duration_sec=probe.duration,
        width=probe.width,
        height=probe.height,
        fps=probe.fps,
        pix_fmt=pix_fmt,
        has_alpha=_has_alpha_channel(pix_fmt),
        file_size=stat.st_size,
    )


def _is_cache_valid(oid: str, file_path: Path) -> bool:
    """Check if cached entry is still valid (file unchanged)."""
    if oid not in _cache or oid not in _cache_mtime:
        return False
    try:
        return file_path.stat().st_mtime == _cache_mtime[oid]
    except OSError:
        return False


# ── Public API ────────────────────────────────────────────────────────────────


def scan_overlays() -> list[OverlayAsset]:
    """Scan OVERLAY_DIR for overlay files and return metadata list."""
    overlay_root = OVERLAY_DIR.resolve()
    if not overlay_root.is_dir():
        return []

    results: list[OverlayAsset] = []
    for f in sorted(overlay_root.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() not in ALLOWED_OVERLAY_EXTENSIONS:
            continue
        # Security: ensure file is within OVERLAY_DIR
        if not f.resolve().is_relative_to(overlay_root):
            continue

        relative = str(f.relative_to(overlay_root))
        oid = _generate_id(relative)

        with _cache_lock:
            if _is_cache_valid(oid, f):
                results.append(_cache[oid])
                continue

        # Probe (outside lock)
        try:
            asset = _probe_overlay(f)
            with _cache_lock:
                _cache[oid] = asset
                _cache_mtime[oid] = f.stat().st_mtime
            results.append(asset)
        except Exception as e:
            warn(f"[overlay] Failed to probe {f.name}: {e}")

    return results


def get_overlay(overlay_id: str) -> OverlayAsset | None:
    """Get a single overlay by ID. Returns None if not found."""
    with _cache_lock:
        if overlay_id in _cache:
            return _cache[overlay_id]

    # Cache miss — scan and retry
    scan_overlays()
    with _cache_lock:
        return _cache.get(overlay_id)


def get_overlay_path(overlay_id: str) -> Path | None:
    """Get the resolved file path for an overlay, with security validation."""
    asset = get_overlay(overlay_id)
    if not asset:
        return None

    overlay_root = OVERLAY_DIR.resolve()
    file_path = (overlay_root / asset.relative_path).resolve()

    # Security: verify path is within OVERLAY_DIR
    if not file_path.is_relative_to(overlay_root):
        warn(f"[overlay] Path traversal attempt: {asset.relative_path}")
        return None

    if not file_path.exists():
        return None

    return file_path


def validate_blend_mode(mode: str) -> bool:
    """Check if a blend mode is in the whitelist."""
    return mode in VALID_BLEND_MODES


def clear_cache() -> None:
    """Clear the overlay cache (for testing)."""
    with _cache_lock:
        _cache.clear()
        _cache_mtime.clear()
