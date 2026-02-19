"""FastAPI API routes for the karaoke subtitle tool v3."""

from __future__ import annotations

import asyncio
import io
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, UploadFile, BackgroundTasks, Query
from fastapi.responses import FileResponse, StreamingResponse

from src.api.models import (
    TranscribeRequest, RefineRequest, ExportRequest,
    JobInfo, JobStatus, HealthResponse, FileInfo, AudioProbeInfo, JobStats,
    SegmentUpdate, SegmentSplit, SegmentMerge, SegmentReorder,
    TimeShift, SearchReplace, DictionaryEntry, TranslateRequest,
    RetranscribeSegment, GapOverlap,
)
from src.api import tasks

router = APIRouter(prefix="/api", tags=["api"])


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health():
    from src.utils.deps_check import check_ffmpeg, check_all_backends
    ff = check_ffmpeg()
    backends = check_all_backends()
    return HealthResponse(status="ok", version="3.2.0", ffmpeg=ff.available, backends=backends)


@router.get("/presets")
async def list_presets():
    from src.export.themes import PRESETS
    return {n: {"playresx": t.playresx, "playresy": t.playresy, "font": t.font, "fontsize": t.fontsize}
            for n, t in PRESETS.items()}


# ── SSE ───────────────────────────────────────────────────────────────────────

@router.get("/events")
async def sse_events():
    q = tasks.subscribe_sse()
    async def gen():
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type':'heartbeat'})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            tasks.unsubscribe_sse(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    from src.preprocess.ffmpeg_io import SUPPORTED_FORMATS
    suffix = Path(file.filename).suffix.lower()
    allowed = SUPPORTED_FORMATS | {".srt", ".vtt", ".lrc", ".txt"}
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported: {suffix}")
    dest = tasks.UPLOAD_DIR / file.filename
    if dest.exists():
        stem, i = dest.stem, 1
        while dest.exists():
            dest = tasks.UPLOAD_DIR / f"{stem}_{i}{suffix}"; i += 1
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    # Register in media registry
    media_id = ""
    taggable = False
    editable = False
    try:
        from src.db.library import register_media, _classify_file
        file_type, _mime, taggable, editable = _classify_file(dest.name)
        media_id = register_media(
            filename=dest.name, path=str(dest), size=len(content),
        )
    except Exception:
        pass  # non-critical

    return {
        "filename": dest.name, "size": len(content),
        "media_id": media_id, "taggable": taggable, "editable": editable,
    }


@router.get("/files")
async def list_uploaded_files():
    files = []
    if tasks.UPLOAD_DIR.exists():
        for p in sorted(tasks.UPLOAD_DIR.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                st = p.stat()
                files.append(FileInfo(filename=p.name, size=st.st_size,
                    created=datetime.fromtimestamp(st.st_ctime, tz=timezone.utc), type=p.suffix.lstrip(".")))
    return files


@router.delete("/files/{filename}")
async def delete_file(filename: str):
    path = (tasks.UPLOAD_DIR / filename).resolve()
    if not path.is_relative_to(tasks.UPLOAD_DIR.resolve()):
        raise HTTPException(400, "Invalid filename")
    if not path.exists(): raise HTTPException(404, "File not found")
    path.unlink()
    return {"deleted": filename}


@router.get("/files/{filename}/probe", response_model=AudioProbeInfo)
async def probe_audio_file(filename: str):
    from src.preprocess.ffmpeg_io import probe_audio
    path = tasks.UPLOAD_DIR / filename
    if not path.exists(): raise HTTPException(404, "File not found")
    info = probe_audio(path)
    fmt = info.get("format", {})
    streams = info.get("streams", [{}])
    aus = next((s for s in streams if s.get("codec_type") == "audio"), streams[0] if streams else {})
    return AudioProbeInfo(filename=filename, duration=float(fmt.get("duration", 0)),
        format_name=fmt.get("format_name", ""), bit_rate=int(fmt.get("bit_rate", 0)),
        sample_rate=int(aus.get("sample_rate", 0)), channels=int(aus.get("channels", 0)),
        codec=aus.get("codec_name", ""))


# ── Transcribe ────────────────────────────────────────────────────────────────

@router.post("/transcribe", response_model=JobInfo)
async def start_transcription(background_tasks: BackgroundTasks,
    filename: str = Query(...), lyrics_file: str | None = Query(None),
    req: TranscribeRequest = TranscribeRequest()):
    audio_path = tasks.UPLOAD_DIR / filename
    if not audio_path.exists(): raise HTTPException(404, f"Not found: {filename}")
    if lyrics_file:
        lp = tasks.UPLOAD_DIR / lyrics_file
        if not lp.exists() or lp.suffix.lower() not in (".txt", ".lrc"):
            raise HTTPException(400, f"Lyrics file not found or not .txt/.lrc: {lyrics_file}")
        req.lyrics_file = lyrics_file
        if not req.use_lyrics_template:
            req.use_lyrics_template = True  # auto-enable if lyrics file provided
    job = tasks.create_job(filename)
    background_tasks.add_task(tasks.run_transcribe_job, job.job_id, audio_path, req)
    return job


@router.post("/transcribe/batch")
async def batch_transcribe(background_tasks: BackgroundTasks,
    filenames: list[str] = Query(...), req: TranscribeRequest = TranscribeRequest()):
    jobs = []
    for fn in filenames:
        p = tasks.UPLOAD_DIR / fn
        if not p.exists(): continue
        job = tasks.create_job(fn)
        background_tasks.add_task(tasks.run_transcribe_job, job.job_id, p, req)
        jobs.append(job)
    return jobs


@router.post("/transcribe/upload", response_model=JobInfo)
async def transcribe_with_upload(background_tasks: BackgroundTasks,
    file: UploadFile = File(...), backend: str = "voxtral", language: str = "auto",
    generate_ass: bool = True, karaoke_mode: str = "kf", preset: str = "classic"):
    from src.preprocess.ffmpeg_io import SUPPORTED_FORMATS
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_FORMATS: raise HTTPException(400, f"Unsupported: {suffix}")
    dest = tasks.UPLOAD_DIR / file.filename
    with open(dest, "wb") as f: f.write(await file.read())
    req = TranscribeRequest(backend=backend, language=language, generate_ass=generate_ass,
        karaoke_mode=karaoke_mode, preset=preset)
    job = tasks.create_job(file.filename)
    background_tasks.add_task(tasks.run_transcribe_job, job.job_id, dest, req)
    return job


# ── Refine / Export ───────────────────────────────────────────────────────────

@router.post("/refine", response_model=JobInfo)
async def start_refine(background_tasks: BackgroundTasks,
    filename: str = Query(...), req: RefineRequest = RefineRequest()):
    srt_path = tasks.UPLOAD_DIR / filename
    if not srt_path.exists(): raise HTTPException(404, f"Not found: {filename}")
    job = tasks.create_job(filename)
    background_tasks.add_task(tasks.run_refine_job, job.job_id, srt_path, req)
    return job


@router.post("/export", response_model=JobInfo)
async def start_export(background_tasks: BackgroundTasks,
    filename: str = Query(...), req: ExportRequest = ExportRequest()):
    srt_path = tasks.UPLOAD_DIR / filename
    if not srt_path.exists(): raise HTTPException(404, f"Not found: {filename}")
    job = tasks.create_job(filename)
    background_tasks.add_task(tasks.run_export_job, job.job_id, srt_path, req)
    return job


# ── Jobs ──────────────────────────────────────────────────────────────────────

@router.get("/jobs", response_model=list[JobInfo])
async def list_jobs():
    jobs = list(tasks.get_jobs().values())
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return jobs

@router.get("/jobs/{job_id}", response_model=JobInfo)
async def get_job(job_id: str):
    job = tasks.get_job(job_id)
    if not job: raise HTTPException(404, "Job not found")
    return job

@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    job = tasks.get_job(job_id)
    if not job: raise HTTPException(404, "Job not found")
    d = tasks.OUTPUT_DIR / job_id
    if d.exists(): shutil.rmtree(d)
    del tasks._jobs[job_id]
    return {"deleted": job_id}


# ── Downloads ─────────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/files")
async def list_job_files(job_id: str):
    """List available files in a job output directory (works without in-memory job)."""
    job_dir = tasks.OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job directory not found")
    files = {}
    for f in sorted(job_dir.iterdir()):
        if f.is_file() and f.name not in ("segments.json", "waveform.json", ".chat_history.sqlite"):
            files[f.suffix.lstrip(".")] = f.name
    return {"job_id": job_id, "files": files}


@router.get("/jobs/{job_id}/download/{filename}")
async def download_result(job_id: str, filename: str):
    job_dir = (tasks.OUTPUT_DIR / job_id).resolve()
    if not job_dir.is_relative_to(tasks.OUTPUT_DIR.resolve()):
        raise HTTPException(400, "Invalid job_id")
    fp = (job_dir / filename).resolve()
    if not fp.is_relative_to(job_dir):
        raise HTTPException(400, "Invalid filename")
    if not fp.exists(): raise HTTPException(404, "File not found")
    mt = {".srt":"text/plain",".ass":"text/plain",".vtt":"text/vtt",".lrc":"text/plain",
          ".txt":"text/plain",".json":"application/json",".csv":"text/csv",".mp4":"video/mp4",
          ".mp3":"audio/mpeg",".wav":"audio/wav",".flac":"audio/flac",".m4a":"audio/mp4",
          ".ogg":"audio/ogg"}.get(fp.suffix,"application/octet-stream")
    return FileResponse(fp, filename=filename, media_type=mt)


@router.get("/jobs/{job_id}/download-zip")
async def download_zip(job_id: str):
    """Download all job outputs as ZIP."""
    job_dir = tasks.OUTPUT_DIR / job_id
    if not job_dir.exists(): raise HTTPException(404, "Job not found")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in job_dir.iterdir():
            if f.is_file() and f.name not in ("segments.json", "waveform.json"):
                zf.write(f, f.name)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={job_id}_output.zip"})


@router.get("/jobs/{job_id}/content/{filename}")
async def get_file_content(job_id: str, filename: str):
    job_dir = (tasks.OUTPUT_DIR / job_id).resolve()
    if not job_dir.is_relative_to(tasks.OUTPUT_DIR.resolve()):
        raise HTTPException(400, "Invalid job_id")
    fp = (job_dir / filename).resolve()
    if not fp.is_relative_to(job_dir):
        raise HTTPException(400, "Invalid filename")
    if not fp.exists(): raise HTTPException(404, "File not found")
    if fp.suffix in (".mp4",".mp3",".wav"): raise HTTPException(400, "Binary file")
    return {"content": fp.read_text(encoding="utf-8"), "filename": filename}


# ── Segments CRUD ─────────────────────────────────────────────────────────────

def _load_segs(job_id: str) -> tuple[Path, list[dict]]:
    p = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not p.exists(): raise HTTPException(404, "Segments not found")
    return p, json.loads(p.read_text(encoding="utf-8"))

def _save_segs(p: Path, data: list[dict], job_id: str):
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _sync_srt(job_id, data)


@router.get("/jobs/{job_id}/segments")
async def get_segments(job_id: str):
    _, data = _load_segs(job_id)
    return data


@router.put("/jobs/{job_id}/segments")
async def update_segment(job_id: str, update: SegmentUpdate):
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    idx = update.index
    if idx < 0 or idx >= len(data): raise HTTPException(400, f"Index {idx} out of range")
    if update.text is not None: data[idx]["text"] = update.text
    if update.start is not None: data[idx]["start"] = update.start
    if update.end is not None: data[idx]["end"] = update.end
    if update.speaker is not None: data[idx]["speaker"] = update.speaker
    if update.pinned is not None: data[idx]["pinned"] = update.pinned
    _save_segs(p, data, job_id)
    return {"updated": idx}


@router.post("/jobs/{job_id}/segments/split")
async def split_segment(job_id: str, req: SegmentSplit):
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    idx = req.index
    if idx < 0 or idx >= len(data): raise HTTPException(400, "Index out of range")
    seg = data[idx]
    if req.split_at <= seg["start"] or req.split_at >= seg["end"]:
        raise HTTPException(400, "split_at must be between start and end")
    text = seg["text"]
    # try to split at word boundary near midpoint
    words = text.split()
    mid_word = len(words) // 2
    text_a = " ".join(words[:mid_word]) if mid_word > 0 else text[:len(text)//2]
    text_b = " ".join(words[mid_word:]) if mid_word > 0 else text[len(text)//2:]
    seg_a = {**seg, "end": req.split_at, "text": text_a, "words": [], "has_word_timestamps": False}
    seg_b = {**seg, "start": req.split_at, "text": text_b, "words": [], "has_word_timestamps": False}
    data[idx:idx+1] = [seg_a, seg_b]
    _save_segs(p, data, job_id)
    return {"split_at": idx, "new_count": len(data)}


@router.post("/jobs/{job_id}/segments/merge")
async def merge_segments(job_id: str, req: SegmentMerge):
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    a, b = min(req.index_a, req.index_b), max(req.index_a, req.index_b)
    if a < 0 or b >= len(data): raise HTTPException(400, "Index out of range")
    merged = {"start": data[a]["start"], "end": data[b]["end"],
              "text": data[a]["text"] + " " + data[b]["text"],
              "confidence": min(data[a].get("confidence",1), data[b].get("confidence",1)),
              "has_word_timestamps": False, "words": []}
    data[a:b+1] = [merged]
    _save_segs(p, data, job_id)
    return {"merged": [a,b], "new_count": len(data)}


@router.post("/jobs/{job_id}/segments/reorder")
async def reorder_segment(job_id: str, req: SegmentReorder):
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    if req.old_index < 0 or req.old_index >= len(data): raise HTTPException(400, "bad index")
    if req.new_index < 0 or req.new_index >= len(data): raise HTTPException(400, "bad index")
    item = data.pop(req.old_index)
    data.insert(req.new_index, item)
    _save_segs(p, data, job_id)
    return {"moved": req.old_index, "to": req.new_index}


@router.put("/jobs/{job_id}/segments/bulk")
async def bulk_replace_segments(job_id: str, segments: list[dict] = Body(...)):
    """Replace the entire segments array (for add/delete/reorder operations)."""
    tasks.push_undo(job_id)
    p, _ = _load_segs(job_id)
    _save_segs(p, segments, job_id)
    return {"count": len(segments)}


@router.post("/jobs/{job_id}/segments/time-shift")
async def time_shift_segments(job_id: str, req: TimeShift):
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    offset = req.offset_ms / 1000.0
    s_i = req.range_start or 0
    e_i = req.range_end if req.range_end is not None else len(data) - 1
    shifted = 0
    for i in range(max(0, s_i), min(len(data), e_i + 1)):
        data[i]["start"] = max(0, data[i]["start"] + offset)
        data[i]["end"] = max(0, data[i]["end"] + offset)
        for w in data[i].get("words", []):
            w["start"] = max(0, w["start"] + offset)
            w["end"] = max(0, w["end"] + offset)
        shifted += 1
    _save_segs(p, data, job_id)
    return {"shifted": shifted, "offset_ms": req.offset_ms}


@router.post("/jobs/{job_id}/segments/search-replace")
async def search_replace_segments(job_id: str, req: SearchReplace):
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    count = 0
    for seg in data:
        orig = seg["text"]
        if req.regex:
            flags = 0 if req.case_sensitive else re.IGNORECASE
            seg["text"] = re.sub(req.search, req.replace, seg["text"], flags=flags)
        elif req.case_sensitive:
            seg["text"] = seg["text"].replace(req.search, req.replace)
        else:
            seg["text"] = re.sub(re.escape(req.search), req.replace, seg["text"], flags=re.IGNORECASE)
        if seg["text"] != orig: count += 1
    _save_segs(p, data, job_id)
    return {"replaced_in_segments": count}


# ── Dictionary ────────────────────────────────────────────────────────────────

@router.get("/dictionary")
async def get_dictionary():
    """Get custom word replacements."""
    path = Path("custom_words.txt")
    if not path.exists(): return {"entries": []}
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if "=" in line:
            wrong, correct = line.split("=", 1)
            entries.append({"wrong": wrong.strip(), "correct": correct.strip()})
    return {"entries": entries}


@router.put("/dictionary")
async def update_dictionary(entries: list[DictionaryEntry]):
    """Replace the entire custom dictionary."""
    path = Path("custom_words.txt")
    lines = ["# Custom word replacements: wrong=correct"]
    for e in entries:
        lines.append(f"{e.wrong}={e.correct}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"count": len(entries)}


@router.post("/jobs/{job_id}/apply-dictionary")
async def apply_dictionary(job_id: str):
    """Apply custom_words.txt replacements to segments."""
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    path = Path("custom_words.txt")
    if not path.exists(): return {"applied": 0}
    replacements = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if "=" in line:
            w, c = line.split("=", 1)
            replacements[w.strip()] = c.strip()
    count = 0
    for seg in data:
        orig = seg["text"]
        for w, c in replacements.items():
            seg["text"] = re.sub(r'\b' + re.escape(w) + r'\b', c, seg["text"], flags=re.IGNORECASE)
        if seg["text"] != orig: count += 1
    _save_segs(p, data, job_id)
    return {"applied": count}


# ── Gap/Overlap Detection ────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/gaps-overlaps", response_model=list[GapOverlap])
async def detect_gaps_overlaps(job_id: str, min_gap_ms: float = 100, min_overlap_ms: float = 0):
    _, data = _load_segs(job_id)
    issues: list[GapOverlap] = []
    for i in range(len(data) - 1):
        end_a = data[i]["end"]
        start_b = data[i+1]["start"]
        diff_ms = (start_b - end_a) * 1000
        if diff_ms > min_gap_ms:
            issues.append(GapOverlap(type="gap", index_a=i, index_b=i+1,
                start=end_a, end=start_b, duration_ms=diff_ms))
        elif diff_ms < -min_overlap_ms:
            issues.append(GapOverlap(type="overlap", index_a=i, index_b=i+1,
                start=start_b, end=end_a, duration_ms=abs(diff_ms)))
    return issues


@router.post("/jobs/{job_id}/fix-gaps")
async def fix_gaps(job_id: str, strategy: str = Query("extend", pattern="^(extend|shrink|split)$")):
    """Auto-fix gaps: extend=extend previous, shrink=shrink gap, split=split difference."""
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    fixed = 0
    for i in range(len(data) - 1):
        end_a = data[i]["end"]
        start_b = data[i+1]["start"]
        gap = start_b - end_a
        if gap > 0.1:  # >100ms gap
            if strategy == "extend":
                data[i]["end"] = start_b
            elif strategy == "shrink":
                data[i+1]["start"] = end_a
            elif strategy == "split":
                mid = end_a + gap / 2
                data[i]["end"] = mid
                data[i+1]["start"] = mid
            fixed += 1
        elif gap < -0.01:  # overlap
            mid = (end_a + start_b) / 2
            data[i]["end"] = mid
            data[i+1]["start"] = mid
            fixed += 1
    _save_segs(p, data, job_id)
    return {"fixed": fixed, "strategy": strategy}


# ── Speaker Labels ────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/speakers")
async def get_speakers(job_id: str):
    _, data = _load_segs(job_id)
    speakers = set()
    for seg in data:
        sp = seg.get("speaker")
        if sp: speakers.add(sp)
    return {"speakers": sorted(speakers)}


@router.post("/jobs/{job_id}/speakers/assign")
async def assign_speaker(job_id: str, indices: list[int] = Query(...), speaker: str = Query(...)):
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    for idx in indices:
        if 0 <= idx < len(data):
            data[idx]["speaker"] = speaker
    _save_segs(p, data, job_id)
    return {"assigned": len(indices), "speaker": speaker}


# ── Pin / Bookmark Segments ───────────────────────────────────────────────────

@router.post("/jobs/{job_id}/segments/toggle-pin")
async def toggle_pin(job_id: str, index: int = Query(...)):
    tasks.push_undo(job_id)
    p, data = _load_segs(job_id)
    if index < 0 or index >= len(data): raise HTTPException(400, "bad index")
    data[index]["pinned"] = not data[index].get("pinned", False)
    _save_segs(p, data, job_id)
    return {"index": index, "pinned": data[index]["pinned"]}


# ── Translate ─────────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/translate")
async def translate_segments(job_id: str, req: TranslateRequest):
    """Translate all segments — creates a parallel segments_<lang>.json."""
    _, data = _load_segs(job_id)
    job_output = tasks.OUTPUT_DIR / job_id
    # simple approach using available translation APIs
    translated = []
    for seg in data:
        t = dict(seg)
        t["original_text"] = seg["text"]
        # mark for translation (actual translation would need an API)
        t["text"] = f"[{req.target_language.upper()}] {seg['text']}"
        translated.append(t)
    out_path = job_output / f"segments_{req.target_language}.json"
    out_path.write_text(json.dumps(translated, indent=2, ensure_ascii=False))
    return {"translated": len(translated), "file": out_path.name, "target": req.target_language}


# ── Project Export / Import ───────────────────────────────────────────────────

@router.get("/jobs/{job_id}/project-export")
async def export_project(job_id: str):
    """Export full project state as JSON for backup/sharing."""
    job_dir = tasks.OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job directory not found")
    job = tasks.get_job(job_id)
    project = {
        "version": "3.0", "exported_at": datetime.now(timezone.utc).isoformat(),
        "job": job.model_dump(mode="json") if job else {"job_id": job_id},
        "segments": [], "dictionary": [],
    }
    seg_path = job_dir / "segments.json"
    if seg_path.exists():
        project["segments"] = json.loads(seg_path.read_text())
    dict_path = Path("custom_words.txt")
    if dict_path.exists():
        project["dictionary"] = dict_path.read_text()
    return project


@router.get("/jobs/{job_id}/download-zip")
async def download_job_zip(job_id: str):
    """Download entire job output folder as a ZIP file."""
    job_dir = tasks.OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job directory not found")
    files = [f for f in job_dir.iterdir() if f.is_file()]
    if not files:
        raise HTTPException(404, "No files in job directory")
    # Determine a human-readable name from the first SRT/ASS stem or fallback to job_id
    stem = job_id[:12]
    for f in files:
        if f.suffix in (".srt", ".ass"):
            stem = f.stem
            break
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(files, key=lambda x: x.name):
            zf.write(f, f.name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{stem}_all.zip"'},
    )


@router.post("/jobs/{job_id}/project-import")
async def import_project(job_id: str, file: UploadFile = File(...)):
    """Import project state from JSON."""
    content = await file.read()
    project = json.loads(content)
    job_dir = tasks.OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    if "segments" in project:
        tasks.push_undo(job_id)
        seg_path = job_dir / "segments.json"
        seg_path.write_text(json.dumps(project["segments"], indent=2, ensure_ascii=False))
    return {"imported": True, "segments": len(project.get("segments", []))}


# ── Undo / Redo ───────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/undo")
async def undo_action(job_id: str):
    if tasks.undo(job_id): return {"status": "undone"}
    raise HTTPException(400, "Nothing to undo")

@router.post("/jobs/{job_id}/redo")
async def redo_action(job_id: str):
    if tasks.redo(job_id): return {"status": "redone"}
    raise HTTPException(400, "Nothing to redo")


# ── Regenerate / Stats ────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/regenerate-ass")
async def regenerate_ass(job_id: str, req: ExportRequest = ExportRequest()):
    p, data = _load_segs(job_id)
    from src.transcription.base import TranscriptSegment
    from src.refine.alignment import ensure_word_timestamps
    from src.export.ass_writer import write_ass
    from src.export.vtt_writer import write_vtt
    from src.export.lrc_writer import write_lrc
    from src.export.srt_writer import write_srt
    from src.export.txt_writer import write_txt
    segments = [TranscriptSegment.from_dict(s) for s in data]
    if req.approx_karaoke: segments = ensure_word_timestamps(segments)
    job_output = tasks.OUTPUT_DIR / job_id
    stem = "output"
    for f in job_output.glob("*.srt"): stem = f.stem; break
    generated = []
    for fmt in req.formats:
        v = fmt.value
        if v == "srt": write_srt(segments, job_output/f"{stem}.srt"); generated.append(v)
        elif v == "ass": write_ass(segments, job_output/f"{stem}.ass", preset=req.preset.value,
            karaoke_mode=req.karaoke_mode.value, highlight_color=req.highlight_color,
            safe_area=req.safe_area); generated.append(v)
        elif v == "vtt": write_vtt(segments, job_output/f"{stem}.vtt"); generated.append(v)
        elif v == "lrc": write_lrc(segments, job_output/f"{stem}.lrc", title=stem); generated.append(v)
        elif v == "txt": write_txt(segments, job_output/f"{stem}.txt"); generated.append(v)
    return {"regenerated": generated}


@router.get("/jobs/{job_id}/stats", response_model=JobStats)
async def get_job_stats(job_id: str):
    _, data = _load_segs(job_id)
    if not data: return JobStats()
    total_words = total_chars = segs_w = needs_r = gaps = overlaps = pinned = 0
    cps_vals, confs = [], []
    for seg in data:
        text = seg.get("text","")
        dur = seg.get("end",0) - seg.get("start",0)
        total_words += len(text.split())
        total_chars += len(text)
        if dur > 0: cps_vals.append(len(text)/dur)
        c = seg.get("confidence",1.0); confs.append(c)
        if seg.get("has_word_timestamps"): segs_w += 1
        if c < 0.6: needs_r += 1
        if seg.get("pinned"): pinned += 1
    for i in range(len(data)-1):
        diff = data[i+1]["start"] - data[i]["end"]
        if diff > 0.1: gaps += 1
        elif diff < -0.01: overlaps += 1
    duration = data[-1]["end"] if data else 0
    cps_dist = []
    if cps_vals:
        for bs in range(0, int(max(cps_vals))+5, 5):
            cnt = sum(1 for c in cps_vals if bs <= c < bs+5)
            if cnt: cps_dist.append({"cps_range": f"{bs}-{bs+5}", "count": cnt})
    # Load processing info from report if available
    bpm_val = 0.0
    proc_info = {}
    for f in (tasks.OUTPUT_DIR / job_id).glob("*.report.json"):
        try:
            report = json.loads(f.read_text())
            proc = report.get("processing", {})
            bpm_val = proc.get("bpm", 0.0)
            proc_info = proc
        except Exception:
            pass
        break

    return JobStats(total_segments=len(data), total_words=total_words, total_chars=total_chars,
        duration_sec=duration, avg_cps=sum(cps_vals)/len(cps_vals) if cps_vals else 0,
        max_cps=max(cps_vals) if cps_vals else 0, min_cps=min(cps_vals) if cps_vals else 0,
        cps_distribution=cps_dist,
        avg_segment_duration=sum(s["end"]-s["start"] for s in data)/len(data),
        avg_confidence=sum(confs)/len(confs) if confs else 0,
        segments_with_words=segs_w, segments_needing_review=needs_r,
        gaps=gaps, overlaps=overlaps, pinned=pinned,
        bpm=bpm_val, processing=proc_info)


@router.get("/jobs/{job_id}/waveform")
async def get_waveform(job_id: str):
    wf = tasks.OUTPUT_DIR / job_id / "waveform.json"
    if not wf.exists(): raise HTTPException(404, "Waveform not available")
    return json.loads(wf.read_text())

@router.get("/jobs/{job_id}/report")
async def get_report(job_id: str):
    for f in (tasks.OUTPUT_DIR / job_id).glob("*.report.json"):
        return json.loads(f.read_text())
    raise HTTPException(404, "Report not found")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sync_srt(job_id: str, data: list[dict]) -> None:
    from src.transcription.base import TranscriptSegment
    from src.export.srt_writer import write_srt
    segs = [TranscriptSegment.from_dict(s) for s in data]
    job_dir = tasks.OUTPUT_DIR / job_id
    for f in job_dir.glob("*.srt"):
        write_srt(segs, f); break
    # Also sync ASS if it exists on disk
    for f in job_dir.glob("*.ass"):
        try:
            from src.refine.alignment import ensure_word_timestamps
            from src.export.ass_writer import write_ass
            segs_wt = ensure_word_timestamps(segs)
            # Read karaoke_mode + preset from report.json if available
            k_mode, k_preset = "kf", "classic"
            for rp in job_dir.glob("*.report.json"):
                try:
                    rd = json.loads(rp.read_text(encoding="utf-8"))
                    k_mode = rd.get("karaoke_mode", "kf")
                    k_preset = rd.get("preset", "classic")
                except Exception:
                    pass
                break
            write_ass(segs_wt, f, karaoke_mode=k_mode, preset=k_preset)
        except Exception:
            pass  # non-critical: ASS regeneration may fail without word timestamps
        break


# ── Rhyme Scheme Detection ────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/rhyme")
async def get_rhyme_scheme(job_id: str, window: int = 8, threshold: float = 0.6):
    """Analyze rhyme patterns in transcribed segments."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    data = json.loads(seg_path.read_text())
    lines = [s["text"] for s in data if s.get("text", "").strip()]
    from src.refine.rhyme import detect_rhyme_scheme
    scheme = detect_rhyme_scheme(lines, threshold=threshold, window=window)
    return scheme.to_dict()


# ── Auto CPS Fixer ────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/auto-fix-cps")
async def auto_fix_cps_route(job_id: str, max_cps: float = 22.0):
    """Auto-fix all segments exceeding CPS limit."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    tasks.push_undo(job_id)
    data = json.loads(seg_path.read_text())
    from src.transcription.base import TranscriptSegment
    from src.refine.cps_fixer import auto_fix_cps
    segments = [TranscriptSegment.from_dict(s) for s in data]
    fixed, result = auto_fix_cps(segments, max_cps=max_cps)
    fixed_data = [s.to_dict() for s in fixed]
    seg_path.write_text(json.dumps(fixed_data, indent=2, ensure_ascii=False), encoding="utf-8")
    _sync_srt(job_id, fixed_data)
    return result.to_dict()


# ── Karaoke HTML Export ───────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/karaoke-html")
async def export_karaoke_html_route(
    job_id: str,
    theme: str = "dark",
    embed_audio: bool = False,
    font_size: int = 32,
    highlight_color: str = "%2300e5a0",  # URL-encoded #00e5a0
):
    """Export standalone karaoke HTML player."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    data = json.loads(seg_path.read_text())
    from src.transcription.base import TranscriptSegment
    from src.export.karaoke_html import export_karaoke_html
    segments = [TranscriptSegment.from_dict(s) for s in data]

    job = tasks.get_job(job_id)
    title = job.filename.rsplit(".", 1)[0] if job else "Karaoke"
    audio_path = None
    if job:
        ap = tasks.OUTPUT_DIR / job_id / job.filename
        if ap.exists():
            audio_path = ap
        else:
            ap2 = tasks.UPLOAD_DIR / job.filename
            if ap2.exists():
                audio_path = ap2

    color = highlight_color.replace("%23", "#")
    out = tasks.OUTPUT_DIR / job_id / f"{title}_karaoke.html"
    export_karaoke_html(
        segments, out, title=title, audio_path=audio_path,
        embed_audio=embed_audio, theme=theme, font_size=font_size,
        highlight_color=color,
    )
    return FileResponse(out, filename=out.name, media_type="text/html")


# ── Export Presets ────────────────────────────────────────────────────────────

EXPORT_PRESETS = {
    "youtube": {
        "name": "YouTube SRT",
        "desc": "Standard SRT für YouTube-Upload",
        "formats": ["srt"], "max_chars": 42, "max_lines": 2, "cps": 20,
    },
    "tiktok": {
        "name": "TikTok/Reels ASS",
        "desc": "Vertikale Untertitel, groß, fett, zentral",
        "formats": ["ass", "srt"], "max_chars": 30, "max_lines": 1, "cps": 18,
        "ass_preset": "bold_center", "font_size": 28,
    },
    "spotify": {
        "name": "Spotify LRC",
        "desc": "Synced Lyrics im LRC-Format",
        "formats": ["lrc", "txt"], "max_chars": 80, "max_lines": 1,
    },
    "karaoke": {
        "name": "Karaoke Full",
        "desc": "ASS mit Wort-Highlighting + HTML Player",
        "formats": ["ass", "srt", "lrc"], "karaoke": True,
        "ass_preset": "karaoke_glow",
    },
    "translation": {
        "name": "Übersetzung",
        "desc": "SRT + TXT für Übersetzer",
        "formats": ["srt", "txt", "vtt"], "max_chars": 42, "max_lines": 2,
    },
}

@router.get("/export-presets")
async def get_export_presets():
    """List available export presets."""
    return {k: {"name": v["name"], "desc": v["desc"]} for k, v in EXPORT_PRESETS.items()}

@router.post("/jobs/{job_id}/export-preset/{preset_name}")
async def apply_export_preset(job_id: str, preset_name: str):
    """Apply an export preset and re-export all formats."""
    if preset_name not in EXPORT_PRESETS:
        raise HTTPException(404, f"Unknown preset: {preset_name}")
    preset = EXPORT_PRESETS[preset_name]

    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    data = json.loads(seg_path.read_text())
    from src.transcription.base import TranscriptSegment
    segments = [TranscriptSegment.from_dict(s) for s in data]

    job = tasks.get_job(job_id)
    stem = job.filename.rsplit(".", 1)[0] if job else job_id
    job_output = tasks.OUTPUT_DIR / job_id
    exported = []

    # Apply CPS limit if specified
    if "cps" in preset:
        from src.refine.cps_fixer import auto_fix_cps
        segments, _ = auto_fix_cps(segments, max_cps=preset["cps"])

    for fmt in preset.get("formats", []):
        if fmt == "srt":
            from src.export.srt_writer import write_srt
            p = job_output / f"{stem}.srt"
            write_srt(segments, p); exported.append(p.name)
        elif fmt == "ass":
            from src.export.ass_writer import write_ass
            p = job_output / f"{stem}.ass"
            kw = {}
            if "ass_preset" in preset: kw["preset"] = preset["ass_preset"]
            write_ass(segments, p, **kw); exported.append(p.name)
        elif fmt == "vtt":
            from src.export.vtt_writer import write_vtt
            p = job_output / f"{stem}.vtt"
            write_vtt(segments, p); exported.append(p.name)
        elif fmt == "lrc":
            from src.export.lrc_writer import write_lrc
            p = job_output / f"{stem}.lrc"
            write_lrc(segments, p, title=stem); exported.append(p.name)
        elif fmt == "txt":
            from src.export.txt_writer import write_txt
            p = job_output / f"{stem}.txt"
            write_txt(segments, p); exported.append(p.name)

    # Karaoke HTML if requested
    if preset.get("karaoke"):
        from src.export.karaoke_html import export_karaoke_html
        audio_path = job_output / job.filename if job else None
        if audio_path and not audio_path.exists():
            audio_path = tasks.UPLOAD_DIR / job.filename if job else None
        p = export_karaoke_html(segments, job_output / f"{stem}_karaoke.html",
                                 title=stem, audio_path=audio_path)
        exported.append(p.name)

    return {"preset": preset_name, "name": preset["name"], "exported": exported}


# ── Gap Filler ────────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/fill-gaps")
async def fill_gaps_route(job_id: str, min_gap: float = 2.0, fill_text: str = "♪"):
    """Fill significant timeline gaps with pause segments."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    tasks.push_undo(job_id)
    data = json.loads(seg_path.read_text())
    from src.transcription.base import TranscriptSegment
    from src.refine.gap_filler import fill_gaps
    segments = [TranscriptSegment.from_dict(s) for s in data]
    fixed, result = fill_gaps(segments, min_gap=min_gap, fill_text=fill_text)
    fixed_data = [s.to_dict() for s in fixed]
    seg_path.write_text(json.dumps(fixed_data, indent=2, ensure_ascii=False), encoding="utf-8")
    _sync_srt(job_id, fixed_data)
    return result.to_dict()


@router.post("/jobs/{job_id}/redistribute-timing")
async def redistribute_timing_route(job_id: str, duration: float | None = None):
    """Redistribute segment timing evenly (fixes broken timestamps)."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    tasks.push_undo(job_id)
    data = json.loads(seg_path.read_text())
    from src.transcription.base import TranscriptSegment
    from src.refine.gap_filler import redistribute_timing
    segments = [TranscriptSegment.from_dict(s) for s in data]
    fixed = redistribute_timing(segments, total_duration=duration)
    fixed_data = [s.to_dict() for s in fixed]
    seg_path.write_text(json.dumps(fixed_data, indent=2, ensure_ascii=False), encoding="utf-8")
    _sync_srt(job_id, fixed_data)
    return {"count": len(fixed), "duration": fixed[-1].end if fixed else 0}


# ── Text Statistics ───────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/text-stats")
async def get_text_stats(job_id: str):
    """Analyze vocabulary richness, word frequency, flow score."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    data = json.loads(seg_path.read_text())
    lines = [s["text"] for s in data if s.get("text", "").strip()]
    from src.refine.text_stats import analyze_text_stats
    stats = analyze_text_stats(lines)
    return stats.to_dict()


# ── Batch Segment Operations ─────────────────────────────────────────────────

@router.post("/jobs/{job_id}/segments/remove-short")
async def remove_short_segments(job_id: str, min_chars: int = 2, min_duration: float = 0.3):
    """Remove very short or empty segments."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    tasks.push_undo(job_id)
    data = json.loads(seg_path.read_text())
    before = len(data)
    data = [s for s in data
            if len(s.get("text", "").strip()) >= min_chars
            and (s.get("end", 0) - s.get("start", 0)) >= min_duration]
    seg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _sync_srt(job_id, data)
    return {"removed": before - len(data), "remaining": len(data)}


@router.post("/jobs/{job_id}/segments/normalize-text")
async def normalize_text_route(job_id: str, fix_case: bool = True, fix_punctuation: bool = True):
    """Normalize segment text: fix casing, punctuation, whitespace."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    tasks.push_undo(job_id)
    data = json.loads(seg_path.read_text())
    changed = 0
    for s in data:
        original = s.get("text", "")
        text = original.strip()
        text = re.sub(r"\s+", " ", text)  # collapse whitespace
        if fix_punctuation:
            text = re.sub(r"\s+([,.:;!?])", r"\1", text)  # remove space before punctuation
            text = re.sub(r"([,.:;!?])(\w)", r"\1 \2", text)  # ensure space after punctuation
        if fix_case and text and text[0].islower():
            text = text[0].upper() + text[1:]
        if text != original:
            s["text"] = text
            changed += 1
    seg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _sync_srt(job_id, data)
    return {"changed": changed, "total": len(data)}


# ── Song Structure Detection ─────────────────────────────────────────────────

@router.get("/jobs/{job_id}/structure")
async def get_song_structure(job_id: str, gap_threshold: float = 3.0):
    """Auto-detect song structure (Verse/Chorus/Bridge)."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    data = json.loads(seg_path.read_text())
    from src.transcription.base import TranscriptSegment
    from src.refine.structure import detect_song_structure
    segments = [TranscriptSegment.from_dict(s) for s in data]
    structure = detect_song_structure(segments, gap_threshold=gap_threshold)
    return structure.to_dict()


# ── Video Editor Marker Export ────────────────────────────────────────────────

@router.post("/jobs/{job_id}/export-markers/{format}")
async def export_markers(job_id: str, format: str):
    """Export segment markers for video editors.

    Formats: resolve, premiere, youtube, ffmpeg, json
    """
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    data = json.loads(seg_path.read_text())
    from src.transcription.base import TranscriptSegment
    segments = [TranscriptSegment.from_dict(s) for s in data]

    job = tasks.get_job(job_id)
    stem = job.filename.rsplit(".", 1)[0] if job else job_id
    job_output = tasks.OUTPUT_DIR / job_id

    from src.export.video_markers import (
        export_resolve_markers, export_premiere_markers,
        export_youtube_chapters, export_ffmpeg_chapters,
        export_json_markers,
    )

    if format == "resolve":
        p = export_resolve_markers(segments, job_output / f"{stem}_markers")
    elif format == "premiere":
        p = export_premiere_markers(segments, job_output / f"{stem}_markers")
    elif format == "youtube":
        from src.refine.structure import detect_song_structure
        structure = detect_song_structure(segments)
        sections = [s.to_dict() for s in structure.sections]
        p = export_youtube_chapters(sections, job_output / f"{stem}")
    elif format == "ffmpeg":
        from src.refine.structure import detect_song_structure
        structure = detect_song_structure(segments)
        sections = [s.to_dict() for s in structure.sections]
        p = export_ffmpeg_chapters(sections, job_output / f"{stem}")
    elif format == "json":
        p = export_json_markers(segments, job_output / f"{stem}", include_words=True)
    else:
        raise HTTPException(400, f"Unknown format: {format}. Use: resolve, premiere, youtube, ffmpeg, json")

    return FileResponse(p, filename=p.name)


# ── Clipboard Lyrics Import ──────────────────────────────────────────────────

@router.post("/jobs/{job_id}/paste-lyrics")
async def paste_lyrics_align(job_id: str, text: str = ""):
    """Paste lyrics text and align to existing segments.

    Replaces segment text with pasted lyrics while keeping timing.
    """
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    if not text.strip():
        raise HTTPException(400, "No lyrics text provided")

    tasks.push_undo(job_id)
    data = json.loads(seg_path.read_text())

    # Parse pasted lyrics into lines
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    # Skip section markers
    lines = [l for l in lines if not re.match(r"^\[.*\]$", l) and not re.match(r"^\(.*\)$", l)]

    if not lines:
        raise HTTPException(400, "No valid lyrics lines found")

    # Map lyrics lines to segments
    replaced = 0
    for i, seg in enumerate(data):
        if i < len(lines):
            seg["text"] = lines[i]
            replaced += 1

    # If more lyrics than segments, append new segments with estimated timing
    if len(lines) > len(data) and data:
        last_end = data[-1]["end"]
        avg_dur = sum(s["end"] - s["start"] for s in data) / len(data)
        for i in range(len(data), len(lines)):
            start = last_end + 0.05
            end = start + avg_dur
            data.append({
                "start": round(start, 3), "end": round(end, 3),
                "text": lines[i], "confidence": 0.3,
                "has_word_timestamps": False, "words": [],
            })
            last_end = end
            replaced += 1

    seg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _sync_srt(job_id, data)
    return {"replaced": replaced, "lyrics_lines": len(lines), "segments": len(data)}


# ── Duplicate / Chorus Finder ─────────────────────────────────────────────────

@router.get("/jobs/{job_id}/duplicates")
async def find_duplicates(job_id: str, threshold: float = 0.8):
    """Find repeated/similar text passages (chorus detection)."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")
    data = json.loads(seg_path.read_text())

    from difflib import SequenceMatcher
    lines = [re.sub(r"[^\w\s]", "", s.get("text", "").lower().strip()) for s in data]
    n = len(lines)

    groups: dict[int, list[int]] = {}
    assigned: set[int] = set()

    for i in range(n):
        if i in assigned or not lines[i]:
            continue
        group = [i]
        for j in range(i + 1, n):
            if j in assigned or not lines[j]:
                continue
            sim = SequenceMatcher(None, lines[i], lines[j]).ratio()
            if sim >= threshold:
                group.append(j)
                assigned.add(j)
        if len(group) > 1:
            groups[i] = group
            assigned.add(i)

    result = []
    for anchor, indices in groups.items():
        result.append({
            "text": data[anchor].get("text", ""),
            "occurrences": len(indices),
            "lines": indices,
            "times": [round(data[i]["start"], 2) for i in indices],
        })

    return {"groups": result, "total_duplicates": sum(len(g["lines"]) for g in result)}


# ── Segment Snapshot / Compare ────────────────────────────────────────────────

@router.post("/jobs/{job_id}/snapshot")
async def save_snapshot(job_id: str, name: str = ""):
    """Save current segment state as a named snapshot for comparison."""
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments")

    snap_dir = tasks.OUTPUT_DIR / job_id / "snapshots"
    snap_dir.mkdir(exist_ok=True)

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    label = name or ts
    snap_path = snap_dir / f"snap_{label}.json"
    shutil.copy2(seg_path, snap_path)
    return {"snapshot": snap_path.name, "label": label}


@router.get("/jobs/{job_id}/snapshots")
async def list_snapshots(job_id: str):
    """List saved snapshots."""
    snap_dir = tasks.OUTPUT_DIR / job_id / "snapshots"
    if not snap_dir.exists():
        return {"snapshots": []}
    snaps = sorted(snap_dir.glob("snap_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {"snapshots": [
        {"name": s.stem, "size": s.stat().st_size, "modified": s.stat().st_mtime}
        for s in snaps
    ]}


@router.post("/jobs/{job_id}/snapshot/restore/{name}")
async def restore_snapshot(job_id: str, name: str):
    """Restore a saved snapshot."""
    snap_path = tasks.OUTPUT_DIR / job_id / "snapshots" / f"{name}.json"
    if not snap_path.exists():
        raise HTTPException(404, "Snapshot not found")
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    tasks.push_undo(job_id)
    shutil.copy2(snap_path, seg_path)
    data = json.loads(seg_path.read_text())
    _sync_srt(job_id, data)
    return {"restored": name, "segments": len(data)}
