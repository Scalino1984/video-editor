"""Video Editor — Timeline state management, undo/redo, project model.

Manages a multi-track timeline with:
- Video track (clips, images, loops)
- Audio track (music, voiceover)
- Subtitle track (SRT/ASS burn-in)
- Effects (transitions, filters, speed, color)

All state is JSON-serializable for AI chat integration.
"""

from __future__ import annotations

import copy
import json
import subprocess
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, error, debug, render_log, set_job_id
from src.utils.media_executor import run_media_subprocess, run_media_popen, release_media_popen
from src.video.render import probe_media, ProbeResult

# ── Data directory ────────────────────────────────────────────────────────────

EDITOR_DIR = Path("data/editor")
EDITOR_DIR.mkdir(parents=True, exist_ok=True)
(EDITOR_DIR / "assets").mkdir(exist_ok=True)
(EDITOR_DIR / "projects").mkdir(exist_ok=True)
(EDITOR_DIR / "renders").mkdir(exist_ok=True)

MAX_UNDO = 80

# Valid track types
TRACK_TYPES = frozenset({"video", "audio", "subtitle"})


# ── Timeline data model ──────────────────────────────────────────────────────

@dataclass
class Asset:
    """Uploaded media asset."""
    id: str
    filename: str
    path: str
    type: str  # video | audio | image | subtitle
    duration: float = 0
    width: int = 0
    height: int = 0
    fps: float = 30
    has_audio: bool = False
    thumbnail: str = ""  # path to generated thumb

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Effect:
    """Applied effect on a clip."""
    type: str  # fade_in | fade_out | zoom | pan | speed | blur |
               # brightness | contrast | saturation | grayscale | sepia |
               # rotate | flip_h | flip_v | chromakey | overlay_text
    params: dict = field(default_factory=dict)
    # e.g. {"duration": 1.0} for fade, {"factor": 1.5} for speed
    #      {"brightness": 0.1, "contrast": 1.2} for color

    def to_dict(self) -> dict:
        return {"type": self.type, "params": self.params}


# ── Timeline v2: Track model ─────────────────────────────────────────────────

@dataclass
class Track:
    """A track (layer) on the v2 timeline."""
    id: str
    type: str  # video | audio | subtitle
    name: str = ""
    index: int = 0
    enabled: bool = True
    locked: bool = False
    # Audio-specific
    mute: bool = False
    solo: bool = False
    # Video track-level
    opacity: float = 1.0
    gain_db: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Clip:
    """A clip on the timeline."""
    id: str
    asset_id: str
    track: str  # video | audio | subtitle | overlay
    start: float  # position on timeline (seconds)
    duration: float  # clip duration on timeline
    in_point: float = 0  # trim start in source
    out_point: float = 0  # trim end in source (0 = full)
    volume: float = 1.0
    speed: float = 1.0
    loop: bool = False  # auto-loop to fill duration
    effects: list[Effect] = field(default_factory=list)
    z_index: int = 0  # layer order for overlays
    # Overlay-specific
    opacity: float = 1.0  # 0.0–1.0, used for overlay track
    blend_mode: str = "normal"  # normal | screen | addition | multiply
    # Subtitle-specific
    sub_style: str = ""  # ASS style override
    sub_position: str = "bottom"  # top | middle | bottom

    @property
    def end(self) -> float:
        return self.start + self.duration

    def to_dict(self) -> dict:
        d = asdict(self)
        d["effects"] = [e if isinstance(e, dict) else asdict(e) for e in self.effects]
        d["end"] = self.end
        return d


@dataclass
class Project:
    """Full editor project state."""
    id: str
    name: str
    width: int = 1920
    height: int = 1080
    fps: float = 30
    duration: float = 0  # auto-computed from clips
    assets: dict[str, Asset] = field(default_factory=dict)
    clips: list[Clip] = field(default_factory=list)
    # Timeline v2
    timeline_version: int = 2
    tracks: list[Track] = field(default_factory=list)
    # Render settings
    preset: str = "youtube"
    crf: int = 20
    audio_bitrate: str = "192k"
    # Subtitle settings
    sub_font: str = "Arial"
    sub_size: int = 48
    sub_color: str = "&H00FFFFFF"   # ASS color: white (AABBGGRR)
    sub_outline_color: str = "&H00000000"  # black outline
    sub_outline_width: int = 2
    sub_position: str = "bottom"    # legacy, kept for compat
    sub_margin_v: int = 40          # legacy
    sub_y_percent: int = 85         # 0=top, 100=bottom
    sub_lines: int = 1             # 1 = only current, 2 = current+next, 3 = prev+current+next
    sub_bg_enabled: bool = True
    sub_bg_color: str = "&H80000000"  # ASS: semi-transparent black
    sub_highlight_color: str = "&H0000FFFF"  # ASS: yellow karaoke highlight
    video_fit: str = "cover"  # cover | contain | stretch

    @property
    def computed_duration(self) -> float:
        if not self.clips:
            return 0
        return max(c.end for c in self.clips)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "timeline_version": self.timeline_version,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration": self.computed_duration,
            "tracks": [t.to_dict() for t in self.tracks],
            "preset": self.preset,
            "crf": self.crf,
            "audio_bitrate": self.audio_bitrate,
            "sub_font": self.sub_font,
            "sub_size": self.sub_size,
            "sub_color": self.sub_color,
            "sub_outline_color": self.sub_outline_color,
            "sub_outline_width": self.sub_outline_width,
            "sub_position": self.sub_position,
            "sub_margin_v": self.sub_margin_v,
            "sub_y_percent": self.sub_y_percent,
            "sub_lines": self.sub_lines,
            "sub_bg_enabled": self.sub_bg_enabled,
            "sub_bg_color": self.sub_bg_color,
            "sub_highlight_color": self.sub_highlight_color,
            "video_fit": self.video_fit,
            "assets": {k: v.to_dict() for k, v in self.assets.items()},
            "clips": [c.to_dict() for c in self.clips],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        assets = {k: Asset(**v) for k, v in d.get("assets", {}).items()}
        clips = []
        for cd in d.get("clips", []):
            cd.pop("end", None)
            efx = [Effect(**e) if isinstance(e, dict) else e for e in cd.pop("effects", [])]
            clips.append(Clip(**cd, effects=efx))
        tracks = []
        for td in d.get("tracks", []):
            tracks.append(Track(**td))
        proj = cls(
            id=d["id"], name=d["name"],
            width=d.get("width", 1920), height=d.get("height", 1080),
            fps=d.get("fps", 30), preset=d.get("preset", "youtube"),
            crf=d.get("crf", 20), audio_bitrate=d.get("audio_bitrate", "192k"),
            timeline_version=d.get("timeline_version", 2),
            sub_font=d.get("sub_font", "Arial"),
            sub_size=d.get("sub_size", 48),
            sub_color=d.get("sub_color", "&H00FFFFFF"),
            sub_outline_color=d.get("sub_outline_color", "&H00000000"),
            sub_outline_width=d.get("sub_outline_width", 2),
            sub_position=d.get("sub_position", "bottom"),
            sub_margin_v=d.get("sub_margin_v", 40),
            sub_y_percent=d.get("sub_y_percent", 85),
            sub_lines=d.get("sub_lines", 1),
            sub_bg_enabled=d.get("sub_bg_enabled", True),
            sub_bg_color=d.get("sub_bg_color", "&H80000000"),
            sub_highlight_color=d.get("sub_highlight_color", "&H0000FFFF"),
            video_fit=d.get("video_fit", "cover"),
            assets=assets, clips=clips, tracks=tracks,
        )
        # Upgrade legacy v1 projects: ensure default tracks exist
        if not proj.tracks:
            proj.tracks = _default_tracks()
        return proj


# ── Default tracks for new projects ──────────────────────────────────────────

def _default_tracks() -> list[Track]:
    """Create default V1+A1+S1 tracks for a new project."""
    return [
        Track(id=_uid(), type="video", name="V1", index=0),
        Track(id=_uid(), type="audio", name="A1", index=1),
        Track(id=_uid(), type="subtitle", name="S1", index=2),
    ]


def legacy_project_to_v2(data: dict) -> dict:
    """Convert a v1 project dict to v2 format (upgrade-on-read).

    Creates default tracks and sets timeline_version=2.
    Idempotent: v2 dicts pass through unchanged.
    """
    if data.get("timeline_version", 0) >= 2:
        return data

    data = copy.deepcopy(data)
    data["timeline_version"] = 2

    # Build tracks from existing clip track types
    used_types: set[str] = set()
    for clip in data.get("clips", []):
        t = clip.get("track", "video")
        # Map overlay -> video for track purposes
        if t == "overlay":
            used_types.add("video")
        elif t in TRACK_TYPES:
            used_types.add(t)

    tracks = []
    idx = 0
    for ttype in ("video", "audio", "subtitle"):
        if ttype in used_types or ttype in ("video", "audio"):
            tracks.append({
                "id": uuid.uuid4().hex[:10],
                "type": ttype,
                "name": f"{ttype[0].upper()}1",
                "index": idx,
                "enabled": True,
                "locked": False,
                "mute": False,
                "solo": False,
                "opacity": 1.0,
                "gain_db": 0.0,
            })
            idx += 1

    data["tracks"] = tracks
    return data


# ── In-memory project store with undo/redo ────────────────────────────────────

_projects: dict[str, Project] = {}
_undo_stacks: dict[str, deque[str]] = {}
_redo_stacks: dict[str, deque[str]] = {}
_editor_lock = threading.Lock()


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def create_project(name: str = "Untitled", width: int = 1920,
                   height: int = 1080, fps: float = 30) -> Project:
    pid = _uid()
    proj = Project(id=pid, name=name, width=width, height=height, fps=fps,
                   tracks=_default_tracks())
    _projects[pid] = proj
    _undo_stacks[pid] = deque(maxlen=MAX_UNDO)
    _redo_stacks[pid] = deque(maxlen=MAX_UNDO)
    info(f"[editor] Project created: {pid} ({name})")
    return proj


def get_project(pid: str) -> Project | None:
    return _projects.get(pid)


def list_projects() -> list[dict]:
    return [
        {"id": p.id, "name": p.name, "clips": len(p.clips),
         "duration": p.computed_duration, "assets": len(p.assets)}
        for p in _projects.values()
    ]


def _push_undo(pid: str) -> None:
    p = _projects.get(pid)
    if not p:
        return
    if pid not in _undo_stacks:
        _undo_stacks[pid] = deque(maxlen=MAX_UNDO)
        _redo_stacks[pid] = deque(maxlen=MAX_UNDO)
    _undo_stacks[pid].append(p.to_json())
    _redo_stacks[pid].clear()


def undo(pid: str) -> bool:
    if pid not in _undo_stacks or not _undo_stacks[pid]:
        return False
    p = _projects[pid]
    _redo_stacks.setdefault(pid, deque(maxlen=MAX_UNDO)).append(p.to_json())
    snapshot = _undo_stacks[pid].pop()
    _projects[pid] = Project.from_dict(json.loads(snapshot))
    return True


def redo(pid: str) -> bool:
    if pid not in _redo_stacks or not _redo_stacks[pid]:
        return False
    p = _projects[pid]
    _undo_stacks.setdefault(pid, deque(maxlen=MAX_UNDO)).append(p.to_json())
    snapshot = _redo_stacks[pid].pop()
    _projects[pid] = Project.from_dict(json.loads(snapshot))
    return True


def save_project(pid: str) -> Path | None:
    p = _projects.get(pid)
    if not p:
        return None
    # Use project name in filename for easier identification
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (p.name or "")).strip()[:40]
    if safe_name and safe_name.lower() != "untitled":
        filename = f"{safe_name}_{pid[:8]}.json"
    else:
        filename = f"{pid}.json"
    path = EDITOR_DIR / "projects" / filename
    path.write_text(p.to_json(), encoding="utf-8")
    info(f"[editor] Project saved: {path}")
    return path


def load_project(path: Path) -> Project | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        proj = Project.from_dict(data)
        _projects[proj.id] = proj
        _undo_stacks[proj.id] = deque(maxlen=MAX_UNDO)
        _redo_stacks[proj.id] = deque(maxlen=MAX_UNDO)
        return proj
    except Exception as e:
        error(f"[editor] Failed to load project: {e}")
        return None


# ── Asset management ──────────────────────────────────────────────────────────

def add_asset(pid: str, filename: str, file_path: Path) -> Asset | None:
    p = _projects.get(pid)
    if not p:
        return None

    # Detect type
    ext = file_path.suffix.lower()
    if ext in (".mp4", ".mov", ".webm", ".avi", ".mkv"):
        atype = "video"
    elif ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"):
        atype = "audio"
    elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
        atype = "image"
    elif ext in (".srt", ".ass", ".vtt", ".lrc"):
        atype = "subtitle"
    else:
        atype = "video"  # fallback

    # Probe for metadata
    probe = probe_media(file_path)

    # For subtitle files: parse to get actual duration from timestamps
    if atype == "subtitle" and probe.duration <= 0:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            max_end = 0.0
            if ext in (".srt", ".vtt"):
                import re
                for m in re.finditer(
                    r"(\d{2}):(\d{2}):(\d{2})[,.](\d+)\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d+)",
                    text,
                ):
                    end = int(m[5]) * 3600 + int(m[6]) * 60 + int(m[7]) + int(m[8]) / 1000
                    if end > max_end:
                        max_end = end
            elif ext == ".ass":
                for line in text.split("\n"):
                    if line.startswith("Dialogue:"):
                        parts = line[10:].split(",", 9)
                        if len(parts) >= 3:
                            try:
                                tp = parts[2].strip().split(":")
                                end = int(tp[0]) * 3600 + int(tp[1]) * 60 + float(tp[2])
                                if end > max_end:
                                    max_end = end
                            except (ValueError, IndexError):
                                pass
            if max_end > 0:
                probe.duration = max_end
                info(f"[editor] Parsed subtitle duration: {max_end:.1f}s from {filename}")
        except Exception as e:
            warn(f"[editor] Failed to parse subtitle duration: {e}")

    aid = _uid()

    # Generate thumbnail for video/image
    thumb_path = ""
    if atype in ("video", "image"):
        try:
            thumb_file = EDITOR_DIR / "assets" / f"thumb_{aid}.jpg"
            if atype == "video":
                run_media_subprocess([
                    "ffmpeg", "-y", "-i", str(file_path),
                    "-ss", "1", "-frames:v", "1",
                    "-vf", "scale=160:-1", str(thumb_file)
                ], tool="ffmpeg", description=f"thumb {filename}",
                   timeout=15, heavy=False)
            else:
                run_media_subprocess([
                    "ffmpeg", "-y", "-i", str(file_path),
                    "-vf", "scale=160:-1", str(thumb_file)
                ], tool="ffmpeg", description=f"thumb {filename}",
                   timeout=15, heavy=False)
            if thumb_file.exists():
                thumb_path = str(thumb_file)
        except Exception:
            pass

    asset = Asset(
        id=aid, filename=filename, path=str(file_path),
        type=atype, duration=probe.duration,
        width=probe.width, height=probe.height,
        fps=probe.fps, has_audio=probe.has_audio,
        thumbnail=thumb_path,
    )
    _push_undo(pid)
    p.assets[aid] = asset
    info(f"[editor] Asset added: {aid} ({filename}, {atype}, {probe.duration:.1f}s)")
    return asset


# ── Clip operations ───────────────────────────────────────────────────────────

def add_clip(pid: str, asset_id: str, track: str = "video",
             start: float = -1, duration: float = 0,
             **kwargs) -> Clip | None:
    """Add a clip to the timeline. start=-1 means append at end of track."""
    p = _projects.get(pid)
    if not p:
        return None
    asset = p.assets.get(asset_id)
    if not asset:
        warn(f"[editor] Asset not found: {asset_id}")
        return None

    _push_undo(pid)

    # Auto-position
    if start < 0:
        track_clips = [c for c in p.clips if c.track == track]
        start = max((c.end for c in track_clips), default=0)

    # Auto-duration
    if duration <= 0:
        if asset.type == "image":
            duration = 5.0  # default 5s for images
        elif asset.duration > 0:
            duration = asset.duration
        else:
            duration = 5.0

    clip = Clip(
        id=_uid(), asset_id=asset_id, track=track,
        start=round(start, 3), duration=round(duration, 3),
        out_point=asset.duration if asset.duration > 0 else 0,
        **kwargs,
    )
    p.clips.append(clip)
    p.clips.sort(key=lambda c: (c.track, c.start))
    info(f"[editor] Clip added: {clip.id} on {track} at {start:.1f}s ({duration:.1f}s)")
    return clip


def remove_clip(pid: str, clip_id: str) -> bool:
    p = _projects.get(pid)
    if not p:
        return False
    _push_undo(pid)
    before = len(p.clips)
    p.clips = [c for c in p.clips if c.id != clip_id]
    return len(p.clips) < before


def update_clip(pid: str, clip_id: str, **kwargs) -> Clip | None:
    _READONLY_CLIP_FIELDS = frozenset({"end", "id"})
    p = _projects.get(pid)
    if not p:
        return None
    for c in p.clips:
        if c.id == clip_id:
            _push_undo(pid)
            for k, v in kwargs.items():
                if k in _READONLY_CLIP_FIELDS:
                    continue
                if hasattr(c, k):
                    setattr(c, k, v)
            return c
    return None


def split_clip(pid: str, clip_id: str, at_time: float) -> tuple[Clip, Clip] | None:
    """Split a clip at a given timeline time."""
    p = _projects.get(pid)
    if not p:
        return None
    for i, c in enumerate(p.clips):
        if c.id == clip_id and c.start < at_time < c.end:
            _push_undo(pid)
            speed = c.speed if c.speed else 1.0
            dur1 = at_time - c.start
            dur2 = c.end - at_time
            # First half
            c.duration = round(dur1, 3)
            c.out_point = c.in_point + dur1 / speed
            # Second half
            c2 = Clip(
                id=_uid(), asset_id=c.asset_id, track=c.track,
                start=round(at_time, 3), duration=round(dur2, 3),
                in_point=c.out_point, out_point=c.out_point + dur2 / speed,
                volume=c.volume, speed=c.speed, loop=c.loop,
                effects=copy.deepcopy(c.effects),
            )
            p.clips.insert(i + 1, c2)
            return (c, c2)
    return None


def add_effect(pid: str, clip_id: str, effect_type: str,
               params: dict | None = None) -> Effect | None:
    p = _projects.get(pid)
    if not p:
        return None
    for c in p.clips:
        if c.id == clip_id:
            _push_undo(pid)
            effect = Effect(type=effect_type, params=params or {})
            c.effects.append(effect)
            return effect
    return None


def remove_effect(pid: str, clip_id: str, effect_index: int) -> bool:
    p = _projects.get(pid)
    if not p:
        return False
    for c in p.clips:
        if c.id == clip_id and 0 <= effect_index < len(c.effects):
            _push_undo(pid)
            c.effects.pop(effect_index)
            return True
    return False


# ── Track management (v2) ─────────────────────────────────────────────────────

def add_track(pid: str, track_type: str, name: str = "",
              index: int | None = None) -> Track | None:
    """Add a new track to the project. Returns the created Track or None."""
    p = _projects.get(pid)
    if not p:
        return None
    if track_type not in TRACK_TYPES:
        warn(f"[editor] Invalid track type: {track_type}")
        return None

    _push_undo(pid)

    # Auto-name
    if not name:
        prefix = track_type[0].upper()
        existing = [t for t in p.tracks if t.type == track_type]
        name = f"{prefix}{len(existing) + 1}"

    # Auto-index
    if index is None:
        index = max((t.index for t in p.tracks), default=-1) + 1

    track = Track(id=_uid(), type=track_type, name=name, index=index)
    p.tracks.append(track)
    p.tracks.sort(key=lambda t: t.index)
    info(f"[editor] Track added: {track.id} ({track.type}/{track.name}) at index {index}")
    return track


def remove_track(pid: str, track_id: str, force: bool = False,
                 migrate_to_track_id: str | None = None) -> bool:
    """Remove a track. Clips on it are deleted (with undo) unless migrated.

    Rules:
    - Empty tracks can always be removed.
    - Non-empty tracks require force=True or migrate_to_track_id.
    - When migrate_to_track_id is set, clips move to that track.
    - If the removed track is the last of its type, clips of that type are deleted.
    """
    p = _projects.get(pid)
    if not p:
        return False

    track = next((t for t in p.tracks if t.id == track_id), None)
    if not track:
        return False

    # Identify clips belonging to this track's type
    track_clips = [c for c in p.clips if c.track == track.type]

    if track_clips and not force and not migrate_to_track_id:
        remaining_same_type = [t for t in p.tracks if t.type == track.type and t.id != track_id]
        if not remaining_same_type:
            warn(f"[editor] Cannot remove non-empty track {track_id} without force or migration")
            return False

    _push_undo(pid)

    if track_clips and migrate_to_track_id:
        target = next((t for t in p.tracks if t.id == migrate_to_track_id), None)
        if target and target.type == track.type:
            info(f"[editor] Migrating {len(track_clips)} clips to track {target.id}")
            # Clips stay as-is since they use track type string
        else:
            # Cannot migrate to different type; delete clips if last of this type
            remaining_same_type = [t for t in p.tracks if t.type == track.type and t.id != track_id]
            if not remaining_same_type:
                p.clips = [c for c in p.clips if c.track != track.type]
    elif track_clips and force:
        # Delete clips if this is the last track of its type
        remaining_same_type = [t for t in p.tracks if t.type == track.type and t.id != track_id]
        if not remaining_same_type:
            p.clips = [c for c in p.clips if c.track != track.type]

    p.tracks = [t for t in p.tracks if t.id != track_id]
    info(f"[editor] Track removed: {track_id}")
    return True


def update_track(pid: str, track_id: str, **kwargs) -> Track | None:
    """Update track properties (name, index, enabled, locked, mute, solo, opacity, gain_db)."""
    p = _projects.get(pid)
    if not p:
        return None

    _ALLOWED = {"name", "index", "enabled", "locked", "mute", "solo", "opacity", "gain_db"}
    for t in p.tracks:
        if t.id == track_id:
            _push_undo(pid)
            for k, v in kwargs.items():
                if k in _ALLOWED and hasattr(t, k):
                    setattr(t, k, v)
            return t
    return None


def reorder_tracks(pid: str, track_ids: list[str]) -> bool:
    """Reorder tracks by assigning new indices based on list order."""
    p = _projects.get(pid)
    if not p:
        return False

    track_map = {t.id: t for t in p.tracks}
    if not all(tid in track_map for tid in track_ids):
        return False

    _push_undo(pid)
    for i, tid in enumerate(track_ids):
        track_map[tid].index = i
    p.tracks.sort(key=lambda t: t.index)
    return True


# ── Render ────────────────────────────────────────────────────────────────────

# Supported blend modes for overlay clips (ffmpeg blend filter mode names)
_OVERLAY_BLEND_MODES = frozenset({"normal", "screen", "addition", "multiply"})


def _parse_srt_cues(text: str) -> list[dict]:
    """Parse SRT file into [{start, end, text}]."""
    import re
    cues = []
    for block in text.strip().split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        ts_line = None
        for l in lines:
            if re.search(r"\d{2}:\d{2}:\d{2}", l):
                ts_line = l
                break
        if not ts_line:
            continue
        m = re.match(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d+)\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d+)",
            ts_line,
        )
        if not m:
            continue
        start = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4]) / 1000
        end = int(m[5]) * 3600 + int(m[6]) * 60 + int(m[7]) + int(m[8]) / 1000
        text_lines = [l for l in lines if l != ts_line and not re.match(r"^\d+$", l.strip())]
        cues.append({"start": start, "end": end, "text": "\n".join(text_lines).strip()})
    return cues


def _parse_ass_cues(text: str) -> list[dict]:
    """Parse ASS Dialogue lines into [{start, end, text}]."""
    cues = []
    for line in text.split("\n"):
        if not line.startswith("Dialogue:"):
            continue
        parts = line[10:].split(",", 9)
        if len(parts) < 10:
            continue

        def _t(s: str) -> float:
            p = s.strip().split(":")
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])

        start, end = _t(parts[1]), _t(parts[2])
        raw = parts[9]
        import re
        txt = re.sub(r"\{[^}]*\}", "", raw).replace("\\N", "\n").replace("\\n", "\n").strip()
        if txt:
            cues.append({"start": start, "end": end, "text": txt})
    return cues


def _fmt_ass_time(secs: float) -> str:
    """Format seconds as ASS timestamp: H:MM:SS.cc"""
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = secs % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def generate_styled_ass(
    sub_path: Path,
    project: Project,
    output_path: Path,
    segments: list | None = None,
) -> Path | None:
    """Generate an ASS file with styled subtitles, karaoke tags, and multi-line display.

    If *segments* (list[TranscriptSegment]) is provided, karaoke tags are generated
    from word-level timestamps — this is the preferred path for accurate karaoke.
    Otherwise cues are parsed from the file on disk (tags will be stripped).

    sub_lines=1: only current line
    sub_lines=2: current + next
    sub_lines=3: prev + current + next
    """

    # ── Build cues — prefer TranscriptSegment objects (preserves word TS) ──
    if segments:
        cues = []
        for seg in segments:
            cue: dict = {"start": seg.start, "end": seg.end, "text": seg.text}
            if seg.has_word_timestamps and seg.words:
                cue["words"] = [{"start": w.start, "end": w.end, "word": w.word} for w in seg.words]
            cues.append(cue)
    else:
        text = sub_path.read_text(encoding="utf-8", errors="replace")
        ext = sub_path.suffix.lower()
        if ext in (".srt", ".vtt"):
            cues = _parse_srt_cues(text)
        elif ext == ".ass":
            cues = _parse_ass_cues(text)
        else:
            return None

    if not cues:
        warn(f"[editor] No cues found in {sub_path.name}")
        return None

    p = project
    w, h = p.width, p.height

    # Convert y_percent (0=top, 100=bottom) to ASS alignment + MarginV
    y_pct = getattr(p, 'sub_y_percent', 85)
    if y_pct <= 33:
        alignment = 8  # top-center
        mv = int(y_pct / 100 * h)
    elif y_pct <= 66:
        alignment = 5  # middle-center
        mv = int(abs(y_pct - 50) / 100 * h)
    else:
        alignment = 2  # bottom-center
        mv = int((100 - y_pct) / 100 * h)

    # Background box: BorderStyle 3 = opaque box, 1 = outline only
    bg_enabled = getattr(p, 'sub_bg_enabled', True)
    bg_color = getattr(p, 'sub_bg_color', '&H80000000')
    border_style = 3 if bg_enabled else 1
    shadow_depth = 0 if bg_enabled else 1

    # Build ASS header
    header = f"""[Script Info]
Title: Styled Subtitles
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Current,{p.sub_font},{p.sub_size},{p.sub_color},{p.sub_highlight_color},{p.sub_outline_color},{bg_color},-1,0,0,0,100,100,0,0,{border_style},{p.sub_outline_width},{shadow_depth},{alignment},20,20,{mv},1
Style: Context,{p.sub_font},{int(p.sub_size * 0.75)},&H80FFFFFF,&H000000FF,{p.sub_outline_color},{bg_color},0,0,0,0,100,100,0,0,{border_style},{max(1, p.sub_outline_width - 1)},{shadow_depth},{alignment},20,20,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    n_lines = p.sub_lines

    for i, cue in enumerate(cues):
        start_ts = _fmt_ass_time(cue["start"])
        end_ts = _fmt_ass_time(cue["end"])

        # ── Generate karaoke-tagged text if word timestamps available ──
        words = cue.get("words")
        if words and len(words) > 0:
            # Use \kf (progressive fill) for karaoke.
            # ASS \kf fills from SecondaryColour → PrimaryColour, so we override
            # \1c = highlight (sung/filled) and \2c = base (not yet sung) on every word
            # to ensure the fill direction matches the HTML preview.
            hl = p.sub_highlight_color or "&H0000FFFF"
            base = p.sub_color or "&H00FFFFFF"
            parts = []
            for wi, word in enumerate(words):
                dur_cs = max(1, round((word["end"] - word["start"]) * 100))
                parts.append(f"{{\\kf{dur_cs}\\1c{hl}\\2c{base}}}{word['word']}")
                if wi < len(words) - 1:
                    parts.append(" ")
            current_text = "".join(parts)
        else:
            current_text = cue["text"].replace("\n", r"\N")

        # Inline override tag for context lines
        ctx_size = int(p.sub_size * 0.75)
        ctx_tag = r"{\fs" + str(ctx_size) + r"\1a&H80&\b0}"

        if n_lines == 1:
            events.append(
                f"Dialogue: 0,{start_ts},{end_ts},Current,,0,0,0,,{current_text}"
            )
        elif n_lines == 2:
            next_cue = cues[i + 1] if i + 1 < len(cues) else None
            next_text = next_cue["text"].replace("\n", r"\N") if next_cue else ""
            combined = current_text
            if next_text:
                combined += r"\N" + ctx_tag + next_text
            events.append(
                f"Dialogue: 0,{start_ts},{end_ts},Current,,0,0,0,,{combined}"
            )
        elif n_lines >= 3:
            prev_cue = cues[i - 1] if i > 0 else None
            next_cue = cues[i + 1] if i + 1 < len(cues) else None
            prev_text = prev_cue["text"].replace("\n", r"\N") if prev_cue else ""
            next_text = next_cue["text"].replace("\n", r"\N") if next_cue else ""
            parts_combined = []
            if prev_text:
                parts_combined.append(ctx_tag + prev_text + r"\N")
            parts_combined.append(r"{\r}" + current_text)
            if next_text:
                parts_combined.append(r"\N" + ctx_tag + next_text)
            combined = "".join(parts_combined)
            events.append(
                f"Dialogue: 0,{start_ts},{end_ts},Current,,0,0,0,,{combined}"
            )

    ass_content = header + "\n".join(events) + "\n"
    output_path.write_text(ass_content, encoding="utf-8")
    has_karaoke = any(cue.get("words") for cue in cues)
    tag_info = " with karaoke tags" if has_karaoke else ""
    info(f"[editor] Generated styled ASS: {output_path.name} ({len(cues)} cues, {n_lines} lines{tag_info})")
    render_log(f"Styled ASS: {output_path.name} ({len(cues)} cues, {n_lines} lines{tag_info})")
    return output_path

def build_render_cmd(pid: str, output_path: Path) -> list[str] | None:
    """Build the ffmpeg command for the full timeline render.

    Filter graph structure:
      - Input 0: black canvas (base)
      - Input 1..N: video/image clips
      - Input N+1..M: audio clips
      - Video chain: canvas → overlay(clip1) → overlay(clip2) → ... → subtitles → [vout]
      - Audio chain: audio clips → delays → amix → [aout]
    """
    p = _projects.get(pid)
    if not p or not p.clips:
        return None

    duration = p.computed_duration
    if duration <= 0:
        warn("[editor] Project has zero duration")
        return None

    w, h = p.width + (p.width % 2), p.height + (p.height % 2)

    inputs: list[str] = []
    filter_parts: list[str] = []
    input_idx = 0

    # ── Input 0: Base canvas (black) ──
    inputs.extend(["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d={duration}:r={p.fps}"])
    video_chain = f"{input_idx}:v"  # current video stream label (without brackets)
    input_idx += 1

    # ── Collect clips by track ──
    video_clips = sorted(
        [c for c in p.clips if c.track in ("video", "overlay")],
        key=lambda c: (c.z_index, c.start),
    )
    audio_clips = [c for c in p.clips if c.track == "audio"]
    sub_clips = [c for c in p.clips if c.track == "subtitle"]

    # ── Video/Image clips → scale + overlay chain ──
    for ci, clip in enumerate(video_clips):
        asset = p.assets.get(clip.asset_id)
        if not asset:
            continue

        clip_idx = input_idx

        # Add input
        if asset.type == "image":
            inputs.extend(["-loop", "1", "-t", str(clip.duration), "-i", asset.path])
        elif clip.loop and asset.duration > 0 and clip.duration > asset.duration:
            loops = int(clip.duration / asset.duration) + 1
            inputs.extend(["-stream_loop", str(loops), "-t", str(clip.duration), "-i", asset.path])
        else:
            if clip.in_point > 0:
                inputs.extend(["-ss", str(clip.in_point)])
            inputs.extend(["-t", str(clip.duration), "-i", asset.path])
        input_idx += 1

        # Scale + effects filter chain
        from src.video.render import _scale_filter
        is_overlay = clip.track == "overlay"
        vf_parts = _scale_filter(w, h, p.video_fit)

        # Overlay-specific: ensure rgba format and apply opacity
        if is_overlay:
            vf_parts.append("format=rgba")
            if abs(clip.opacity - 1.0) > 1e-6:
                vf_parts.append(f"colorchannelmixer=aa={clip.opacity:.3f}")

        if clip.speed != 1.0:
            vf_parts.append(f"setpts=PTS/{clip.speed}")

        for eff in clip.effects:
            vf_eff = _effect_to_filter(eff, clip)
            if vf_eff:
                vf_parts.append(vf_eff)

        prep_label = f"vp{ci}"
        filter_parts.append(f"[{clip_idx}:v]{','.join(vf_parts)}[{prep_label}]")

        # Composite onto video chain
        ov_label = f"vo{ci}"
        enable = f"between(t,{clip.start:.3f},{clip.end:.3f})"

        if is_overlay and clip.blend_mode != "normal" and clip.blend_mode in _OVERLAY_BLEND_MODES:
            # Use blend filter for non-normal blend modes
            filter_parts.append(
                f"[{video_chain}][{prep_label}]blend=all_mode={clip.blend_mode}:enable='{enable}'[{ov_label}]"
            )
        else:
            # Standard overlay (alpha compositing)
            filter_parts.append(
                f"[{video_chain}][{prep_label}]overlay=0:0:enable='{enable}'[{ov_label}]"
            )
        video_chain = ov_label

    # ── Audio clips → delay + mix ──
    audio_labels = []
    for ai, clip in enumerate(audio_clips):
        asset = p.assets.get(clip.asset_id)
        if not asset:
            continue

        clip_idx = input_idx
        if clip.in_point > 0:
            inputs.extend(["-ss", str(clip.in_point)])
        if clip.loop and asset.duration > 0 and clip.duration > asset.duration:
            loops = int(clip.duration / asset.duration) + 1
            inputs.extend(["-stream_loop", str(loops)])
        inputs.extend(["-t", str(clip.duration), "-i", asset.path])
        input_idx += 1

        af_parts = []
        if clip.volume != 1.0:
            af_parts.append(f"volume={clip.volume}")
        if clip.speed != 1.0:
            af_parts.append(f"atempo={clip.speed}")
        delay_ms = int(clip.start * 1000)
        if delay_ms > 0:
            af_parts.append(f"adelay={delay_ms}|{delay_ms}")
        af_parts.append(f"apad=pad_dur={duration}")

        a_label = f"ad{ai}"
        filter_parts.append(f"[{clip_idx}:a]{','.join(af_parts)}[{a_label}]")
        audio_labels.append(a_label)

    if audio_labels:
        mix_in = "".join(f"[{l}]" for l in audio_labels)
        filter_parts.append(f"{mix_in}amix=inputs={len(audio_labels)}:duration=longest[aout]")

    # ── Subtitle burn-in (only first clip, matching player behavior) ──
    if len(sub_clips) > 1:
        warn(f"[editor] {len(sub_clips)} subtitle clips found, using only the first (matching player)")
    for si, clip in enumerate(sub_clips[:1]):
        asset = p.assets.get(clip.asset_id)
        if not asset:
            continue

        sub_path = Path(asset.path)

        # If subtitle comes from a job output dir, regenerate from segments.json
        # to ensure we always use the latest edited version
        _refreshed = False
        _segs_for_styled: list | None = None
        try:
            if "data/output/" in str(sub_path):
                seg_json = sub_path.parent / "segments.json"
                if seg_json.exists():
                    import json as _json
                    segs_data = _json.loads(seg_json.read_text(encoding="utf-8"))
                    from src.transcription.base import TranscriptSegment
                    segs = [TranscriptSegment.from_dict(s) for s in segs_data]
                    ext = sub_path.suffix.lower()
                    if ext == ".srt":
                        from src.export.srt_writer import write_srt
                        write_srt(segs, sub_path)
                    elif ext == ".ass":
                        from src.refine.alignment import ensure_word_timestamps
                        from src.export.ass_writer import write_ass
                        segs = ensure_word_timestamps(segs)
                        write_ass(segs, sub_path)
                    _segs_for_styled = segs
                    _refreshed = True
                    render_log(f"Refreshed {sub_path.name} from segments.json ({len(segs)} segments)")
                    info(f"[editor] Refreshed {sub_path.name} from segments.json before render")
        except Exception as e:
            warn(f"[editor] Could not refresh subtitle from segments.json: {e}")

        if not sub_path.exists():
            warn(f"[editor] Subtitle file not found: {sub_path}")
            continue

        sub_label = f"vs{si}"

        # Generate styled ASS with multi-line support, positioning, and karaoke tags
        styled_ass = EDITOR_DIR / "renders" / f"styled_{pid}_{si}.ass"
        styled_ass.parent.mkdir(parents=True, exist_ok=True)
        # Pass segments directly so generate_styled_ass can use word timestamps for \kf tags
        result = generate_styled_ass(sub_path, p, styled_ass, segments=_segs_for_styled)

        if result and result.exists():
            sub_path = result
        else:
            # Fallback: convert SRT to ASS via ffmpeg
            ext = sub_path.suffix.lower()
            if ext in (".srt", ".vtt"):
                ass_path = sub_path.with_suffix(".ass")
                if not ass_path.exists():
                    try:
                        run_media_subprocess([
                            "ffmpeg", "-y", "-i", str(sub_path), str(ass_path)
                        ], tool="ffmpeg", description="SRT→ASS fallback",
                           timeout=30, heavy=False)
                    except Exception:
                        pass
                if ass_path and ass_path.exists():
                    sub_path = ass_path

        # Escape path for ffmpeg filter
        esc_path = str(sub_path).replace("\\", "/")
        esc_path = esc_path.replace(":", "\\:")
        esc_path = esc_path.replace("'", "'\\''")
        esc_path = esc_path.replace("[", "\\[").replace("]", "\\]")

        filt = f"ass='{esc_path}'"
        filter_parts.append(f"[{video_chain}]{filt}[{sub_label}]")
        video_chain = sub_label

    # ── Final output label ──
    # Rename final video chain to [vout] using copy filter (passthrough)
    filter_parts.append(f"[{video_chain}]copy[vout]")

    filter_complex = ";\n".join(filter_parts)

    # Log for debugging
    render_log(f"Filter complex ({len(filter_parts)} parts):\n{filter_complex}")
    info(f"[editor] Filter complex ({len(filter_parts)} parts):\n{filter_complex}")

    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)
    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", "[vout]"])
    if audio_labels:
        cmd.extend(["-map", "[aout]"])
    cmd.extend([
        "-c:v", "libx264", "-preset", "medium",
        "-crf", str(p.crf), "-pix_fmt", "yuv420p",
        "-t", str(duration),
    ])
    if audio_labels:
        cmd.extend(["-c:a", "aac", "-b:a", p.audio_bitrate])
    else:
        cmd.append("-an")
    cmd.append(str(output_path))

    return cmd


def _effect_to_filter(eff: Effect, clip: Clip) -> str:
    """Convert an Effect to an ffmpeg filter string."""
    t = eff.type
    p = eff.params

    if t == "fade_in":
        d = p.get("duration", 1.0)
        return f"fade=t=in:st=0:d={d}"
    elif t == "fade_out":
        d = p.get("duration", 1.0)
        return f"fade=t=out:st={clip.duration - d}:d={d}"
    elif t == "brightness":
        v = p.get("value", 0.1)
        return f"eq=brightness={v}"
    elif t == "contrast":
        v = p.get("value", 1.2)
        return f"eq=contrast={v}"
    elif t == "saturation":
        v = p.get("value", 1.3)
        return f"eq=saturation={v}"
    elif t == "grayscale":
        return "hue=s=0"
    elif t == "sepia":
        return "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"
    elif t == "blur":
        s = p.get("sigma", 5)
        return f"gblur=sigma={s}"
    elif t == "rotate":
        angle = p.get("angle", 90)
        if angle == 90:
            return "transpose=1"
        elif angle == 180:
            return "transpose=1,transpose=1"
        elif angle == 270:
            return "transpose=2"
        return "null"
    elif t == "flip_h":
        return "hflip"
    elif t == "flip_v":
        return "vflip"
    elif t == "zoom":
        factor = p.get("factor", 1.2)
        return f"zoompan=z={factor}:d=1:s={clip.duration * 25}"
    elif t == "vignette":
        return "vignette"
    elif t == "sharpen":
        return "unsharp=5:5:1.5"
    elif t == "overlay_text":
        text = p.get("text", "").replace("'", "\\'")
        size = p.get("size", 48)
        color = p.get("color", "white")
        x = p.get("x", "(w-text_w)/2")
        y = p.get("y", "(h-text_h)/2")
        return f"drawtext=text='{text}':fontsize={size}:fontcolor={color}:x={x}:y={y}"

    return ""


def _prepare_render(pid: str) -> tuple[Path | None, list[str] | None, float, str]:
    """Prepare render: build output path + ffmpeg command. Returns (output, cmd, duration, error)."""
    import time
    set_job_id(pid)
    render_log(f"=== Render start for project {pid} ===")
    render_log(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    p = _projects.get(pid)
    if not p or not p.clips:
        render_log(f"No clips in project {pid}", level="error")
        return None, None, 0, "No clips"

    render_log(f"Project: {p.name} ({p.width}x{p.height} @ {p.fps}fps, {len(p.clips)} clips)")

    from datetime import datetime
    audio_clips = [c for c in p.clips if c.track == "audio"]
    if audio_clips:
        asset = p.assets.get(audio_clips[0].asset_id)
        base_name = Path(asset.filename).stem if asset else p.name
    else:
        base_name = p.name
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base_name).strip()[:60]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = EDITOR_DIR / "renders" / f"{safe_name}_{ts}.mp4"
    cmd = build_render_cmd(pid, output)
    if not cmd:
        render_log(f"Failed to build render command for {pid}", level="error")
        return None, None, 0, "Failed to build render command"
    render_log(f"Output: {output}")
    render_log(f"Duration: {p.computed_duration:.1f}s")
    return output, cmd, p.computed_duration, ""


def _parse_ffmpeg_time(line: str) -> float | None:
    """Extract elapsed seconds from ffmpeg stderr line (time=HH:MM:SS.cs)."""
    import re
    m = re.search(r"time=\s*(-?)(\d+):(\d+):(\d+(?:\.\d+)?)", line)
    if not m:
        return None
    sign, h, mi, s = m.group(1), int(m.group(2)), int(m.group(3)), float(m.group(4))
    t = h * 3600 + mi * 60 + s
    return -t if sign == "-" else t


def _extract_ffmpeg_error(stderr_text: str) -> str:
    """Extract meaningful error from ffmpeg stderr (strip banner/config)."""
    err_lines = stderr_text.strip().split("\n")
    useful = []
    skip_banner = True
    for line in err_lines:
        if skip_banner:
            if any(x in line for x in (
                "--enable-", "--disable-", "configuration:", "built with",
                "ffmpeg version", "Copyright",
            )):
                continue
            if line.strip().startswith("lib") and "/" in line:
                continue
            skip_banner = False
        useful.append(line)
    return "\n".join(useful[-15:]) if useful else stderr_text[-500:]


def render_project(pid: str) -> tuple[Path | None, str]:
    """Render the full project to MP4. Returns (path, error_msg)."""
    import time
    t0 = time.monotonic()
    output, cmd, duration, err = _prepare_render(pid)
    if not cmd:
        return None, err

    info(f"[editor] Rendering project {pid} → {output}")
    render_log(f"Rendering (blocking) project {pid} → {output}")
    debug(f"[editor] Full CMD:\n{' '.join(str(c) for c in cmd)}")
    for i, arg in enumerate(cmd):
        if arg == "-filter_complex" and i + 1 < len(cmd):
            debug(f"[editor] filter_complex:\n{cmd[i+1]}")
            render_log(f"filter_complex:\n{cmd[i+1]}")
            break

    try:
        r = run_media_subprocess(
            cmd, tool="ffmpeg", description=f"render project {pid}",
            timeout=max(600, duration * 5), heavy=True,
        )
        if r.returncode != 0:
            err_msg = _extract_ffmpeg_error(r.stderr)
            error(f"[editor] Render failed:\n{err_msg}")
            render_log(f"Render FAILED (exit={r.returncode}): {err_msg}", level="error")
            return None, err_msg
    except subprocess.TimeoutExpired:
        error("[editor] Render timed out")
        render_log("Render TIMED OUT", level="error")
        return None, "Render timed out"

    elapsed = time.monotonic() - t0
    if output.exists():
        mb = output.stat().st_size / (1024 * 1024)
        info(f"[editor] Rendered: {output.name} ({mb:.1f} MB)")
        render_log(f"Render OK: {output.name} ({mb:.1f} MB, {elapsed:.1f}s)")
        return output, ""
    render_log("Output file not created", level="error")
    return None, "Output file not created"


def render_project_with_progress(
    pid: str,
    progress_cb: callable | None = None,
) -> tuple[Path | None, str]:
    """Render with real-time progress via callback.

    progress_cb(phase: str, percent: int) is called during rendering.
    Percent is 0–100.  Phase is a short German label.
    """
    import time
    t0 = time.monotonic()
    output, cmd, duration, err = _prepare_render(pid)
    if not cmd:
        return None, err

    info(f"[editor] Rendering (streamed) project {pid} → {output}")
    render_log(f"Rendering (streamed) project {pid} → {output}")
    debug(f"[editor] Full CMD:\n{' '.join(str(c) for c in cmd)}")
    for i, arg in enumerate(cmd):
        if arg == "-filter_complex" and i + 1 < len(cmd):
            debug(f"[editor] filter_complex:\n{cmd[i+1]}")
            render_log(f"filter_complex:\n{cmd[i+1]}")
            break

    if progress_cb:
        progress_cb("Vorbereitung", 0)

    timeout_sec = max(600, duration * 5)
    try:
        proc, media_job_id, sem_acquired = run_media_popen(
            cmd, tool="ffmpeg", description=f"render (streamed) {pid}",
            heavy=True, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
            text=True, bufsize=1,
        )
    except FileNotFoundError:
        return None, "ffmpeg not found"

    if progress_cb:
        progress_cb("Rendering gestartet", 2)

    last_pct = 0
    stderr_lines: list[str] = []
    try:
        for line in proc.stderr:
            stderr_lines.append(line)
            if not progress_cb or duration <= 0:
                continue
            elapsed = _parse_ffmpeg_time(line)
            if elapsed is not None and elapsed >= 0:
                pct = min(int(elapsed / duration * 100), 99)
                if pct > last_pct:
                    last_pct = pct
                    progress_cb("Rendering", pct)

        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        release_media_popen(media_job_id, sem_acquired, returncode=-1, error_msg="Timeout")
        error("[editor] Render timed out (streamed)")
        render_log("Render TIMED OUT (streamed)", level="error")
        return None, "Render timed out"

    # Release semaphore now that process is done
    release_media_popen(media_job_id, sem_acquired,
                        returncode=proc.returncode,
                        error_msg="".join(stderr_lines[-5:]) if proc.returncode != 0 else "")

    if proc.returncode != 0:
        full_stderr = "".join(stderr_lines)
        err_msg = _extract_ffmpeg_error(full_stderr)
        error(f"[editor] Render failed:\n{err_msg}")
        render_log(f"Render FAILED (streamed, exit={proc.returncode}): {err_msg}", level="error")
        if progress_cb:
            progress_cb("Fehler", -1)
        return None, err_msg

    elapsed = time.monotonic() - t0
    if output.exists():
        mb = output.stat().st_size / (1024 * 1024)
        info(f"[editor] Rendered (streamed): {output.name} ({mb:.1f} MB)")
        render_log(f"Render OK (streamed): {output.name} ({mb:.1f} MB, {elapsed:.1f}s)")
        if progress_cb:
            progress_cb("Fertig", 100)
        return output, ""

    if progress_cb:
        progress_cb("Fehler", -1)
    return None, "Output file not created"


# ── Quick render: loop video from single asset ────────────────────────────────

def render_loop_video(
    source_path: Path, output_path: Path,
    loop_count: int = 3, duration: float = 0,
    effects: list[dict] | None = None,
    width: int = 1920, height: int = 1080,
    fps: int = 30, crf: int = 20,
) -> Path | None:
    """Quick render: loop a video/image with optional effects."""
    probe = probe_media(source_path)
    w = width + (width % 2)
    h = height + (height % 2)

    vf = [f"scale={w}:{h}:force_original_aspect_ratio=decrease",
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
          f"fps={fps}"]

    # Apply effects
    for eff_dict in (effects or []):
        eff = Effect(type=eff_dict.get("type", ""), params=eff_dict.get("params", {}))
        clip = Clip(id="tmp", asset_id="tmp", track="video", start=0,
                    duration=duration or probe.duration * loop_count)
        filt = _effect_to_filter(eff, clip)
        if filt:
            vf.append(filt)

    cmd = ["ffmpeg", "-y"]
    if probe.is_image:
        cmd.extend(["-loop", "1", "-i", str(source_path)])
    else:
        cmd.extend(["-stream_loop", str(loop_count - 1), "-i", str(source_path)])

    if duration > 0:
        cmd.extend(["-t", str(duration)])
    elif not probe.is_image:
        cmd.extend(["-t", str(probe.duration * loop_count)])
    else:
        cmd.extend(["-t", "10"])  # default 10s for images

    cmd.extend(["-vf", ",".join(vf)])
    cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-pix_fmt", "yuv420p"])

    if not probe.is_image and probe.has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.append("-an")

    cmd.append(str(output_path))
    info(f"[editor] Loop render: {source_path.name} × {loop_count} → {output_path.name}")

    try:
        r = run_media_subprocess(
            cmd, tool="ffmpeg", description=f"loop render {source_path.name}",
            timeout=300, heavy=True,
        )
        if r.returncode != 0:
            error(f"[editor] Loop render failed:\n{r.stderr[-1000:]}")
            return None
    except subprocess.TimeoutExpired:
        error("[editor] Loop render timed out")
        return None

    return output_path if output_path.exists() else None


# ── Timeline summary for AI ───────────────────────────────────────────────────

def get_timeline_summary(pid: str) -> str:
    """Get a human-readable timeline summary for AI chat context."""
    p = _projects.get(pid)
    if not p:
        return "No project loaded."

    lines = [
        f"Project: {p.name} ({p.width}x{p.height} @ {p.fps}fps, timeline_version={p.timeline_version})",
        f"Duration: {p.computed_duration:.1f}s",
        f"Assets: {len(p.assets)}, Clips: {len(p.clips)}, Tracks: {len(p.tracks)}",
        "",
    ]

    if p.tracks:
        lines.append("=== Tracks ===")
        for t in sorted(p.tracks, key=lambda t: t.index):
            flags = []
            if not t.enabled:
                flags.append("disabled")
            if t.locked:
                flags.append("locked")
            if t.mute:
                flags.append("mute")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"  [{t.id}] {t.name} ({t.type}, idx={t.index}){flag_str}")

    if p.assets:
        lines.append("\n=== Assets ===")
        for a in p.assets.values():
            lines.append(f"  [{a.id}] {a.filename} ({a.type}, {a.duration:.1f}s)")

    if p.clips:
        for track in ["video", "audio", "subtitle", "overlay"]:
            tc = [c for c in p.clips if c.track == track]
            if tc:
                lines.append(f"\n=== {track.upper()} Track ===")
                for c in tc:
                    asset = p.assets.get(c.asset_id)
                    name = asset.filename if asset else "?"
                    efx = ", ".join(e.type for e in c.effects) if c.effects else "none"
                    lines.append(
                        f"  [{c.id}] {name} @ {c.start:.1f}s–{c.end:.1f}s "
                        f"(speed={c.speed}x, vol={c.volume}, loop={c.loop}, fx={efx})"
                    )

    return "\n".join(lines)
