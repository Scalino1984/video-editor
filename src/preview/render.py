"""Preview render: generate short MP4 clips with ASS subtitles burned in."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.utils.logging import info, warn, error, debug
from src.utils.media_executor import run_media_subprocess


def parse_time_str(time_str: str) -> float:
    """Parse time strings like '15s', '1m30s', '60' to seconds."""
    import re
    m = re.match(r"(?:(\d+)m)?(\d+(?:\.\d+)?)s?$", time_str)
    if m:
        minutes = int(m.group(1) or 0)
        seconds = float(m.group(2))
        return minutes * 60 + seconds
    try:
        return float(time_str)
    except ValueError:
        return 15.0


def check_preview_deps() -> tuple[bool, str]:
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg not found. Install: sudo apt-get install ffmpeg"
    return True, "OK"


def render_preview(
    ass_path: Path,
    output_path: Path | None = None,
    audio_path: Path | None = None,
    duration: str = "15s",
    start: str = "0s",
    resolution: str = "1920x1080",
    background: str = "#000000",
    bg_image: Path | None = None,
) -> Path | None:
    ok, msg = check_preview_deps()
    if not ok:
        error(msg)
        warn("Preview render requires ffmpeg with libass support.")
        warn("Install on Debian/Ubuntu: sudo apt-get install ffmpeg")
        warn("Install on macOS: brew install ffmpeg")
        return None

    dur_sec = parse_time_str(duration)
    start_sec = parse_time_str(start)
    w, h = resolution.split("x")

    if output_path is None:
        output_path = ass_path.with_suffix(".preview.mp4")

    # build input: either background image or solid color
    if bg_image and bg_image.exists():
        input_args = ["-loop", "1", "-i", str(bg_image)]
    else:
        bg = background.lstrip("#")
        input_args = [
            "-f", "lavfi",
            "-i", f"color=c=0x{bg}:s={w}x{h}:d={dur_sec}:r=30",
        ]

    # subtitle filter
    ass_escaped = str(ass_path).replace(":", "\\:").replace("'", "\\'")
    vf = f"ass='{ass_escaped}'"

    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-ss", str(start_sec),
        "-t", str(dur_sec),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p",
    ]

    # mux audio if available
    if audio_path and audio_path.exists():
        cmd.extend(["-i", str(audio_path), "-ss", str(start_sec), "-t", str(dur_sec)])
        cmd.extend(["-c:a", "aac", "-shortest"])

    cmd.append(str(output_path))

    info(f"Rendering preview: {output_path.name}")
    debug(f"CMD: {' '.join(cmd)}")

    try:
        r = run_media_subprocess(
            cmd, tool="ffmpeg", description=f"preview {output_path.name}",
            timeout=120, heavy=True,
        )
        if r.returncode != 0:
            error(f"ffmpeg preview render failed:\n{r.stderr}")
            return None
    except subprocess.TimeoutExpired:
        error("Preview render timed out")
        return None

    if output_path.exists():
        info(f"Preview saved: {output_path}")
        return output_path

    error("Preview file was not created")
    return None
