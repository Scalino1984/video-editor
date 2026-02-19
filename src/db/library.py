"""Transcriptions Library — SQLite storage for completed transcriptions.

Schema auto-created on first connect. No ORM dependency — raw sqlite3.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, debug

_DB_PATH: Path | None = None
_con: sqlite3.Connection | None = None
_db_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcriptions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    source_hash TEXT,
    language TEXT DEFAULT '',
    backend TEXT DEFAULT '',
    duration_sec REAL DEFAULT 0,
    bpm REAL DEFAULT 0,
    segments_count INTEGER DEFAULT 0,
    has_word_timestamps INTEGER DEFAULT 0,
    needs_review INTEGER DEFAULT 0,
    avg_confidence REAL DEFAULT 0,
    srt_text TEXT,
    ass_text TEXT,
    segments_json TEXT,
    job_id TEXT,
    tags TEXT DEFAULT '[]',
    deleted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    mime TEXT DEFAULT '',
    file_type TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    duration REAL DEFAULT 0,
    path TEXT NOT NULL,
    hash TEXT DEFAULT '',
    taggable INTEGER DEFAULT 0,
    editable INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    job_id TEXT
);

CREATE TABLE IF NOT EXISTS file_registry (
    id TEXT PRIMARY KEY,
    storage_path TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_type TEXT NOT NULL DEFAULT 'original',
    mime TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    tool_scope TEXT DEFAULT 'karaoke',
    state TEXT DEFAULT 'active',
    source_file_id TEXT,
    job_id TEXT,
    project_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_references (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    ref_type TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(file_id, ref_type, ref_id)
);

CREATE INDEX IF NOT EXISTS idx_transcriptions_created ON transcriptions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transcriptions_source ON transcriptions(source_hash);
CREATE INDEX IF NOT EXISTS idx_transcriptions_deleted ON transcriptions(deleted);
CREATE INDEX IF NOT EXISTS idx_media_filename ON media(filename);
CREATE INDEX IF NOT EXISTS idx_media_job ON media(job_id);
CREATE INDEX IF NOT EXISTS idx_file_registry_path ON file_registry(storage_path);
CREATE INDEX IF NOT EXISTS idx_file_registry_job ON file_registry(job_id);
CREATE INDEX IF NOT EXISTS idx_file_registry_project ON file_registry(project_id);
CREATE INDEX IF NOT EXISTS idx_file_registry_state ON file_registry(state);
CREATE INDEX IF NOT EXISTS idx_file_references_file ON file_references(file_id);
CREATE INDEX IF NOT EXISTS idx_file_references_ref ON file_references(ref_type, ref_id);
"""


def init_db(db_path: Path | None = None) -> None:
    """Initialize database connection and schema."""
    global _DB_PATH, _con
    _DB_PATH = db_path or Path("data/library.sqlite")
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _con = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    _con.row_factory = sqlite3.Row
    _con.executescript(SCHEMA)
    _con.commit()
    info(f"Library DB: {_DB_PATH}")


def get_con() -> sqlite3.Connection:
    if _con is None:
        init_db()
    return _con


def close_db() -> None:
    global _con
    if _con:
        _con.close()
        _con = None


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TranscriptionRecord:
    id: str
    created_at: str
    updated_at: str
    title: str
    source_filename: str
    source_hash: str
    language: str
    backend: str
    duration_sec: float
    bpm: float
    segments_count: int
    has_word_timestamps: bool
    needs_review: int
    avg_confidence: float
    srt_text: str | None
    ass_text: str | None
    segments_json: str | None
    job_id: str | None
    tags: list[str]
    deleted: bool

    def to_dict(self, include_text: bool = False) -> dict[str, Any]:
        d = {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "source_filename": self.source_filename,
            "language": self.language,
            "backend": self.backend,
            "duration_sec": self.duration_sec,
            "bpm": self.bpm,
            "segments_count": self.segments_count,
            "has_word_timestamps": self.has_word_timestamps,
            "needs_review": self.needs_review,
            "avg_confidence": self.avg_confidence,
            "job_id": self.job_id,
            "tags": self.tags,
        }
        if include_text:
            d["srt_text"] = self.srt_text
            d["ass_text"] = self.ass_text
            d["segments_json"] = self.segments_json
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TranscriptionRecord:
        tags = []
        try:
            tags = json.loads(row["tags"]) if row["tags"] else []
        except (json.JSONDecodeError, TypeError):
            pass
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            title=row["title"],
            source_filename=row["source_filename"],
            source_hash=row["source_hash"] or "",
            language=row["language"] or "",
            backend=row["backend"] or "",
            duration_sec=row["duration_sec"] or 0,
            bpm=row["bpm"] or 0,
            segments_count=row["segments_count"] or 0,
            has_word_timestamps=bool(row["has_word_timestamps"]),
            needs_review=row["needs_review"] or 0,
            avg_confidence=row["avg_confidence"] or 0,
            srt_text=row["srt_text"],
            ass_text=row["ass_text"],
            segments_json=row["segments_json"],
            job_id=row["job_id"],
            tags=tags,
            deleted=bool(row["deleted"]),
        )


# ── Source hash for deduplication ─────────────────────────────────────────────

def compute_source_hash(filename: str, backend: str, language: str) -> str:
    """Hash of source + options for deduplication."""
    raw = f"{filename}|{backend}|{language}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_transcription(
    source_filename: str,
    backend: str,
    language: str,
    duration_sec: float = 0,
    bpm: float = 0,
    segments_count: int = 0,
    has_word_timestamps: bool = False,
    needs_review: int = 0,
    avg_confidence: float = 0,
    srt_text: str | None = None,
    ass_text: str | None = None,
    segments_json: str | None = None,
    job_id: str | None = None,
    title: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Insert or update (dedupe by source_hash). Returns record ID."""
    con = get_con()
    now = datetime.now(timezone.utc).isoformat()
    source_hash = compute_source_hash(source_filename, backend, language)

    # Check for existing entry with same source hash
    existing = con.execute(
        "SELECT id FROM transcriptions WHERE source_hash = ? AND deleted = 0",
        (source_hash,)
    ).fetchone()

    if existing:
        # Update existing
        rec_id = existing["id"]
        con.execute("""
            UPDATE transcriptions SET
                updated_at=?, duration_sec=?, bpm=?, segments_count=?,
                has_word_timestamps=?, needs_review=?, avg_confidence=?,
                srt_text=?, ass_text=?, segments_json=?, job_id=?
            WHERE id=?
        """, (now, duration_sec, bpm, segments_count, int(has_word_timestamps),
              needs_review, avg_confidence, srt_text, ass_text, segments_json,
              job_id, rec_id))
        con.commit()
        debug(f"Library: updated {rec_id}")
        return rec_id

    # Insert new
    rec_id = uuid.uuid4().hex[:12]
    display_title = title or Path(source_filename).stem.replace("_", " ").replace("-", " ").title()

    con.execute("""
        INSERT INTO transcriptions (
            id, created_at, updated_at, title, source_filename, source_hash,
            language, backend, duration_sec, bpm, segments_count,
            has_word_timestamps, needs_review, avg_confidence,
            srt_text, ass_text, segments_json, job_id, tags
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (rec_id, now, now, display_title, source_filename, source_hash,
          language, backend, duration_sec, bpm, segments_count,
          int(has_word_timestamps), needs_review, avg_confidence,
          srt_text, ass_text, segments_json, job_id,
          json.dumps(tags or [])))
    con.commit()
    info(f"Library: saved {rec_id} '{display_title}'")
    return rec_id


def list_transcriptions(
    limit: int = 50, offset: int = 0, q: str = ""
) -> tuple[list[TranscriptionRecord], int]:
    """List transcriptions (paginated). Returns (records, total_count)."""
    con = get_con()
    where = "deleted = 0"
    params: list[Any] = []
    if q:
        where += " AND (title LIKE ? OR source_filename LIKE ? OR backend LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])

    total = con.execute(f"SELECT COUNT(*) FROM transcriptions WHERE {where}", params).fetchone()[0]
    rows = con.execute(
        f"SELECT * FROM transcriptions WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()
    return [TranscriptionRecord.from_row(r) for r in rows], total


def get_transcription(rec_id: str) -> TranscriptionRecord | None:
    con = get_con()
    row = con.execute(
        "SELECT * FROM transcriptions WHERE id = ? AND deleted = 0", (rec_id,)
    ).fetchone()
    if row:
        return TranscriptionRecord.from_row(row)
    return None


def delete_transcription(rec_id: str, hard: bool = False) -> bool:
    con = get_con()
    if hard:
        cur = con.execute("DELETE FROM transcriptions WHERE id = ?", (rec_id,))
    else:
        cur = con.execute(
            "UPDATE transcriptions SET deleted = 1, updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), rec_id)
        )
    con.commit()
    return cur.rowcount > 0


def update_transcription(rec_id: str, **kwargs) -> bool:
    """Update specific fields (title, tags, etc.)."""
    con = get_con()
    allowed = {"title", "tags", "bpm", "needs_review"}
    updates = []
    params = []
    for k, v in kwargs.items():
        if k in allowed:
            if k == "tags" and isinstance(v, list):
                v = json.dumps(v)
            updates.append(f"{k} = ?")
            params.append(v)
    if not updates:
        return False
    updates.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.append(rec_id)
    con.execute(f"UPDATE transcriptions SET {', '.join(updates)} WHERE id = ?", params)
    con.commit()
    return True


# ══════════════════════════════════════════════════════════════════════════════
#  MEDIA REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

_AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}
_VIDEO_EXT = {".mp4", ".mov", ".webm", ".avi", ".mkv"}
_SUB_EXT = {".srt", ".ass", ".vtt", ".lrc"}
_LYRICS_EXT = {".txt", ".lrc"}

_MIME_MAP = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
    ".m4a": "audio/mp4", ".aac": "audio/aac", ".ogg": "audio/ogg",
    ".opus": "audio/opus", ".wma": "audio/x-ms-wma",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
    ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
    ".srt": "text/plain", ".ass": "text/plain", ".vtt": "text/vtt",
    ".lrc": "text/plain", ".txt": "text/plain",
}


def _classify_file(filename: str) -> tuple[str, str, bool, bool]:
    """Classify file → (file_type, mime, taggable, editable)."""
    ext = Path(filename).suffix.lower()
    mime = _MIME_MAP.get(ext, "application/octet-stream")

    if ext in _AUDIO_EXT:
        file_type = "audio"
        taggable = ext in {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wma"}
        editable = ext in {".mp3", ".m4a", ".flac", ".ogg", ".opus"}
    elif ext in _VIDEO_EXT:
        file_type = "video"
        taggable = ext in {".mp4", ".mov"}
        editable = ext == ".mp4"
    elif ext in _SUB_EXT:
        file_type = "subtitle"
        taggable = False
        editable = False
    elif ext in _LYRICS_EXT:
        file_type = "lyrics"
        taggable = False
        editable = False
    else:
        file_type = "unknown"
        taggable = False
        editable = False

    return file_type, mime, taggable, editable


def register_media(
    filename: str,
    path: str,
    size: int = 0,
    duration: float = 0,
    file_hash: str = "",
    job_id: str = "",
) -> str:
    """Register an uploaded file in the media registry. Returns media_id."""
    con = get_con()
    now = datetime.now(timezone.utc).isoformat()
    media_id = uuid.uuid4().hex[:12]
    file_type, mime, taggable, editable = _classify_file(filename)

    # Check for existing by same filename+path
    existing = con.execute(
        "SELECT id FROM media WHERE filename = ? AND path = ?",
        (filename, path)
    ).fetchone()
    if existing:
        return existing["id"]

    con.execute("""
        INSERT INTO media (id, filename, original_name, mime, file_type, size,
            duration, path, hash, taggable, editable, created_at, job_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (media_id, filename, filename, mime, file_type, size,
          duration, path, file_hash, int(taggable), int(editable), now, job_id))
    con.commit()
    debug(f"Media registered: {media_id} {filename} ({file_type})")
    return media_id


def get_media(media_id: str) -> dict | None:
    """Get media record by ID."""
    con = get_con()
    row = con.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    if not row:
        return None
    return dict(row)


def get_media_by_filename(filename: str) -> dict | None:
    """Get media record by filename."""
    con = get_con()
    row = con.execute(
        "SELECT * FROM media WHERE filename = ? ORDER BY created_at DESC LIMIT 1",
        (filename,)
    ).fetchone()
    if not row:
        return None
    return dict(row)


def list_media(file_type: str = "", limit: int = 50) -> list[dict]:
    """List media records, optionally filtered by type."""
    con = get_con()
    if file_type:
        rows = con.execute(
            "SELECT * FROM media WHERE file_type = ? ORDER BY created_at DESC LIMIT ?",
            (file_type, limit)
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM media ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_media(media_id: str) -> bool:
    """Delete a media record."""
    con = get_con()
    cur = con.execute("DELETE FROM media WHERE id = ?", (media_id,))
    con.commit()
    return cur.rowcount > 0


# ══════════════════════════════════════════════════════════════════════════════
#  FILE REGISTRY — Central file tracking across Karaoke & Video Editor
# ══════════════════════════════════════════════════════════════════════════════

def register_file(
    storage_path: str,
    original_name: str,
    file_type: str = "original",
    mime: str = "",
    size: int = 0,
    tool_scope: str = "karaoke",
    source_file_id: str = "",
    job_id: str = "",
    project_id: str = "",
) -> str:
    """Register a file in the central file registry. Returns file_id.

    file_type: original | derived | project_asset
    tool_scope: karaoke | editor | both
    """
    con = get_con()
    now = datetime.now(timezone.utc).isoformat()

    # Check for existing entry with same storage path
    existing = con.execute(
        "SELECT id FROM file_registry WHERE storage_path = ? AND state = 'active'",
        (storage_path,)
    ).fetchone()
    if existing:
        return existing["id"]

    file_id = uuid.uuid4().hex[:12]
    con.execute("""
        INSERT INTO file_registry (id, storage_path, original_name, file_type, mime, size,
            tool_scope, state, source_file_id, job_id, project_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
    """, (file_id, storage_path, original_name, file_type, mime, size,
          tool_scope, source_file_id or None, job_id or None, project_id or None, now, now))
    con.commit()
    debug(f"File registered: {file_id} {original_name} ({file_type}/{tool_scope})")
    return file_id


def add_file_reference(file_id: str, ref_type: str, ref_id: str) -> str:
    """Add a reference from a job/project/transcription to a file. Returns ref_id."""
    con = get_con()
    now = datetime.now(timezone.utc).isoformat()

    # Check for existing reference
    existing = con.execute(
        "SELECT id FROM file_references WHERE file_id = ? AND ref_type = ? AND ref_id = ?",
        (file_id, ref_type, ref_id)
    ).fetchone()
    if existing:
        return existing["id"]

    rid = uuid.uuid4().hex[:12]
    con.execute(
        "INSERT INTO file_references (id, file_id, ref_type, ref_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (rid, file_id, ref_type, ref_id, now)
    )
    con.commit()
    debug(f"File ref added: {file_id} ← {ref_type}:{ref_id}")
    return rid


def remove_file_references(ref_type: str, ref_id: str) -> int:
    """Remove all file references for a given ref_type + ref_id. Returns count removed."""
    con = get_con()
    cur = con.execute(
        "DELETE FROM file_references WHERE ref_type = ? AND ref_id = ?",
        (ref_type, ref_id)
    )
    con.commit()
    return cur.rowcount


def get_file_references(file_id: str) -> list[dict]:
    """Get all references pointing to a file."""
    con = get_con()
    rows = con.execute(
        "SELECT * FROM file_references WHERE file_id = ?", (file_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_references_by_ref(ref_type: str, ref_id: str) -> list[dict]:
    """Get all file references for a given ref (e.g. all files for a project)."""
    con = get_con()
    rows = con.execute(
        "SELECT fr.*, reg.storage_path, reg.original_name, reg.file_type, reg.state "
        "FROM file_references fr JOIN file_registry reg ON fr.file_id = reg.id "
        "WHERE fr.ref_type = ? AND fr.ref_id = ?",
        (ref_type, ref_id)
    ).fetchall()
    return [dict(r) for r in rows]


def get_registered_file(file_id: str) -> dict | None:
    """Get a file registry entry by ID."""
    con = get_con()
    row = con.execute("SELECT * FROM file_registry WHERE id = ?", (file_id,)).fetchone()
    return dict(row) if row else None


def get_file_by_path(storage_path: str) -> dict | None:
    """Get a file registry entry by storage path."""
    con = get_con()
    row = con.execute(
        "SELECT * FROM file_registry WHERE storage_path = ? AND state = 'active'",
        (storage_path,)
    ).fetchone()
    return dict(row) if row else None


def list_registered_files(
    tool_scope: str = "",
    file_type: str = "",
    state: str = "active",
    limit: int = 100,
) -> list[dict]:
    """List file registry entries with optional filters."""
    con = get_con()
    where = ["state = ?"]
    params: list[Any] = [state]
    if tool_scope:
        where.append("(tool_scope = ? OR tool_scope = 'both')")
        params.append(tool_scope)
    if file_type:
        where.append("file_type = ?")
        params.append(file_type)
    params.append(limit)
    rows = con.execute(
        f"SELECT * FROM file_registry WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?",
        params
    ).fetchall()
    return [dict(r) for r in rows]


def update_file_state(file_id: str, state: str) -> bool:
    """Update file state (active, deleted, orphaned)."""
    con = get_con()
    now = datetime.now(timezone.utc).isoformat()
    cur = con.execute(
        "UPDATE file_registry SET state = ?, updated_at = ? WHERE id = ?",
        (state, now, file_id)
    )
    con.commit()
    return cur.rowcount > 0


def update_file_scope(file_id: str, tool_scope: str) -> bool:
    """Update tool_scope of a registered file (e.g. karaoke → both)."""
    con = get_con()
    now = datetime.now(timezone.utc).isoformat()
    cur = con.execute(
        "UPDATE file_registry SET tool_scope = ?, updated_at = ? WHERE id = ?",
        (tool_scope, now, file_id)
    )
    con.commit()
    return cur.rowcount > 0


def find_orphaned_files() -> list[dict]:
    """Find files with no remaining references (candidates for cleanup)."""
    con = get_con()
    rows = con.execute("""
        SELECT reg.* FROM file_registry reg
        LEFT JOIN file_references ref ON reg.id = ref.file_id
        WHERE reg.state = 'active' AND ref.id IS NULL
        ORDER BY reg.created_at ASC
    """).fetchall()
    return [dict(r) for r in rows]


def find_files_for_job(job_id: str) -> list[dict]:
    """Find all registered files associated with a job_id."""
    con = get_con()
    rows = con.execute(
        "SELECT * FROM file_registry WHERE job_id = ? AND state = 'active'",
        (job_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def find_files_for_project(project_id: str) -> list[dict]:
    """Find all registered files associated with a project_id."""
    con = get_con()
    rows = con.execute(
        "SELECT * FROM file_registry WHERE project_id = ? AND state = 'active'",
        (project_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def check_file_has_references(file_id: str) -> bool:
    """Check if a file has any remaining references."""
    con = get_con()
    row = con.execute(
        "SELECT COUNT(*) FROM file_references WHERE file_id = ?", (file_id,)
    ).fetchone()
    return row[0] > 0


def delete_registered_file(file_id: str, hard: bool = False) -> bool:
    """Soft-delete or hard-delete a file registry entry."""
    con = get_con()
    if hard:
        con.execute("DELETE FROM file_references WHERE file_id = ?", (file_id,))
        cur = con.execute("DELETE FROM file_registry WHERE id = ?", (file_id,))
    else:
        now = datetime.now(timezone.utc).isoformat()
        cur = con.execute(
            "UPDATE file_registry SET state = 'deleted', updated_at = ? WHERE id = ?",
            (now, file_id)
        )
    con.commit()
    return cur.rowcount > 0
