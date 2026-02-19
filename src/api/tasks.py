"""Background job manager for async audio processing — v3 thread-safe."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
import traceback
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.api.models import JobInfo, JobResult, JobStatus, TranscribeRequest, RefineRequest, ExportRequest
from src.utils.logging import info, success, warn, error, debug


UPLOAD_DIR = Path("data/uploads")
OUTPUT_DIR = Path("data/output")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, JobInfo] = {}
_jobs_lock = threading.Lock()

# SSE — thread-safe event bus
_sse_subscribers: list[asyncio.Queue] = []
_loop: asyncio.AbstractEventLoop | None = None  # captured on first SSE subscribe

# Undo/Redo
_undo_stacks: dict[str, deque[str]] = {}
_redo_stacks: dict[str, deque[str]] = {}
_undo_lock = threading.Lock()
MAX_UNDO = 50


def get_jobs() -> dict[str, JobInfo]:
    return _jobs

def get_job(job_id: str) -> JobInfo | None:
    return _jobs.get(job_id)


def create_job(filename: str) -> JobInfo:
    job_id = uuid.uuid4().hex[:12]
    job = JobInfo(
        job_id=job_id, filename=filename,
        status=JobStatus.pending, progress=0.0, stage="queued",
        created_at=datetime.now(timezone.utc),
    )
    with _jobs_lock:
        _jobs[job_id] = job
    _emit_sse({"type": "job_created", "job_id": job_id, "filename": filename})
    return job


def update_job(job_id: str, **kwargs) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for k, v in kwargs.items():
            setattr(job, k, v)
        status_val = job.status.value
        progress_val = job.progress
        stage_val = job.stage
    _emit_sse({
        "type": "job_progress", "job_id": job_id,
        "status": status_val, "progress": progress_val, "stage": stage_val,
    })


# ── SSE (thread-safe) ────────────────────────────────────────────────────────

def subscribe_sse() -> asyncio.Queue:
    global _loop
    _loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_subscribers.append(q)
    return q

def unsubscribe_sse(q: asyncio.Queue) -> None:
    if q in _sse_subscribers:
        _sse_subscribers.remove(q)


def _emit_sse(event: dict) -> None:
    """Thread-safe SSE emission — safe to call from ThreadPoolExecutor."""
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    if _loop is None or not _sse_subscribers:
        return
    for q in list(_sse_subscribers):  # copy list to avoid mutation during iteration
        try:
            _loop.call_soon_threadsafe(q.put_nowait, event)
        except (asyncio.QueueFull, RuntimeError):
            pass  # drop if queue full or loop closed


# ── Undo/Redo ─────────────────────────────────────────────────────────────────

def push_undo(job_id: str) -> None:
    seg_path = OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists(): return
    with _undo_lock:
        if job_id not in _undo_stacks:
            _undo_stacks[job_id] = deque(maxlen=MAX_UNDO)
            _redo_stacks[job_id] = deque(maxlen=MAX_UNDO)
        _undo_stacks[job_id].append(seg_path.read_text(encoding="utf-8"))
        _redo_stacks[job_id].clear()

def undo(job_id: str) -> bool:
    with _undo_lock:
        if job_id not in _undo_stacks or not _undo_stacks[job_id]: return False
        seg_path = OUTPUT_DIR / job_id / "segments.json"
        if seg_path.exists():
            _redo_stacks.setdefault(job_id, deque(maxlen=MAX_UNDO)).append(seg_path.read_text(encoding="utf-8"))
        seg_path.write_text(_undo_stacks[job_id].pop(), encoding="utf-8")
        return True

def redo(job_id: str) -> bool:
    with _undo_lock:
        if job_id not in _redo_stacks or not _redo_stacks[job_id]: return False
        seg_path = OUTPUT_DIR / job_id / "segments.json"
        if seg_path.exists():
            _undo_stacks.setdefault(job_id, deque(maxlen=MAX_UNDO)).append(seg_path.read_text(encoding="utf-8"))
        seg_path.write_text(_redo_stacks[job_id].pop(), encoding="utf-8")
        return True


# ── Run Jobs ──────────────────────────────────────────────────────────────────

def _safe_stem(name: str, fallback: str = "unknown") -> str:
    """Sanitize a filename stem — remove path traversal, special chars, limit length."""
    import re as _re
    # Strip path separators, null bytes
    name = name.replace("/", "_").replace("\\", "_").replace("\x00", "")
    # Remove leading dots (hidden files) and collapse ".." sequences
    name = name.lstrip(".")
    name = _re.sub(r"\.{2,}", ".", name)  # collapse .. → .
    # Keep only safe chars
    name = _re.sub(r"[^\w\s\-.]", "_", name)
    name = _re.sub(r"\s+", "_", name).strip("_").strip(".")
    if not name:
        name = fallback
    return name[:200]  # filesystem limit safety


def get_artifact_dir(job_output: Path, stem: str) -> Path:
    """Get (and create) the artifact subdirectory for a job."""
    d = job_output / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


async def run_transcribe_job(job_id: str, audio_path: Path, req: TranscribeRequest) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _transcribe_sync, job_id, audio_path, req)


def _transcribe_sync(job_id: str, audio_path: Path, req: TranscribeRequest) -> None:
    from src.preprocess.ffmpeg_io import convert_to_wav, get_duration
    from src.preprocess.vad import detect_speech, create_vad_trimmed, create_time_mapping, remap_timestamps
    from src.preprocess.normalize import normalize_audio
    from src.preprocess.vocals import isolate_vocals
    from src.refine.text_cleanup import clean_all_segments
    from src.refine.alignment import ensure_word_timestamps
    from src.refine.segmentation import refine_segments
    from src.refine.lyrics_align import parse_lyrics_file, align_lyrics_to_segments
    from src.refine.beatgrid import detect_bpm, snap_segments_to_grid
    from src.refine.confidence import analyze_confidence, FileReport, save_report
    from src.export.srt_writer import write_srt
    from src.export.ass_writer import write_ass
    from src.export.vtt_writer import write_vtt
    from src.export.lrc_writer import write_lrc
    from src.export.txt_writer import write_txt
    from src.transcription.base import TranscriptResult, TranscriptSegment

    try:
        job_output = OUTPUT_DIR / job_id
        job_output.mkdir(parents=True, exist_ok=True)

        # stem = sanitized filename base — needed throughout the pipeline
        stem = _safe_stem(audio_path.stem, fallback=job_id)

        # copy original audio for playback
        import shutil
        audio_copy = job_output / audio_path.name
        if not audio_copy.exists():
            info(f"[{job_id}] Copying audio for playback...")
            shutil.copy2(audio_path, audio_copy)

        info(f"[{job_id}] Getting duration...")
        duration = get_duration(audio_path)
        update_job(job_id, status=JobStatus.preprocessing, progress=0.05, stage="Preprocessing")

        with tempfile.TemporaryDirectory(prefix="karaoke_") as tmp:
            tmp_dir = Path(tmp)
            current = audio_path
            time_mapping = None

            if req.vocal_isolation:
                update_job(job_id, progress=0.07, stage="Vocal isolation")
                info(f"[{job_id}] Vocal isolation...")
                vocals = isolate_vocals(current, output_dir=tmp_dir / "sep", device=req.vocal_device)
                if vocals:
                    current = vocals

            info(f"[{job_id}] Converting to WAV (16kHz mono)...")
            update_job(job_id, progress=0.08, stage="Converting to WAV")
            wav_path = tmp_dir / f"{audio_path.stem}_work.wav"
            current = convert_to_wav(current, wav_path)
            update_job(job_id, progress=0.12, stage="WAV ready")

            if req.normalize:
                info(f"[{job_id}] Normalizing audio...")
                update_job(job_id, progress=0.13, stage="Normalizing")
                norm_path = tmp_dir / f"{audio_path.stem}_norm.wav"
                current = normalize_audio(current, norm_path, req.target_lufs)
                update_job(job_id, progress=0.18, stage="Normalized")

            # WhisperX has built-in VAD
            # Also skip external VAD when vocal isolation is active — the isolated
            # vocals track already filters non-speech content, and running VAD on
            # it causes large timestamp gaps when silence between vocal phrases
            # gets trimmed (the #1 cause of "timestamp jumps" bug)
            use_external_vad = req.vad and req.backend.value != "whisperx" and not req.vocal_isolation
            if use_external_vad:
                info(f"[{job_id}] Running VAD...")
                update_job(job_id, progress=0.19, stage="VAD running")
                segments_vad = detect_speech(current, aggressiveness=req.vad_aggressiveness)
                if segments_vad:
                    time_mapping = create_time_mapping(segments_vad)
                    vad_path = tmp_dir / f"{audio_path.stem}_vad.wav"
                    current = create_vad_trimmed(current, segments_vad, vad_path)
                update_job(job_id, progress=0.22, stage="VAD done")

            # ── Transcription (API call) ──────────────────────────────────
            info(f"[{job_id}] Starting transcription with {req.backend.value}...")
            update_job(job_id, status=JobStatus.transcribing, progress=0.25, stage=f"Transcribing ({req.backend.value})")

            backend = _get_backend(req.backend.value, req=req)
            ok, msg = backend.check_available()
            if not ok:
                raise RuntimeError(f"Backend not available: {msg}")

            transcript = backend.transcribe(
                current,
                language=req.language.value,
                word_timestamps=req.word_timestamps != "off",
            )

            info(f"[{job_id}] Transcription done: {len(transcript.segments)} segments")

            if time_mapping and transcript.segments:
                seg_dicts = [s.to_dict() for s in transcript.segments]
                remapped = remap_timestamps(seg_dicts, time_mapping)
                transcript.segments = [TranscriptSegment.from_dict(d) for d in remapped]

        update_job(job_id, progress=0.55, stage="Transcription complete")

        segments = transcript.segments
        if not segments:
            raise RuntimeError("No segments transcribed")

        # ── Refinement ────────────────────────────────────────────────────
        info(f"[{job_id}] Refining segments...")
        update_job(job_id, status=JobStatus.refining, progress=0.60, stage="Refining")

        # Lyrics alignment: if user uploaded a lyrics file, use template system
        lyrics_aligned = False
        if req.lyrics_file and req.use_lyrics_template:
            lyrics_path = UPLOAD_DIR / req.lyrics_file
            if lyrics_path.exists() and lyrics_path.suffix.lower() in (".txt", ".lrc"):
                info(f"[{job_id}] Lyrics template: {req.lyrics_file} (mode={req.lyrics_template_mode.value})")
                update_job(job_id, progress=0.62, stage="Parsing lyrics")

                from src.lyrics.template import parse_lyrics, get_lrc_timings
                from src.lyrics.reports import generate_alignment_report, save_alignment_report, save_diff_report

                parsed = parse_lyrics(lyrics_path, preserve_empty_lines=req.preserve_empty_lines)
                target_lines = parsed.target_lines

                if target_lines:
                    # Save lyrics artifacts
                    import shutil
                    shutil.copy2(lyrics_path, job_output / f"lyrics_original{lyrics_path.suffix}")
                    (job_output / "lyrics_parsed.json").write_text(
                        json.dumps(parsed.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

                    update_job(job_id, progress=0.64, stage=f"Aligning {len(target_lines)} lyrics lines")

                    # Ensure word timestamps for alignment
                    segments = ensure_word_timestamps(segments, "force")
                    original_segments = list(segments)  # keep copy for report

                    # Align lyrics to transcription
                    threshold = 0.5 if req.match_mode.value == "lenient" else 0.7
                    segments = align_lyrics_to_segments(segments, target_lines,
                                                        similarity_threshold=threshold)

                    # Generate alignment report
                    update_job(job_id, progress=0.67, stage="Generating alignment report")
                    alignment_report = generate_alignment_report(
                        target_lines, segments, original_segments)
                    save_alignment_report(alignment_report, job_output / stem)

                    # Hybrid mode: save diff report
                    if req.lyrics_template_mode.value == "hybrid_mark_differences":
                        save_diff_report(alignment_report, job_output / stem)

                    # Layout-only mode: use ASR text but lyrics line breaks
                    if req.lyrics_template_mode.value == "layout_only_reflow":
                        for i, seg in enumerate(segments):
                            if i < len(alignment_report.line_alignments):
                                la = alignment_report.line_alignments[i]
                                if la.asr_text.strip():
                                    seg.text = la.asr_text  # keep ASR text, lyrics timing

                    lyrics_aligned = True
                    info(f"[{job_id}] Lyrics aligned: {len(segments)} segments, "
                         f"avg_score={alignment_report.avg_match_score:.2f}, "
                         f"review={alignment_report.lines_needing_review}")
                else:
                    warn(f"[{job_id}] Lyrics file empty, falling back to normal refinement")
            else:
                warn(f"[{job_id}] Lyrics file not found or wrong format: {req.lyrics_file}")

        elif req.lyrics_file:
            # Legacy mode: lyrics alignment without template system
            lyrics_path = UPLOAD_DIR / req.lyrics_file
            if lyrics_path.exists() and lyrics_path.suffix.lower() in (".txt", ".lrc"):
                info(f"[{job_id}] Legacy lyrics align: {req.lyrics_file}")
                update_job(job_id, progress=0.62, stage="Aligning to lyrics")
                lyrics_lines = parse_lyrics_file(lyrics_path)
                if lyrics_lines:
                    segments = ensure_word_timestamps(segments, "force")
                    segments = align_lyrics_to_segments(segments, lyrics_lines)
                    lyrics_aligned = True

        if not lyrics_aligned:
            # Normal refinement pipeline
            segments = clean_all_segments(segments)
            segments = ensure_word_timestamps(segments, req.word_timestamps)
            segments = refine_segments(
                segments, cps=req.cps, min_duration=req.min_duration,
                max_duration=req.max_duration, max_chars_per_line=req.max_chars_per_line,
                max_lines=req.max_lines,
            )

        bpm_value = 0.0
        if req.snap_to_beat and req.bpm:
            if req.bpm == "detect":
                info(f"[{job_id}] Detecting BPM...")
                update_job(job_id, progress=0.72, stage="Detecting BPM")
                bpm_value = detect_bpm(audio_path) or 0
                if bpm_value > 0:
                    info(f"[{job_id}] BPM: {bpm_value:.1f}")
            else:
                try: bpm_value = float(req.bpm)
                except ValueError: pass
            if bpm_value > 0:
                update_job(job_id, progress=0.73, stage=f"Snapping to {bpm_value:.0f} BPM")
                segments = snap_segments_to_grid(segments, bpm_value, duration)

        # ── AI Lyrics Correction (Mistral) ────────────────────────────────
        ai_corrected = False
        if req.ai_correct:
            info(f"[{job_id}] AI lyrics correction...")
            update_job(job_id, progress=0.74, stage="AI correcting lyrics")
            try:
                segments, ai_corrected = _ai_correct_lyrics(segments, req.language.value, job_id)
            except Exception as e:
                warn(f"[{job_id}] AI correction failed: {e}")

        update_job(job_id, progress=0.75, stage="Refined")

        # ── Export ────────────────────────────────────────────────────────
        info(f"[{job_id}] Exporting formats...")
        update_job(job_id, status=JobStatus.exporting, progress=0.80, stage="Exporting")
        # stem already defined above

        srt_path = job_output / f"{stem}.srt"
        write_srt(segments, srt_path)

        ass_path = None
        if req.generate_ass:
            ass_path = job_output / f"{stem}.ass"
            write_ass(segments, ass_path, preset=req.preset.value,
                      karaoke_mode=req.karaoke_mode.value,
                      highlight_color=req.highlight_color, safe_area=req.safe_area, title=stem)

        vtt_path = lrc_path = txt_path = None
        if req.generate_vtt:
            vtt_path = job_output / f"{stem}.vtt"; write_vtt(segments, vtt_path)
        if req.generate_lrc:
            lrc_path = job_output / f"{stem}.lrc"; write_lrc(segments, lrc_path, title=stem)
        if req.generate_txt:
            txt_path = job_output / f"{stem}.txt"; write_txt(segments, txt_path)

        update_job(job_id, progress=0.88, stage="Exported")

        # ── Confidence report ─────────────────────────────────────────────
        seg_reports = analyze_confidence(segments, 0.6)
        file_report = FileReport(
            filename=audio_path.name, backend=transcript.backend,
            language=transcript.language, total_segments=len(segments),
            segments_needing_review=sum(1 for r in seg_reports if r.needs_review),
            avg_confidence=sum(r.avg_conf for r in seg_reports) / max(len(seg_reports), 1),
            vad_active=req.vad, normalize_active=req.normalize,
            vocal_isolation_active=req.vocal_isolation,
            bpm_snap_active=bpm_value > 0, bpm_value=bpm_value,
            ai_correct_active=ai_corrected,
            duration_sec=duration, segment_reports=seg_reports,
        )
        report_path = save_report(file_report, job_output / stem, "json")

        # ── Preview ───────────────────────────────────────────────────────
        preview_path = None
        if req.generate_preview and ass_path:
            update_job(job_id, status=JobStatus.rendering_preview, progress=0.90, stage="Rendering preview")
            from src.preview.render import render_preview
            preview_path = render_preview(ass_path, audio_path=audio_path,
                duration=req.preview_duration, start=req.preview_start,
                resolution=req.preview_resolution)

        # ── segments.json ─────────────────────────────────────────────────
        seg_data = [s.to_dict() for s in segments]
        (job_output / "segments.json").write_text(
            json.dumps(seg_data, indent=2, ensure_ascii=False), encoding="utf-8")

        # ── Waveform (non-blocking, uses WAV copy if available) ───────────
        update_job(job_id, progress=0.95, stage="Generating waveform")
        try:
            _generate_waveform_data(audio_copy, job_output / "waveform.json")
        except Exception as wf_err:
            warn(f"[{job_id}] Waveform generation failed (non-critical): {wf_err}")

        # ── Done ──────────────────────────────────────────────────────────
        has_words = any(s.has_word_timestamps for s in segments)
        result = JobResult(
            srt_file=srt_path.name,
            ass_file=ass_path.name if ass_path else None,
            vtt_file=vtt_path.name if vtt_path else None,
            lrc_file=lrc_path.name if lrc_path else None,
            txt_file=txt_path.name if txt_path else None,
            preview_file=preview_path.name if preview_path else None,
            report_file=report_path.name,
            segments_count=len(segments),
            duration_sec=duration,
            needs_review=file_report.segments_needing_review,
            backend=transcript.backend,
            language=transcript.language,
            word_timestamps_available=has_words,
        )
        update_job(job_id, status=JobStatus.completed, progress=1.0, stage="Done",
                   completed_at=datetime.now(timezone.utc), result=result)

        # ── Save to Library ───────────────────────────────────────────────
        try:
            from src.db.library import save_transcription
            srt_text = srt_path.read_text(encoding="utf-8") if srt_path.exists() else None
            ass_text = ass_path.read_text(encoding="utf-8") if ass_path and ass_path.exists() else None
            seg_json = (job_output / "segments.json").read_text(encoding="utf-8")
            save_transcription(
                source_filename=audio_path.name,
                backend=transcript.backend,
                language=transcript.language,
                duration_sec=duration,
                bpm=bpm_value,
                segments_count=len(segments),
                has_word_timestamps=has_words,
                needs_review=file_report.segments_needing_review,
                avg_confidence=file_report.avg_confidence,
                srt_text=srt_text,
                ass_text=ass_text,
                segments_json=seg_json,
                job_id=job_id,
            )
        except Exception as lib_err:
            warn(f"[{job_id}] Library save failed (non-critical): {lib_err}")

        _emit_sse({"type": "job_completed", "job_id": job_id, "filename": _jobs[job_id].filename})
        info(f"[{job_id}] ✅ Completed: {len(segments)} segments")
        info(f"[{job_id}] 📁 Output: {job_output}")

    except Exception as e:
        error(f"[{job_id}] ❌ Failed: {e}")
        traceback.print_exc()
        update_job(job_id, status=JobStatus.failed, stage="Error", error=str(e),
                   completed_at=datetime.now(timezone.utc))
        _emit_sse({"type": "job_failed", "job_id": job_id, "error": str(e)})


async def run_refine_job(job_id: str, srt_path: Path, req: RefineRequest) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _refine_sync, job_id, srt_path, req)

def _refine_sync(job_id: str, srt_path: Path, req: RefineRequest) -> None:
    from src.export.srt_writer import read_srt, write_srt
    from src.refine.text_cleanup import clean_all_segments
    from src.refine.alignment import ensure_word_timestamps
    from src.refine.segmentation import refine_segments
    try:
        update_job(job_id, status=JobStatus.refining, progress=0.2, stage="Reading SRT")
        segments = read_srt(srt_path)
        segments = clean_all_segments(segments)
        segments = ensure_word_timestamps(segments)
        update_job(job_id, progress=0.5, stage="Refining segments")
        segments = refine_segments(segments, cps=req.cps, min_duration=req.min_duration,
            max_duration=req.max_duration, max_chars_per_line=req.max_chars_per_line, max_lines=req.max_lines)
        job_output = OUTPUT_DIR / job_id
        job_output.mkdir(parents=True, exist_ok=True)
        out_path = job_output / srt_path.name
        write_srt(segments, out_path)
        seg_data = [s.to_dict() for s in segments]
        (job_output / "segments.json").write_text(json.dumps(seg_data, indent=2, ensure_ascii=False))
        result = JobResult(srt_file=out_path.name, segments_count=len(segments))
        update_job(job_id, status=JobStatus.completed, progress=1.0, stage="Done",
                   completed_at=datetime.now(timezone.utc), result=result)
    except Exception as e:
        update_job(job_id, status=JobStatus.failed, error=str(e), completed_at=datetime.now(timezone.utc))


async def run_export_job(job_id: str, srt_path: Path, req: ExportRequest) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, _export_sync, job_id, srt_path, req)

def _export_sync(job_id: str, srt_path: Path, req: ExportRequest) -> None:
    from src.export.srt_writer import read_srt, write_srt
    from src.export.ass_writer import write_ass
    from src.export.vtt_writer import write_vtt
    from src.export.lrc_writer import write_lrc
    from src.export.txt_writer import write_txt
    from src.refine.alignment import ensure_word_timestamps
    try:
        update_job(job_id, status=JobStatus.exporting, progress=0.3, stage="Reading SRT")
        segments = read_srt(srt_path)
        if req.approx_karaoke: segments = ensure_word_timestamps(segments)
        job_output = OUTPUT_DIR / job_id
        job_output.mkdir(parents=True, exist_ok=True)
        stem = srt_path.stem
        result_kwargs: dict[str, Any] = {"segments_count": len(segments)}
        for fmt in req.formats:
            v = fmt.value
            if v == "srt": write_srt(segments, job_output/f"{stem}.srt"); result_kwargs["srt_file"] = f"{stem}.srt"
            elif v == "ass": write_ass(segments, job_output/f"{stem}.ass", preset=req.preset.value,
                karaoke_mode=req.karaoke_mode.value, highlight_color=req.highlight_color,
                safe_area=req.safe_area); result_kwargs["ass_file"] = f"{stem}.ass"
            elif v == "vtt": write_vtt(segments, job_output/f"{stem}.vtt"); result_kwargs["vtt_file"] = f"{stem}.vtt"
            elif v == "lrc": write_lrc(segments, job_output/f"{stem}.lrc", title=stem); result_kwargs["lrc_file"] = f"{stem}.lrc"
            elif v == "txt": write_txt(segments, job_output/f"{stem}.txt"); result_kwargs["txt_file"] = f"{stem}.txt"
        result = JobResult(**result_kwargs)
        update_job(job_id, status=JobStatus.completed, progress=1.0, stage="Done",
                   completed_at=datetime.now(timezone.utc), result=result)
    except Exception as e:
        update_job(job_id, status=JobStatus.failed, error=str(e), completed_at=datetime.now(timezone.utc))


# ── Waveform (uses converted WAV, not original compressed audio) ──────────────

def _ai_correct_lyrics(
    segments: list[TranscriptSegment], language: str, job_id: str
) -> tuple[list[TranscriptSegment], bool]:
    """Use Mistral API to correct transcription errors in lyrics.

    Uses the same MISTRAL_API_KEY as Voxtral transcription.
    Returns (corrected_segments, success_bool).
    """
    import os
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        warn(f"[{job_id}] AI correction: no MISTRAL_API_KEY")
        return segments, False

    try:
        from mistralai import Mistral
    except ImportError:
        warn(f"[{job_id}] AI correction: mistralai not installed")
        return segments, False

    # Build lyrics text for the prompt
    lyrics_lines = []
    for i, seg in enumerate(segments):
        lyrics_lines.append(f"{i+1}: {seg.text}")
    lyrics_text = "\n".join(lyrics_lines)

    lang_names = {"de": "Deutsch", "en": "English", "fr": "Français", "es": "Español", "ja": "Japanese"}
    lang_name = lang_names.get(language, language or "auto-detected")

    prompt = f"""Du bist ein Experte fuer Songtext-Korrektur. Korrigiere Transkriptionsfehler in den folgenden Lyrics.

Regeln:
- Korrigiere offensichtliche Transkriptionsfehler (falsch erkannte Woerter)
- Beachte Reimschemata: wenn Zeile A reimt, muss die korrigierte Version auch reimen
- Behalte Slang, Umgangssprache und kuenstlerische Freiheiten bei
- Aendere NUR Woerter die eindeutig falsch transkribiert sind
- Gib NUR die geaenderten Zeilen zurueck im Format: NUMMER: korrigierter Text
- Wenn nichts zu korrigieren ist, antworte mit: KEINE KORREKTUREN
- Sprache: {lang_name}

Lyrics:
{lyrics_text}"""

    try:
        client = Mistral(api_key=api_key)
        info(f"[{job_id}] Sending {len(segments)} segments to Mistral for correction...")

        response = client.chat.complete(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4096,
        )

        result_text = response.choices[0].message.content.strip()

        if "KEINE KORREKTUREN" in result_text.upper() or not result_text:
            info(f"[{job_id}] AI: no corrections needed")
            return segments, True

        # Parse corrections
        import re
        corrections = 0
        for line in result_text.split("\n"):
            line = line.strip()
            match = re.match(r"(\d+)\s*:\s*(.+)", line)
            if not match:
                continue
            idx = int(match.group(1)) - 1
            new_text = match.group(2).strip()
            if 0 <= idx < len(segments) and new_text != segments[idx].text:
                old_text = segments[idx].text
                segments[idx].text = new_text
                debug(f"[{job_id}] AI fix [{idx+1}]: '{old_text}' -> '{new_text}'")
                corrections += 1

        info(f"[{job_id}] AI corrected {corrections} segments")
        return segments, True

    except Exception as e:
        warn(f"[{job_id}] Mistral AI correction error: {e}")
        return segments, False


def _generate_waveform_data(audio_path: Path, output_path: Path, num_points: int = 2000) -> None:
    """Generate waveform peak data. Uses ffmpeg to decode to raw PCM first
    to avoid soundfile struggling with compressed formats."""
    import subprocess

    info(f"Generating waveform from {audio_path.name}...")

    # Decode to raw PCM via ffmpeg (fast, handles any format)
    cmd = ["ffmpeg", "-y", "-i", str(audio_path), "-f", "s16le", "-ac", "1", "-ar", "22050", "pipe:1"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            warn(f"Waveform ffmpeg failed, skipping")
            return
    except subprocess.TimeoutExpired:
        warn("Waveform generation timed out")
        return

    import numpy as np
    raw = result.stdout
    if not raw:
        return

    # Convert raw PCM bytes to numpy array
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    samples /= 32768.0  # normalize to -1..1
    sr = 22050
    duration = len(samples) / sr

    chunk_size = max(1, len(samples) // num_points)
    peaks = []
    for i in range(0, len(samples), chunk_size):
        chunk = samples[i:i + chunk_size]
        if len(chunk) > 0:
            peaks.append(float(np.max(np.abs(chunk))))

    output_path.write_text(json.dumps({
        "peaks": peaks, "duration": duration, "sample_rate": sr,
    }), encoding="utf-8")
    info(f"Waveform: {len(peaks)} peaks, {duration:.1f}s")


# ── Backend factory ───────────────────────────────────────────────────────────

def _get_backend(name: str, model: str = "", diarize: bool = True, req: TranscribeRequest | None = None):
    if name == "voxtral":
        from src.transcription.voxtral import VoxtralBackend
        return VoxtralBackend(model=model or "voxtral-mini-latest", diarize=diarize)
    elif name == "openai_whisper":
        from src.transcription.openai_whisper import OpenAIWhisperBackend
        return OpenAIWhisperBackend()
    elif name == "local_whisper":
        from src.transcription.local_whisper import LocalWhisperBackend
        return LocalWhisperBackend()
    elif name == "whisperx":
        from src.transcription.whisperx_backend import WhisperXBackend
        kw = {}
        if req:
            kw = {"model_size": req.whisperx_model_size, "compute_type": req.whisperx_compute_type,
                  "batch_size": req.whisperx_batch_size}
        return WhisperXBackend(**kw)
    raise ValueError(f"Unknown backend: {name}")
