"""Karaoke Video Renderer — ffmpeg-based full video rendering.

Supports:
- Background: image (jpg/png/webp) or video (mp4/mov/webm), auto-looped
- Subtitles: .ass (native libass) or .srt (auto-converted)
- Audio: any ffmpeg-supported format as soundtrack
- Presets: youtube, mobile, draft, custom
- Position: top, middle, bottom subtitle placement
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, error, debug
from src.utils.media_executor import run_media_subprocess


# ── Probe helpers ─────────────────────────────────────────────────────────────

@dataclass
class ProbeResult:
    width: int = 0
    height: int = 0
    duration: float = 0
    fps: float = 30
    has_audio: bool = False
    codec: str = ""
    is_image: bool = False

    @property
    def is_portrait(self) -> bool:
        return self.height > self.width

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


def probe_media(path: Path) -> ProbeResult:
    """Probe media file with ffprobe — works for images, video, audio."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        r = run_media_subprocess(
            cmd, tool="ffprobe", description=f"probe {path.name}",
            timeout=30, heavy=False,
        )
        data = json.loads(r.stdout)
    except Exception as e:
        error(f"ffprobe failed: {e}")
        return ProbeResult()

    result = ProbeResult()
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    for s in streams:
        if s.get("codec_type") == "video":
            result.width = int(s.get("width", 0))
            result.height = int(s.get("height", 0))
            result.codec = s.get("codec_name", "")
            # Duration from stream or format
            dur = s.get("duration") or fmt.get("duration", "0")
            result.duration = float(dur)
            # FPS
            r_fps = s.get("r_frame_rate", "30/1")
            try:
                num, den = r_fps.split("/")
                result.fps = round(float(num) / float(den), 2)
            except (ValueError, ZeroDivisionError):
                result.fps = 30
            # Detect if it's a still image (very short or image codec)
            if result.codec in ("png", "mjpeg", "bmp", "webp", "tiff"):
                result.is_image = True
            elif result.duration < 0.1:
                result.is_image = True
        elif s.get("codec_type") == "audio":
            result.has_audio = True

    # Fallback duration from format
    if result.duration <= 0:
        result.duration = float(fmt.get("duration", 0))

    return result


def get_audio_duration(path: Path) -> float:
    """Get duration of an audio file."""
    p = probe_media(path)
    return p.duration


# ── Presets ───────────────────────────────────────────────────────────────────

RENDER_PRESETS = {
    "youtube": {
        "crf": 18,
        "x264_preset": "medium",
        "audio_bitrate": "192k",
        "fps": 30,
        "max_width": 1920,
        "max_height": 1080,
    },
    "mobile": {
        "crf": 23,
        "x264_preset": "fast",
        "audio_bitrate": "128k",
        "fps": 30,
        "max_width": 720,
        "max_height": 1280,
    },
    "draft": {
        "crf": 28,
        "x264_preset": "ultrafast",
        "audio_bitrate": "96k",
        "fps": 24,
        "max_width": 1280,
        "max_height": 720,
    },
    "custom": {
        "crf": 20,
        "x264_preset": "medium",
        "audio_bitrate": "192k",
        "fps": 30,
        "max_width": 0,  # no limit
        "max_height": 0,
    },
}


# ── SRT → ASS conversion ─────────────────────────────────────────────────────

def srt_to_ass(srt_path: Path, output_path: Path | None = None,
               position: str = "bottom", font_size: int = 48) -> Path:
    """Convert SRT to ASS using ffmpeg for reliable subtitle handling."""
    out = output_path or srt_path.with_suffix(".ass")
    cmd = [
        "ffmpeg", "-y", "-i", str(srt_path),
        str(out),
    ]
    r = run_media_subprocess(
        cmd, tool="ffmpeg", description=f"SRT→ASS {srt_path.name}",
        timeout=30, heavy=False,
    )
    if r.returncode != 0 or not out.exists():
        # Fallback: manual minimal ASS
        _manual_srt_to_ass(srt_path, out, position, font_size)
    return out


def _manual_srt_to_ass(srt_path: Path, out_path: Path,
                       position: str = "bottom", font_size: int = 48) -> None:
    """Manual SRT→ASS conversion as fallback."""
    alignment = {"top": 8, "middle": 5, "bottom": 2}.get(position, 2)
    margin_v = {"top": 30, "middle": 0, "bottom": 40}.get(position, 40)

    header = f"""[Script Info]
Title: Karaoke Video
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,{alignment},20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = srt_path.read_text(encoding="utf-8").strip().split("\n\n")
    events = []
    import re
    for block in lines:
        parts = block.strip().split("\n")
        if len(parts) < 3:
            continue
        time_match = re.match(
            r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})",
            parts[1]
        )
        if not time_match:
            continue
        g = time_match.groups()
        start = f"{g[0]}:{g[1]}:{g[2]}.{g[3][:2]}"
        end = f"{g[4]}:{g[5]}:{g[6]}.{g[7][:2]}"
        text = "\\N".join(parts[2:])
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def _scale_filter(w: int, h: int, fit: str = "cover") -> list[str]:
    """Return ffmpeg scale/pad/crop filter parts for a target resolution.

    fit modes:
      contain — scale down, pad with black bars (letterbox/pillarbox)
      cover   — scale up, crop to fill (no bars)
      stretch — force exact dimensions (distorts aspect ratio)
    """
    if fit == "stretch":
        return [f"scale={w}:{h}"]
    elif fit == "cover":
        return [
            f"scale={w}:{h}:force_original_aspect_ratio=increase",
            f"crop={w}:{h}",
        ]
    else:  # contain (default safe fallback)
        return [
            f"scale={w}:{h}:force_original_aspect_ratio=decrease",
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
        ]


# ── Main render function ─────────────────────────────────────────────────────

@dataclass
class RenderOptions:
    """Video render configuration."""
    preset: str = "youtube"
    position: str = "bottom"           # top | middle | bottom
    crf: int | None = None             # override preset
    x264_preset: str | None = None     # override preset
    audio_bitrate: str | None = None   # override preset
    fps: int | None = None             # override preset
    target_resolution: str | None = None  # e.g. "1920x1080", None=auto
    duration: float | None = None      # force duration (seconds)
    font_size: int = 48
    safe_area: bool = False
    video_fit: str = "cover"  # cover | contain | stretch


def render_video(
    subtitle_path: Path,
    background_path: Path,
    output_path: Path,
    audio_path: Path | None = None,
    options: RenderOptions | None = None,
    progress_callback: Any = None,
) -> Path | None:
    """Render a full karaoke video.

    Args:
        subtitle_path: .srt or .ass file
        background_path: image or video file
        output_path: output .mp4 path
        audio_path: optional audio track
        options: render configuration
        progress_callback: callable(stage: str, progress: float)
    """
    if not shutil.which("ffmpeg"):
        error("ffmpeg not found")
        return None

    opts = options or RenderOptions()
    preset = RENDER_PRESETS.get(opts.preset, RENDER_PRESETS["youtube"])

    # Resolve overrides
    crf = opts.crf or preset["crf"]
    x264_preset = opts.x264_preset or preset["x264_preset"]
    audio_br = opts.audio_bitrate or preset["audio_bitrate"]
    fps = opts.fps or preset["fps"]

    def _progress(stage: str, pct: float):
        if progress_callback:
            progress_callback(stage, pct)
        info(f"[render] {stage} ({pct:.0%})")

    _progress("Probing background", 0.05)

    # ── Step 1: Probe background ──────────────────────────────────────────
    bg_probe = probe_media(background_path)
    info(f"Background: {bg_probe.resolution} {'image' if bg_probe.is_image else 'video'} "
         f"duration={bg_probe.duration:.1f}s fps={bg_probe.fps}")

    # ── Step 2: Determine target duration ─────────────────────────────────
    target_duration = opts.duration
    if not target_duration and audio_path and audio_path.exists():
        target_duration = get_audio_duration(audio_path)
        info(f"Target duration from audio: {target_duration:.1f}s")
    if not target_duration and not bg_probe.is_image:
        target_duration = bg_probe.duration
    if not target_duration:
        error("Cannot determine duration — provide audio or --duration")
        return None

    _progress("Determining target", 0.10)

    # ── Step 3: Determine target resolution ───────────────────────────────
    if opts.target_resolution:
        tw, th = opts.target_resolution.split("x")
        target_w, target_h = int(tw), int(th)
    elif bg_probe.width > 0:
        target_w, target_h = bg_probe.width, bg_probe.height
        # Clamp to preset max
        max_w, max_h = preset["max_width"], preset["max_height"]
        if max_w > 0 and target_w > max_w:
            scale = max_w / target_w
            target_w, target_h = max_w, int(target_h * scale)
        if max_h > 0 and target_h > max_h:
            scale = max_h / target_h
            target_w, target_h = int(target_w * scale), max_h
    else:
        target_w, target_h = 1920, 1080

    # Ensure even dimensions (H.264 requires)
    target_w = target_w + (target_w % 2)
    target_h = target_h + (target_h % 2)
    info(f"Target: {target_w}x{target_h} @ {fps}fps, duration={target_duration:.1f}s")

    _progress("Preparing background", 0.15)

    # ── Step 4: Prepare subtitle file ─────────────────────────────────────
    with tempfile.TemporaryDirectory(prefix="render_") as tmp:
        tmp_dir = Path(tmp)

        # Ensure ASS format for libass rendering
        if subtitle_path.suffix.lower() == ".srt":
            _progress("Converting SRT to ASS", 0.20)
            ass_path = tmp_dir / "subtitles.ass"
            srt_to_ass(subtitle_path, ass_path, opts.position, opts.font_size)
        elif subtitle_path.suffix.lower() == ".ass":
            ass_path = subtitle_path
        else:
            error(f"Unsupported subtitle format: {subtitle_path.suffix}")
            return None

        _progress("Building ffmpeg command", 0.25)

        # ── Step 5: Build ffmpeg command ──────────────────────────────────
        ass_escaped = str(ass_path).replace(":", "\\:").replace("'", "\\'")
        vf_parts = []

        # Background input
        input_args = []
        if bg_probe.is_image:
            # Image → video: loop + scale
            input_args = ["-loop", "1", "-i", str(background_path)]
            vf_parts.extend(_scale_filter(target_w, target_h, opts.video_fit))
        else:
            # Video background
            if bg_probe.duration < target_duration:
                # Loop video to reach target duration
                loop_count = int(target_duration / bg_probe.duration) + 1
                input_args = [
                    "-stream_loop", str(loop_count),
                    "-i", str(background_path),
                ]
            else:
                input_args = ["-i", str(background_path)]
            # Scale to target if different
            if bg_probe.width != target_w or bg_probe.height != target_h:
                vf_parts.extend(_scale_filter(target_w, target_h, opts.video_fit))

        # Set FPS
        vf_parts.append(f"fps={fps}")

        # Burn in subtitles via libass
        vf_parts.append(f"ass='{ass_escaped}'")

        vf = ",".join(vf_parts)

        cmd = [
            "ffmpeg", "-y",
            *input_args,
            "-t", str(target_duration),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", x264_preset,
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
        ]

        # Audio muxing
        if audio_path and audio_path.exists():
            cmd.extend(["-i", str(audio_path)])
            cmd.extend([
                "-c:a", "aac",
                "-b:a", audio_br,
                "-t", str(target_duration),
                "-shortest",
            ])
            # Map: video from first input, audio from audio input
            cmd.extend(["-map", "0:v", "-map", "1:a"])
        elif not bg_probe.is_image and bg_probe.has_audio:
            # Use background video's audio
            cmd.extend(["-c:a", "aac", "-b:a", audio_br])
        else:
            cmd.extend(["-an"])  # No audio

        cmd.append(str(output_path))

        _progress("Rendering video", 0.30)
        info(f"Render CMD: ffmpeg ... -vf {vf} -c:v libx264 -crf {crf} → {output_path.name}")
        debug(f"Full CMD: {' '.join(cmd)}")

        try:
            r = run_media_subprocess(
                cmd, tool="ffmpeg", description=f"render video {output_path.name}",
                timeout=max(600, target_duration * 3), heavy=True,
            )
            if r.returncode != 0:
                error(f"ffmpeg render failed:\n{r.stderr[-2000:]}")
                return None
        except subprocess.TimeoutExpired:
            error("Video render timed out")
            return None

    _progress("Complete", 1.0)

    if output_path.exists():
        size_mb = output_path.stat().st_size / (1024 * 1024)
        info(f"Video rendered: {output_path} ({size_mb:.1f} MB)")
        return output_path

    error("Output video was not created")
    return None
