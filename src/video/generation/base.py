"""Generation provider ABC and shared data models."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class GenType(str, Enum):
    """Generation type."""
    video = "video"
    image = "image"


class GenStatus(str, Enum):
    """Generation job status."""
    pending = "pending"
    processing = "processing"
    downloading = "downloading"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class GenRequest:
    """Client-facing generation request."""
    gen_type: GenType
    prompt: str
    project_id: str = ""
    model: str = ""                # empty = provider default
    aspect_ratio: str = "16:9"
    # Video-only
    duration: str = "5s"           # "5s" | "9s"
    loop: bool = False
    resolution: str = "1080p"      # 540p | 720p | 1080p | 4k
    keyframe_image_url: str = ""   # image-to-video start frame
    keyframe_end_url: str = ""     # image-to-video end frame
    # Image-only
    image_format: str = "jpg"      # jpg | png
    style_ref_url: str = ""        # style reference image
    modify_image_url: str = ""     # image to modify

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gen_type"] = self.gen_type.value
        return d


@dataclass
class GenJob:
    """Internal generation job state."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    provider: str = ""
    provider_id: str = ""          # provider-side generation ID
    gen_type: GenType = GenType.video
    prompt: str = ""
    status: GenStatus = GenStatus.pending
    progress: float = 0.0          # 0.0–1.0
    result_url: str = ""           # remote asset URL
    local_path: str = ""           # downloaded local file
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str = ""
    project_id: str = ""
    asset_id: str = ""             # editor asset ID after import
    model: str = ""
    aspect_ratio: str = "16:9"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gen_type"] = self.gen_type.value
        d["status"] = self.status.value
        return d

    @staticmethod
    def from_dict(d: dict) -> GenJob:
        d = dict(d)
        d["gen_type"] = GenType(d.get("gen_type", "video"))
        d["status"] = GenStatus(d.get("status", "pending"))
        return GenJob(**d)


class GenerationProvider(ABC):
    """Abstract base class for AI generation providers."""

    name: str = "base"

    @abstractmethod
    async def check_available(self) -> tuple[bool, str]:
        """Check if provider is available. Returns (ok, message)."""

    @abstractmethod
    async def generate_video(self, request: GenRequest) -> tuple[str, str]:
        """Submit video generation request.

        Returns (provider_job_id, model_used).
        Raises on error.
        """

    @abstractmethod
    async def generate_image(self, request: GenRequest) -> tuple[str, str]:
        """Submit image generation request.

        Returns (provider_job_id, model_used).
        Raises on error.
        """

    @abstractmethod
    async def poll_status(self, provider_id: str) -> tuple[GenStatus, float, str, str]:
        """Poll generation status.

        Returns (status, progress, result_url, error_message).
        """

    @abstractmethod
    async def cancel(self, provider_id: str) -> bool:
        """Cancel / delete a running generation. Returns True on success."""

    async def download(self, url: str, dest: Path) -> Path:
        """Download result asset to local file. Default implementation uses httpx."""
        import httpx
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.get(url, follow_redirects=True)
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
        return dest
