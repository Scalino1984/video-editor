"""Luma Dream Machine generation provider — video and image generation."""

from __future__ import annotations

import os

from src.utils.logging import info, warn, error, debug
from src.video.generation.base import (
    GenerationProvider, GenRequest, GenStatus, GenType,
)

# Luma model constants
VIDEO_MODELS = ("ray-2", "ray-flash-2")
IMAGE_MODELS = ("photon-1", "photon-flash-1")

DEFAULT_VIDEO_MODEL = "ray-2"
DEFAULT_IMAGE_MODEL = "photon-1"

# Valid parameter values
ASPECT_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21")
VIDEO_DURATIONS = ("5s", "9s")
VIDEO_RESOLUTIONS = ("540p", "720p", "1080p", "4k")
IMAGE_FORMATS = ("jpg", "png")


def _get_api_key() -> str:
    """Get Luma API key from environment."""
    return os.environ.get("LUMA_API_KEY", "")


class LumaProvider(GenerationProvider):
    """Luma Dream Machine provider — ray-2 (video) + photon-1 (image)."""

    name = "luma"

    async def check_available(self) -> tuple[bool, str]:
        key = _get_api_key()
        if not key:
            return False, "LUMA_API_KEY nicht gesetzt"
        try:
            from lumaai import AsyncLumaAI  # noqa: F401
            return True, "Luma Dream Machine verfügbar"
        except ImportError:
            return False, "lumaai Paket nicht installiert (pip install lumaai)"

    async def generate_video(self, request: GenRequest) -> tuple[str, str]:
        key = _get_api_key()
        if not key:
            raise RuntimeError("LUMA_API_KEY nicht gesetzt")

        try:
            from lumaai import AsyncLumaAI
        except ImportError:
            raise RuntimeError("lumaai Paket nicht installiert (pip install lumaai)")

        model = request.model if request.model in VIDEO_MODELS else DEFAULT_VIDEO_MODEL
        aspect = request.aspect_ratio if request.aspect_ratio in ASPECT_RATIOS else "16:9"
        duration = request.duration if request.duration in VIDEO_DURATIONS else "5s"
        resolution = request.resolution if request.resolution in VIDEO_RESOLUTIONS else "1080p"

        # Build keyframes for image-to-video
        keyframes: dict | None = None
        if request.keyframe_image_url:
            keyframes = {}
            keyframes["frame0"] = {"type": "image", "url": request.keyframe_image_url}
            if request.keyframe_end_url:
                keyframes["frame1"] = {"type": "image", "url": request.keyframe_end_url}

        client = AsyncLumaAI(auth_token=key)
        try:
            gen = await client.generations.video.create(
                model=model,
                prompt=request.prompt,
                aspect_ratio=aspect,
                duration=duration,
                loop=request.loop,
                resolution=resolution,
                keyframes=keyframes,
            )
            info(f"[luma] Video generation submitted: {gen.id} model={model}")
            return gen.id, model
        except Exception as e:
            error(f"[luma] Video generation failed: {e}")
            raise

    async def generate_image(self, request: GenRequest) -> tuple[str, str]:
        key = _get_api_key()
        if not key:
            raise RuntimeError("LUMA_API_KEY nicht gesetzt")

        try:
            from lumaai import AsyncLumaAI
        except ImportError:
            raise RuntimeError("lumaai Paket nicht installiert (pip install lumaai)")

        model = request.model if request.model in IMAGE_MODELS else DEFAULT_IMAGE_MODEL
        aspect = request.aspect_ratio if request.aspect_ratio in ASPECT_RATIOS else "16:9"
        img_format = request.image_format if request.image_format in IMAGE_FORMATS else "jpg"

        # Build optional reference params
        kwargs: dict = {}
        if request.style_ref_url:
            kwargs["style_ref"] = [{"url": request.style_ref_url, "weight": 0.85}]
        if request.modify_image_url:
            kwargs["modify_image_ref"] = {"url": request.modify_image_url, "weight": 0.85}

        client = AsyncLumaAI(auth_token=key)
        try:
            gen = await client.generations.image.create(
                model=model,
                prompt=request.prompt,
                aspect_ratio=aspect,
                format=img_format,
                **kwargs,
            )
            info(f"[luma] Image generation submitted: {gen.id} model={model}")
            return gen.id, model
        except Exception as e:
            error(f"[luma] Image generation failed: {e}")
            raise

    async def poll_status(self, provider_id: str) -> tuple[GenStatus, float, str, str]:
        key = _get_api_key()
        if not key:
            return GenStatus.failed, 0.0, "", "LUMA_API_KEY nicht gesetzt"

        try:
            from lumaai import AsyncLumaAI
        except ImportError:
            return GenStatus.failed, 0.0, "", "lumaai Paket nicht installiert"

        client = AsyncLumaAI(auth_token=key)
        try:
            gen = await client.generations.get(provider_id)
        except Exception as e:
            return GenStatus.failed, 0.0, "", str(e)

        state = getattr(gen, "state", "unknown")
        assets = getattr(gen, "assets", None)
        failure = getattr(gen, "failure_reason", "") or ""

        if state == "completed":
            url = ""
            if assets:
                url = getattr(assets, "video", "") or getattr(assets, "image", "") or ""
            return GenStatus.completed, 1.0, url, ""

        if state == "failed":
            return GenStatus.failed, 0.0, "", failure or "Generation fehlgeschlagen"

        # queued or dreaming → processing
        progress = 0.1 if state == "queued" else 0.5
        return GenStatus.processing, progress, "", ""

    async def cancel(self, provider_id: str) -> bool:
        key = _get_api_key()
        if not key:
            return False

        try:
            from lumaai import AsyncLumaAI
        except ImportError:
            return False
        client = AsyncLumaAI(auth_token=key)
        try:
            await client.generations.delete(provider_id)
            info(f"[luma] Generation {provider_id} cancelled")
            return True
        except Exception as e:
            warn(f"[luma] Cancel failed for {provider_id}: {e}")
            return False
