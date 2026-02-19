"""Media tag service — read/write ID3, MP4, FLAC, OGG metadata via mutagen.

Supports:
- MP3: ID3v2 tags
- M4A/MP4: MP4 atoms
- FLAC: Vorbis Comments
- OGG: Vorbis Comments
- WAV: limited (INFO tags)
- Video MP4/MOV: ffprobe read-only, mutagen MP4 atoms for write

Copy-on-write mode: creates *_tagged.ext instead of modifying original.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, error, debug


# ── Tag field definitions ─────────────────────────────────────────────────────

# Standard fields that all formats should try to support
STANDARD_FIELDS = [
    "title", "artist", "album", "album_artist", "genre", "year",
    "track", "disc", "comment", "lyrics", "composer", "copyright",
]

# Format capabilities
FORMAT_INFO = {
    ".mp3":  {"lib": "id3", "editable": True, "fields": STANDARD_FIELDS},
    ".m4a":  {"lib": "mp4", "editable": True, "fields": STANDARD_FIELDS},
    ".mp4":  {"lib": "mp4", "editable": True, "fields": STANDARD_FIELDS},
    ".flac": {"lib": "flac", "editable": True, "fields": STANDARD_FIELDS},
    ".ogg":  {"lib": "ogg", "editable": True, "fields": STANDARD_FIELDS},
    ".opus": {"lib": "ogg", "editable": True, "fields": STANDARD_FIELDS},
    ".wav":  {"lib": "wav", "editable": False, "fields": ["title", "artist"]},
    ".wma":  {"lib": "asf", "editable": True, "fields": STANDARD_FIELDS[:8]},
    ".mov":  {"lib": "mp4", "editable": False, "fields": ["title", "artist", "year", "comment"]},
    ".webm": {"lib": None, "editable": False, "fields": ["title"]},
    ".avi":  {"lib": None, "editable": False, "fields": []},
}

# ID3v2 frame mapping
_ID3_MAP = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB",
    "album_artist": "TPE2", "genre": "TCON", "year": "TDRC",
    "track": "TRCK", "disc": "TPOS", "comment": "COMM",
    "lyrics": "USLT", "composer": "TCOM", "copyright": "TCOP",
}

# MP4 atom mapping
_MP4_MAP = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb",
    "album_artist": "aART", "genre": "\xa9gen", "year": "\xa9day",
    "track": "trkn", "disc": "disk", "comment": "\xa9cmt",
    "lyrics": "\xa9lyr", "composer": "\xa9wrt", "copyright": "cprt",
}

# Vorbis comment mapping (FLAC, OGG)
_VORBIS_MAP = {
    "title": "TITLE", "artist": "ARTIST", "album": "ALBUM",
    "album_artist": "ALBUMARTIST", "genre": "GENRE", "year": "DATE",
    "track": "TRACKNUMBER", "disc": "DISCNUMBER", "comment": "COMMENT",
    "lyrics": "LYRICS", "composer": "COMPOSER", "copyright": "COPYRIGHT",
}


@dataclass
class MediaTags:
    """Parsed media tags with format info."""
    tags: dict[str, str]
    format: str                 # file extension
    editable: bool
    supported_fields: list[str]
    has_cover: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tags": self.tags,
            "format": self.format,
            "editable": self.editable,
            "supported_fields": self.supported_fields,
            "has_cover": self.has_cover,
        }


def is_taggable(path: Path) -> bool:
    """Check if a file format supports any tagging."""
    ext = path.suffix.lower()
    return ext in FORMAT_INFO


def _check_mutagen() -> bool:
    """Check if mutagen is installed."""
    try:
        import mutagen
        return True
    except ImportError:
        return False


# ── Read Tags ─────────────────────────────────────────────────────────────────

def read_tags(path: Path) -> MediaTags:
    """Read metadata tags from a media file."""
    ext = path.suffix.lower()
    fmt_info = FORMAT_INFO.get(ext, {"lib": None, "editable": False, "fields": []})

    tags: dict[str, str] = {}
    has_cover = False
    raw: dict[str, Any] = {}

    if _check_mutagen() and fmt_info["lib"]:
        try:
            tags, has_cover, raw = _read_mutagen(path, ext, fmt_info["lib"])
        except Exception as e:
            warn(f"Mutagen read failed for {path.name}: {e}")
            tags = _read_ffprobe(path)
    else:
        tags = _read_ffprobe(path)

    return MediaTags(
        tags=tags,
        format=ext,
        editable=fmt_info["editable"] and _check_mutagen(),
        supported_fields=fmt_info["fields"],
        has_cover=has_cover,
        raw=raw,
    )


def _read_mutagen(path: Path, ext: str, lib: str) -> tuple[dict[str, str], bool, dict]:
    """Read tags using mutagen."""
    import mutagen

    tags: dict[str, str] = {}
    has_cover = False
    raw: dict[str, Any] = {}

    f = mutagen.File(str(path), easy=False)
    if f is None:
        return tags, has_cover, raw

    if lib == "id3":
        from mutagen.id3 import ID3
        try:
            id3 = ID3(str(path))
        except Exception:
            return tags, has_cover, raw

        for field_name, frame_id in _ID3_MAP.items():
            frame = id3.get(frame_id)
            if frame:
                if frame_id == "COMM":
                    tags[field_name] = str(frame)
                elif frame_id == "USLT":
                    tags[field_name] = str(frame)
                else:
                    tags[field_name] = str(frame.text[0]) if hasattr(frame, "text") else str(frame)

        # Check for cover art
        has_cover = bool(id3.getall("APIC"))

    elif lib == "mp4":
        for field_name, atom in _MP4_MAP.items():
            val = f.tags.get(atom) if f.tags else None
            if val:
                if atom in ("trkn", "disk"):
                    tags[field_name] = str(val[0][0]) if isinstance(val[0], tuple) else str(val[0])
                else:
                    tags[field_name] = str(val[0])
        has_cover = bool(f.tags.get("covr")) if f.tags else False

    elif lib in ("flac", "ogg"):
        for field_name, vorbis_key in _VORBIS_MAP.items():
            val = f.tags.get(vorbis_key) if f.tags else None
            if val:
                tags[field_name] = str(val[0]) if isinstance(val, list) else str(val)
        if lib == "flac":
            has_cover = bool(getattr(f, "pictures", []))

    return tags, has_cover, {}


def _read_ffprobe(path: Path) -> dict[str, str]:
    """Read tags via ffprobe (fallback)."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        fmt_tags = data.get("format", {}).get("tags", {})

        mapping = {
            "title": ["title", "TITLE"],
            "artist": ["artist", "ARTIST", "album_artist"],
            "album": ["album", "ALBUM"],
            "genre": ["genre", "GENRE"],
            "year": ["date", "DATE", "year", "YEAR"],
            "track": ["track", "TRACK"],
            "comment": ["comment", "COMMENT", "description"],
        }

        tags: dict[str, str] = {}
        for field_name, keys in mapping.items():
            for k in keys:
                v = fmt_tags.get(k)
                if v:
                    tags[field_name] = str(v)
                    break
        return tags
    except Exception as e:
        warn(f"ffprobe tag read failed: {e}")
        return {}


# ── Write Tags ────────────────────────────────────────────────────────────────

def write_tags(
    path: Path,
    new_tags: dict[str, str],
    copy_on_write: bool = True,
) -> Path:
    """Write metadata tags to a media file.

    Args:
        path: Source media file
        new_tags: Dict of field_name -> value to set
        copy_on_write: If True, create *_tagged.ext copy (default)

    Returns:
        Path to the tagged file (original or copy)
    """
    if not _check_mutagen():
        raise RuntimeError("mutagen not installed — pip install mutagen")

    ext = path.suffix.lower()
    fmt_info = FORMAT_INFO.get(ext)
    if not fmt_info or not fmt_info["editable"]:
        raise ValueError(f"Format {ext} is not editable")

    # Validate fields
    allowed = set(fmt_info["fields"])
    invalid = set(new_tags.keys()) - allowed
    if invalid:
        raise ValueError(f"Unsupported fields for {ext}: {invalid}")

    # Copy-on-write
    target = path
    if copy_on_write:
        target = path.with_stem(path.stem + "_tagged")
        shutil.copy2(path, target)
        info(f"Copy-on-write: {path.name} → {target.name}")

    lib = fmt_info["lib"]

    if lib == "id3":
        _write_id3(target, new_tags)
    elif lib == "mp4":
        _write_mp4(target, new_tags)
    elif lib in ("flac", "ogg"):
        _write_vorbis(target, new_tags)
    else:
        raise ValueError(f"Write not supported for {lib}")

    info(f"Tags written to {target.name}: {list(new_tags.keys())}")
    return target


def _write_id3(path: Path, tags: dict[str, str]) -> None:
    """Write ID3v2 tags to MP3."""
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TCON, TDRC, TRCK, TPOS, TCOM, TCOP
    from mutagen.id3 import COMM, USLT

    try:
        id3 = ID3(str(path))
    except Exception:
        from mutagen.id3 import ID3NoHeaderError
        id3 = ID3()

    frame_classes = {
        "title": TIT2, "artist": TPE1, "album": TALB, "album_artist": TPE2,
        "genre": TCON, "year": TDRC, "track": TRCK, "disc": TPOS,
        "composer": TCOM, "copyright": TCOP,
    }

    for field_name, value in tags.items():
        if field_name == "comment":
            id3.delall("COMM")
            id3.add(COMM(encoding=3, lang="deu", desc="", text=value))
        elif field_name == "lyrics":
            id3.delall("USLT")
            id3.add(USLT(encoding=3, lang="deu", desc="", text=value))
        elif field_name in frame_classes:
            frame_id = _ID3_MAP[field_name]
            id3.delall(frame_id)
            id3.add(frame_classes[field_name](encoding=3, text=[value]))

    id3.save(str(path))


def _write_mp4(path: Path, tags: dict[str, str]) -> None:
    """Write MP4 atoms."""
    import mutagen
    f = mutagen.File(str(path))
    if f is None or f.tags is None:
        raise RuntimeError(f"Cannot open {path.name} for tagging")

    for field_name, value in tags.items():
        atom = _MP4_MAP.get(field_name)
        if not atom:
            continue
        if atom in ("trkn", "disk"):
            try:
                num = int(value)
                f.tags[atom] = [(num, 0)]
            except ValueError:
                pass
        else:
            f.tags[atom] = [value]

    f.save()


def _write_vorbis(path: Path, tags: dict[str, str]) -> None:
    """Write Vorbis comments (FLAC/OGG)."""
    import mutagen
    f = mutagen.File(str(path))
    if f is None:
        raise RuntimeError(f"Cannot open {path.name} for tagging")

    if f.tags is None:
        # Create tags
        try:
            f.add_tags()
        except Exception:
            pass

    for field_name, value in tags.items():
        vorbis_key = _VORBIS_MAP.get(field_name)
        if vorbis_key and f.tags is not None:
            f.tags[vorbis_key] = [value]

    f.save()
