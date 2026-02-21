"""Dependency self-check with helpful installation hints.

IMPORTANT: Never import heavy ML libraries (torch, whisperx, demucs, essentia)
at check time — use importlib.util.find_spec() instead.  Importing torch alone
pulls ~500 MB into resident memory.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass

from src.utils.logging import info, warn, error


@dataclass
class DepStatus:
    name: str
    available: bool
    version: str = ""
    hint: str = ""


def check_ffmpeg() -> DepStatus:
    path = shutil.which("ffmpeg")
    if not path:
        return DepStatus(
            "ffmpeg", False,
            hint="Install: sudo apt-get install ffmpeg  (or https://ffmpeg.org/download.html)"
        )
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        ver = r.stdout.split("\n")[0] if r.stdout else "unknown"
        return DepStatus("ffmpeg", True, version=ver)
    except Exception:
        return DepStatus("ffmpeg", False, hint="ffmpeg found but failed to run")


def check_ffprobe() -> DepStatus:
    path = shutil.which("ffprobe")
    if not path:
        return DepStatus("ffprobe", False, hint="Usually bundled with ffmpeg")
    return DepStatus("ffprobe", True)


def check_demucs() -> DepStatus:
    if importlib.util.find_spec("demucs") is not None:
        return DepStatus("demucs", True)
    return DepStatus(
        "demucs", False,
        hint="Install: pip install demucs  (requires PyTorch)"
    )


def check_openai_key() -> DepStatus:
    import os
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return DepStatus("OPENAI_API_KEY", True, version=f"...{key[-4:]}")
    return DepStatus(
        "OPENAI_API_KEY", False,
        hint="Set via: export OPENAI_API_KEY=sk-... or in .env file"
    )


def check_mistral_key() -> DepStatus:
    import os
    key = os.environ.get("MISTRAL_API_KEY", "")
    if not key:
        return DepStatus(
            "MISTRAL_API_KEY", False,
            hint="Set via: export MISTRAL_API_KEY=... or in .env file"
        )
    try:
        import mistralai  # noqa: F401
    except ImportError:
        return DepStatus(
            "mistralai", False,
            hint="Install: pip install mistralai"
        )
    return DepStatus("MISTRAL_API_KEY + mistralai", True, version=f"...{key[-4:]}")


def check_webrtcvad() -> DepStatus:
    if importlib.util.find_spec("webrtcvad") is not None:
        return DepStatus("webrtcvad", True)
    return DepStatus(
        "webrtcvad", False,
        hint="Install: pip install webrtcvad"
    )


def check_whisperx() -> DepStatus:
    if importlib.util.find_spec("whisperx") is not None:
        return DepStatus("whisperx", True)
    return DepStatus(
        "whisperx", False,
        hint="Install: pip install whisperx  (requires torch, torchaudio)"
    )


def check_faster_whisper() -> DepStatus:
    if importlib.util.find_spec("faster_whisper") is not None:
        return DepStatus("faster-whisper", True)
    return DepStatus(
        "faster-whisper", False,
        hint="Install: pip install faster-whisper"
    )


def check_all(backend: str = "voxtral", vocal_isolation: bool = False) -> list[DepStatus]:
    results = [check_ffmpeg(), check_ffprobe(), check_webrtcvad()]
    if backend == "voxtral":
        results.append(check_mistral_key())
    elif backend == "openai_whisper":
        results.append(check_openai_key())
    elif backend == "whisperx":
        results.append(check_whisperx())
    elif backend == "local_whisper":
        results.append(check_faster_whisper())
    if vocal_isolation:
        results.append(check_demucs())
    return results


def check_all_backends() -> dict[str, bool]:
    """Quick check which backends are available."""
    backends = {
        "voxtral": check_mistral_key().available,
        "openai_whisper": check_openai_key().available,
        "local_whisper": check_faster_whisper().available,
        "whisperx": check_whisperx().available,
    }
    return backends


def check_essentia() -> DepStatus:
    if importlib.util.find_spec("essentia") is not None:
        return DepStatus("essentia", True, hint="pip install essentia")
    return DepStatus("essentia", False, hint="pip install essentia (BPM detection)")


def check_pydantic_ai() -> DepStatus:
    if importlib.util.find_spec("pydantic_ai") is not None:
        return DepStatus("pydantic-ai", True, hint="pip install pydantic-ai")
    return DepStatus("pydantic-ai", False, hint="pip install pydantic-ai (AI Chat)")


def print_dep_status(deps: list[DepStatus], strict: bool = False) -> bool:
    all_ok = True
    for d in deps:
        if d.available:
            info(f"[green]✓[/green] {d.name}: {d.version or 'OK'}")
        else:
            if strict:
                error(f"{d.name}: NOT FOUND — {d.hint}")
                all_ok = False
            else:
                warn(f"{d.name}: not found — {d.hint}")
    return all_ok
