"""Main CLI application with typer subcommands."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv
from rich.prompt import Prompt, Confirm, IntPrompt

from src.utils.logging import (
    setup_logging, Verbosity, console, info, success, warn, error, debug,
    make_progress,
)
from src.utils.config import AppConfig, load_config, merge_cli_overrides, DEFAULT_CONFIG_YAML
from src.utils import cache as cache_module
from src.utils.deps_check import check_all, print_dep_status

load_dotenv()

app = typer.Typer(
    name="karaoke-sub",
    help="Professional karaoke subtitle generator from audio files.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


# ── Enums ─────────────────────────────────────────────────────────────────────

class Backend(str, Enum):
    voxtral = "voxtral"
    openai_whisper = "openai_whisper"
    local_whisper = "local_whisper"


class Language(str, Enum):
    auto = "auto"
    de = "de"
    en = "en"


class KaraokeMode(str, Enum):
    k = "k"
    kf = "kf"
    ko = "ko"


class Preset(str, Enum):
    classic = "classic"
    neon = "neon"
    high_contrast = "high_contrast"
    landscape_1080p = "landscape_1080p"
    portrait_1080x1920 = "portrait_1080x1920"
    mobile_safe = "mobile_safe"


class OnOff(str, Enum):
    on = "on"
    off = "off"


class WordTimestampMode(str, Enum):
    on = "on"
    auto = "auto"
    off = "off"


# ── Helper functions ──────────────────────────────────────────────────────────

def _get_backend(name: str, model: str = "", diarize: bool = True):
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
        return WhisperXBackend(model_size=model or "large-v3")
    else:
        raise typer.BadParameter(f"Unknown backend: {name}")


def _resolve_inputs(input_path: Path, recursive: bool = False) -> list[Path]:
    from src.preprocess.ffmpeg_io import find_audio_files, is_supported_audio
    if input_path.is_dir():
        files = find_audio_files(input_path, recursive)
        if not files:
            error(f"No supported audio files in {input_path}")
            raise typer.Exit(1)
        return files
    elif input_path.is_file():
        if not is_supported_audio(input_path):
            error(f"Unsupported format: {input_path.suffix}")
            raise typer.Exit(1)
        return [input_path]
    else:
        error(f"Input not found: {input_path}")
        raise typer.Exit(1)


def _preprocess_audio(audio_path: Path, cfg: AppConfig, tmp_dir: Path):
    from src.preprocess.ffmpeg_io import convert_to_wav, get_duration
    from src.preprocess.vad import detect_speech, create_vad_trimmed, create_time_mapping
    from src.preprocess.normalize import normalize_audio
    from src.preprocess.vocals import isolate_vocals

    current = audio_path
    time_mapping = None
    steps: dict[str, bool] = {"vad": False, "normalize": False, "vocal_isolation": False}

    # vocal isolation first (on original)
    if cfg.preprocess.vocal_isolation.enabled:
        vocals = isolate_vocals(
            current,
            output_dir=tmp_dir / "separated",
            model=cfg.preprocess.vocal_isolation.model,
            device=cfg.preprocess.vocal_isolation.device,
        )
        if vocals:
            current = vocals
            steps["vocal_isolation"] = True

    # convert to WAV for processing
    wav_path = tmp_dir / f"{audio_path.stem}_work.wav"
    current = convert_to_wav(current, wav_path)

    # normalization
    if cfg.preprocess.normalize.enabled:
        norm_path = tmp_dir / f"{audio_path.stem}_norm.wav"
        current = normalize_audio(current, norm_path, cfg.preprocess.normalize.target_lufs)
        steps["normalize"] = True

    # VAD
    if cfg.preprocess.vad.enabled:
        segments = detect_speech(
            current,
            aggressiveness=cfg.preprocess.vad.aggressiveness,
            min_speech_ms=cfg.preprocess.vad.min_speech_ms,
            min_silence_ms=cfg.preprocess.vad.min_silence_ms,
        )
        if segments:
            time_mapping = create_time_mapping(segments)
            vad_path = tmp_dir / f"{audio_path.stem}_vad.wav"
            current = create_vad_trimmed(current, segments, vad_path)
            steps["vad"] = True

    return current, time_mapping, steps


def _process_single_file(audio_path: Path, output_dir: Path, cfg: AppConfig,
                         do_srt: bool = True, do_ass: bool = False,
                         do_preview: bool = False, review: bool = False) -> dict:
    """Process a single audio file through the full pipeline."""
    from src.preprocess.ffmpeg_io import get_duration
    from src.preprocess.vad import remap_timestamps
    from src.refine.text_cleanup import clean_all_segments, load_dictionary
    from src.refine.alignment import ensure_word_timestamps
    from src.refine.segmentation import refine_segments
    from src.refine.beatgrid import detect_bpm, snap_segments_to_grid
    from src.refine.confidence import analyze_confidence, FileReport, save_report
    from src.export.srt_writer import write_srt
    from src.export.ass_writer import write_ass
    from src.transcription.base import TranscriptResult, TranscriptSegment

    result_info: dict = {"file": str(audio_path), "errors": [], "warnings": []}
    start_time = time.time()

    # check cache
    if cfg.cache.enabled and cfg.cache.skip_existing and not cfg.cache.force:
        cached = cache_module.load_cached(audio_path, "transcript", cfg.cache.id_method)
        if cached:
            info(f"Using cached transcript for {audio_path.name}")
            transcript = TranscriptResult.from_dict(cached)
        else:
            cached = None
    else:
        cached = None

    output_dir.mkdir(parents=True, exist_ok=True)
    duration = get_duration(audio_path)

    if not cached:
        # preprocessing
        with tempfile.TemporaryDirectory(prefix="karaoke_") as tmp:
            tmp_dir = Path(tmp)
            processed_audio, time_mapping, prep_steps = _preprocess_audio(
                audio_path, cfg, tmp_dir
            )

            # transcription
            backend = _get_backend(
                cfg.transcription.backend,
                model=cfg.transcription.model,
                diarize=cfg.transcription.diarize,
            )
            ok, msg = backend.check_available()
            if not ok:
                error(f"Backend {cfg.transcription.backend} not available: {msg}")
                result_info["errors"].append(msg)
                return result_info

            transcript = backend.transcribe(
                processed_audio,
                language=cfg.transcription.language,
                word_timestamps=cfg.transcription.word_timestamps != "off",
            )

            # remap VAD timestamps
            if time_mapping and transcript.segments:
                seg_dicts = [s.to_dict() for s in transcript.segments]
                remapped = remap_timestamps(seg_dicts, time_mapping)
                transcript.segments = [TranscriptSegment.from_dict(d) for d in remapped]

        # save cache
        if cfg.cache.enabled:
            cache_module.save_cache(audio_path, "transcript", transcript.to_dict(), cfg.cache.id_method)
    else:
        transcript = TranscriptResult.from_dict(cached)
        prep_steps = {"vad": False, "normalize": False, "vocal_isolation": False}

    segments = transcript.segments
    if not segments:
        warn(f"No segments transcribed for {audio_path.name}")
        result_info["warnings"].append("No segments")
        return result_info

    # text cleanup
    dictionary = {}
    if cfg.refinement.dictionary_path:
        from src.refine.text_cleanup import load_dictionary
        dictionary = load_dictionary(cfg.refinement.dictionary_path)
    segments = clean_all_segments(segments, dictionary)

    # word timestamp alignment
    wt_mode = cfg.transcription.word_timestamps
    segments = ensure_word_timestamps(segments, wt_mode)

    # segmentation refinement
    segments = refine_segments(
        segments,
        cps=cfg.refinement.cps,
        min_duration=cfg.refinement.min_duration,
        max_duration=cfg.refinement.max_duration,
        max_chars_per_line=cfg.refinement.max_chars_per_line,
        max_lines=cfg.refinement.max_lines,
        min_gap_ms=cfg.refinement.min_gap_ms,
    )

    # BPM snap
    bpm_value = 0.0
    if cfg.beat_grid.enabled:
        bpm = cfg.beat_grid.bpm
        if bpm == "detect":
            detected = detect_bpm(audio_path)
            if detected:
                bpm_value = detected
        else:
            try:
                bpm_value = float(bpm)
            except (ValueError, TypeError):
                pass

        if bpm_value > 0:
            segments = snap_segments_to_grid(
                segments, bpm_value, duration,
                time_signature=cfg.beat_grid.time_signature,
                beat_offset_ms=cfg.beat_grid.beat_offset_ms,
                snap_tolerance_ms=cfg.beat_grid.snap_tolerance_ms,
                snap_strength=cfg.beat_grid.snap_strength,
            )

    # review mode
    if review:
        from src.refine.review_tui import review_segments, save_patches
        segments, patches = review_segments(segments)
        if patches:
            patch_path = output_dir / f"{audio_path.stem}.patches.json"
            save_patches(patches, patch_path)
            info(f"Review patches saved: {patch_path}")

    # confidence analysis
    from src.refine.confidence import analyze_confidence, FileReport, save_report
    seg_reports = analyze_confidence(segments, cfg.confidence.low_threshold)

    elapsed = time.time() - start_time
    file_report = FileReport(
        filename=audio_path.name,
        backend=transcript.backend,
        language=transcript.language,
        total_segments=len(segments),
        segments_needing_review=sum(1 for r in seg_reports if r.needs_review),
        avg_confidence=sum(r.avg_conf for r in seg_reports) / max(len(seg_reports), 1),
        vad_active=prep_steps.get("vad", False),
        normalize_active=prep_steps.get("normalize", False),
        vocal_isolation_active=prep_steps.get("vocal_isolation", False),
        bpm_snap_active=bpm_value > 0,
        bpm_value=bpm_value,
        duration_sec=duration,
        runtime_sec=elapsed,
        segment_reports=seg_reports,
    )

    # SRT output
    if do_srt:
        srt_path = output_dir / f"{audio_path.stem}.srt"
        write_srt(segments, srt_path)
        success(f"SRT: {srt_path}")

    # ASS output
    if do_ass:
        ass_path = output_dir / f"{audio_path.stem}.ass"
        template_path = None
        if hasattr(cfg.theme, '_template_path'):
            template_path = Path(cfg.theme._template_path)

        write_ass(
            segments, ass_path,
            preset=cfg.theme.preset,
            karaoke_mode=cfg.karaoke.mode,
            highlight_color=cfg.karaoke.highlight_color,
            safe_area=cfg.theme.safe_area,
            template_path=template_path,
            confidence_threshold=cfg.confidence.low_threshold,
            title=audio_path.stem,
        )
        success(f"ASS: {ass_path}")

    # report
    report_path = save_report(file_report, output_dir / audio_path.stem, cfg.confidence.report_format)
    debug(f"Report: {report_path}")

    # preview
    if do_preview and do_ass:
        from src.preview.render import render_preview
        ass_path = output_dir / f"{audio_path.stem}.ass"
        preview_path = render_preview(
            ass_path,
            audio_path=audio_path,
            duration=cfg.preview.duration,
            start=cfg.preview.start,
            resolution=cfg.preview.resolution,
            background=cfg.preview.background,
            bg_image=Path(cfg.preview.bg_image) if cfg.preview.bg_image else None,
        )
        if preview_path:
            success(f"Preview: {preview_path}")

    # mark done
    if cfg.cache.enabled:
        cache_module.mark_done(output_dir / f"{audio_path.stem}.srt", audio_path, cfg.cache.id_method)

    result_info["segments"] = len(segments)
    result_info["duration"] = elapsed
    result_info["needs_review"] = file_report.segments_needing_review
    return result_info


# ── TRANSCRIBE ────────────────────────────────────────────────────────────────

@app.command()
def transcribe(
    input: Annotated[Path, typer.Option("--input", "-i", help="Audio file or directory")] = Path("."),
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output directory")] = None,
    backend: Annotated[Backend, typer.Option(help="Transcription backend")] = Backend.voxtral,
    language: Annotated[Language, typer.Option(help="Language")] = Language.auto,
    recursive: Annotated[bool, typer.Option("--recursive", "-r")] = False,
    silent: Annotated[bool, typer.Option("--silent")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    config: Annotated[Optional[Path], typer.Option("--config")] = None,
    vad: Annotated[OnOff, typer.Option(help="VAD")] = OnOff.on,
    vad_aggressiveness: Annotated[int, typer.Option()] = 2,
    normalize: Annotated[OnOff, typer.Option(help="Loudness normalization")] = OnOff.on,
    target_lufs: Annotated[float, typer.Option()] = -16.0,
    vocal_isolation: Annotated[OnOff, typer.Option(help="Vocal isolation")] = OnOff.off,
    vocal_device: Annotated[str, typer.Option()] = "cpu",
    word_timestamps: Annotated[WordTimestampMode, typer.Option()] = WordTimestampMode.auto,
    force: Annotated[bool, typer.Option("--force")] = False,
    ass: Annotated[bool, typer.Option("--ass", help="Also generate ASS")] = False,
    karaoke_mode: Annotated[KaraokeMode, typer.Option()] = KaraokeMode.kf,
    preset: Annotated[Preset, typer.Option()] = Preset.classic,
    bpm: Annotated[Optional[str], typer.Option(help="BPM (number or 'detect')")] = None,
    snap_to_beat: Annotated[bool, typer.Option()] = False,
    review: Annotated[bool, typer.Option()] = False,
    preview: Annotated[bool, typer.Option()] = False,
):
    """Transcribe audio files to SRT (and optionally ASS karaoke)."""
    verbosity = Verbosity.SILENT if silent else (Verbosity.VERBOSE if verbose else Verbosity.NORMAL)
    setup_logging(verbosity)

    cfg = load_config(config)
    cfg = merge_cli_overrides(cfg, {
        "transcription.backend": backend.value,
        "transcription.language": language.value,
        "transcription.word_timestamps": word_timestamps.value,
        "preprocess.vad.enabled": vad == OnOff.on,
        "preprocess.vad.aggressiveness": vad_aggressiveness,
        "preprocess.normalize.enabled": normalize == OnOff.on,
        "preprocess.normalize.target_lufs": target_lufs,
        "preprocess.vocal_isolation.enabled": vocal_isolation == OnOff.on,
        "preprocess.vocal_isolation.device": vocal_device,
        "karaoke.mode": karaoke_mode.value,
        "theme.preset": preset.value,
        "cache.force": force,
    })

    if bpm:
        cfg = merge_cli_overrides(cfg, {
            "beat_grid.enabled": True,
            "beat_grid.bpm": bpm,
        })
    if snap_to_beat:
        cfg = merge_cli_overrides(cfg, {"beat_grid.enabled": True})

    # dependency check
    deps = check_all(cfg.transcription.backend, cfg.preprocess.vocal_isolation.enabled)
    if not print_dep_status(deps):
        warn("Some dependencies missing — continuing with available features")

    files = _resolve_inputs(input, recursive)
    out_dir = output or input.parent if input.is_file() else output or input

    info(f"Processing {len(files)} file(s) with {cfg.transcription.backend}")

    with make_progress() as progress:
        task = progress.add_task("Transcribing", total=len(files))
        for f in files:
            try:
                _process_single_file(f, out_dir, cfg, do_srt=True, do_ass=ass,
                                     do_preview=preview, review=review)
            except Exception as e:
                error(f"Failed: {f.name} — {e}")
            progress.advance(task)

    success("Done!")


# ── REFINE ────────────────────────────────────────────────────────────────────

@app.command()
def refine(
    input: Annotated[Path, typer.Option("--input", "-i", help="SRT file or directory")] = Path("."),
    output: Annotated[Optional[Path], typer.Option("--output", "-o")] = None,
    cps: Annotated[float, typer.Option()] = 18.0,
    min_dur: Annotated[float, typer.Option()] = 1.0,
    max_dur: Annotated[float, typer.Option()] = 6.0,
    max_chars_per_line: Annotated[int, typer.Option()] = 42,
    max_lines: Annotated[int, typer.Option()] = 2,
    auto_punct: Annotated[OnOff, typer.Option()] = OnOff.off,
    dictionary: Annotated[Optional[Path], typer.Option()] = None,
    snap_to_beat: Annotated[bool, typer.Option()] = False,
    bpm: Annotated[Optional[str], typer.Option()] = None,
    review: Annotated[bool, typer.Option()] = False,
    dry_run: Annotated[bool, typer.Option()] = False,
    config: Annotated[Optional[Path], typer.Option("--config")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
):
    """Refine existing SRT files (CPS, line breaks, beat snap)."""
    setup_logging(Verbosity.VERBOSE if verbose else Verbosity.NORMAL)

    from src.export.srt_writer import read_srt, write_srt
    from src.refine.text_cleanup import clean_all_segments, load_dictionary
    from src.refine.alignment import ensure_word_timestamps
    from src.refine.segmentation import refine_segments

    cfg = load_config(config)

    srt_files = []
    if input.is_dir():
        srt_files = sorted(input.glob("*.srt"))
    elif input.suffix == ".srt":
        srt_files = [input]
    else:
        error(f"Expected SRT file or directory: {input}")
        raise typer.Exit(1)

    if not srt_files:
        error("No SRT files found")
        raise typer.Exit(1)

    out_dir = output or (input if input.is_dir() else input.parent)
    out_dir.mkdir(parents=True, exist_ok=True)

    for srt_path in srt_files:
        info(f"Refining: {srt_path.name}")
        segments = read_srt(srt_path)

        dict_map = load_dictionary(dictionary) if dictionary else {}
        segments = clean_all_segments(segments, dict_map)
        segments = ensure_word_timestamps(segments)
        segments = refine_segments(segments, cps, min_dur, max_dur, max_chars_per_line, max_lines)

        if snap_to_beat and bpm:
            from src.refine.beatgrid import detect_bpm, snap_segments_to_grid
            bpm_val = float(bpm) if bpm != "detect" else (detect_bpm(srt_path) or 0)
            if bpm_val > 0:
                segments = snap_segments_to_grid(segments, bpm_val, segments[-1].end if segments else 0)

        if review:
            from src.refine.review_tui import review_segments, save_patches
            segments, patches = review_segments(segments)
            if patches:
                save_patches(patches, out_dir / f"{srt_path.stem}.patches.json")

        if dry_run:
            for s in segments[:5]:
                console.print(f"  [{s.start:.2f}-{s.end:.2f}] {s.text}")
            info("(dry run — not writing)")
        else:
            out_path = out_dir / srt_path.name
            write_srt(segments, out_path)
            success(f"Refined: {out_path}")


# ── EXPORT / SRT2ASS ─────────────────────────────────────────────────────────

@app.command()
def export(
    input: Annotated[Path, typer.Option("--input", "-i", help="SRT file or directory")] = Path("."),
    output: Annotated[Optional[Path], typer.Option("--output", "-o")] = None,
    karaoke_mode: Annotated[KaraokeMode, typer.Option()] = KaraokeMode.kf,
    approx_karaoke: Annotated[OnOff, typer.Option()] = OnOff.on,
    highlight_color: Annotated[str, typer.Option()] = "&H0000FFFF",
    preset: Annotated[Preset, typer.Option()] = Preset.classic,
    safe_area: Annotated[str, typer.Option()] = "",
    playresx: Annotated[int, typer.Option()] = 0,
    playresy: Annotated[int, typer.Option()] = 0,
    font: Annotated[str, typer.Option()] = "",
    fontsize: Annotated[int, typer.Option()] = 0,
    primary_color: Annotated[str, typer.Option()] = "",
    outline_color: Annotated[str, typer.Option()] = "",
    outline: Annotated[float, typer.Option()] = 0,
    shadow: Annotated[float, typer.Option()] = 0,
    alignment: Annotated[int, typer.Option()] = 0,
    margins: Annotated[str, typer.Option()] = "",
    ass_template: Annotated[Optional[Path], typer.Option()] = None,
    replace_events_only: Annotated[OnOff, typer.Option()] = OnOff.on,
    config: Annotated[Optional[Path], typer.Option("--config")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
):
    """Export SRT to ASS with karaoke styling."""
    setup_logging(Verbosity.VERBOSE if verbose else Verbosity.NORMAL)

    from src.export.srt_writer import read_srt
    from src.export.ass_writer import write_ass
    from src.refine.alignment import ensure_word_timestamps

    srt_files = []
    if input.is_dir():
        srt_files = sorted(input.glob("*.srt"))
    elif input.suffix == ".srt":
        srt_files = [input]
    else:
        error(f"Expected SRT file or directory: {input}")
        raise typer.Exit(1)

    out_dir = output or (input if input.is_dir() else input.parent)
    out_dir.mkdir(parents=True, exist_ok=True)

    for srt_path in srt_files:
        info(f"Exporting: {srt_path.name}")
        segments = read_srt(srt_path)
        if approx_karaoke == OnOff.on:
            segments = ensure_word_timestamps(segments)

        ass_path = out_dir / f"{srt_path.stem}.ass"
        write_ass(
            segments, ass_path,
            preset=preset.value,
            karaoke_mode=karaoke_mode.value,
            highlight_color=highlight_color,
            safe_area=safe_area,
            template_path=ass_template,
            replace_events_only=replace_events_only == OnOff.on,
            playresx=playresx or None,
            playresy=playresy or None,
            font=font or None,
            fontsize=fontsize or None,
        )
        success(f"ASS: {ass_path}")


# alias
@app.command()
def srt2ass(
    input: Annotated[Path, typer.Option("--input", "-i")] = Path("."),
    output: Annotated[Optional[Path], typer.Option("--output", "-o")] = None,
    karaoke_mode: Annotated[KaraokeMode, typer.Option()] = KaraokeMode.kf,
    preset: Annotated[Preset, typer.Option()] = Preset.classic,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
):
    """Convert SRT to ASS (alias for export)."""
    export(input=input, output=output, karaoke_mode=karaoke_mode, preset=preset, verbose=verbose)


# ── PREVIEW ───────────────────────────────────────────────────────────────────

@app.command()
def preview(
    input_ass: Annotated[Path, typer.Option("--input-ass", "-i", help="ASS file")],
    audio: Annotated[Optional[Path], typer.Option("--audio")] = None,
    preview_dur: Annotated[str, typer.Option("--preview")] = "15s",
    preview_start: Annotated[str, typer.Option("--preview-start")] = "0s",
    resolution: Annotated[str, typer.Option()] = "1920x1080",
    bg: Annotated[str, typer.Option()] = "#000000",
    bg_image: Annotated[Optional[Path], typer.Option()] = None,
):
    """Render a short preview clip from an ASS file."""
    setup_logging(Verbosity.NORMAL)
    from src.preview.render import render_preview

    result = render_preview(
        input_ass,
        audio_path=audio,
        duration=preview_dur,
        start=preview_start,
        resolution=resolution,
        background=bg,
        bg_image=bg_image,
    )
    if result:
        success(f"Preview: {result}")
    else:
        raise typer.Exit(1)


# ── WATCH ─────────────────────────────────────────────────────────────────────

@app.command()
def watch(
    input: Annotated[Path, typer.Option("--input", "-i", help="Directory to watch")] = Path("."),
    output: Annotated[Optional[Path], typer.Option("--output", "-o")] = None,
    recursive: Annotated[bool, typer.Option("--recursive", "-r")] = False,
    on_add: Annotated[str, typer.Option(help="Pipeline: transcribe,refine,export,preview")] = "transcribe,export",
    config: Annotated[Optional[Path], typer.Option("--config")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
):
    """Watch a directory and auto-process new audio files."""
    setup_logging(Verbosity.VERBOSE if verbose else Verbosity.NORMAL)
    from src.watch.watchdog import watch_directory

    cfg = load_config(config)
    out_dir = output or input
    out_dir.mkdir(parents=True, exist_ok=True)

    pipeline_steps = [s.strip() for s in on_add.split(",")]
    do_ass = "export" in pipeline_steps
    do_preview = "preview" in pipeline_steps

    def process_file(audio_path: Path, out: Path) -> None:
        _process_single_file(audio_path, out, cfg, do_srt=True, do_ass=do_ass,
                             do_preview=do_preview)

    watch_directory(input, out_dir, process_file, recursive=recursive)


# ── INTERACTIVE MENU ──────────────────────────────────────────────────────────

@app.command()
def menu():
    """Interactive setup menu."""
    setup_logging(Verbosity.NORMAL)
    from rich.panel import Panel

    console.print(Panel("[bold cyan]Karaoke Subtitle Tool — Interactive Setup[/bold cyan]"))

    # backend
    backend = Prompt.ask(
        "Transcription backend",
        choices=["voxtral", "openai_whisper", "local_whisper"],
        default="voxtral"
    )

    # input
    input_path = Prompt.ask("Input file or directory", default=".")
    output_path = Prompt.ask("Output directory", default="./output")

    # preprocessing
    use_vad = Confirm.ask("Enable VAD?", default=True)
    use_norm = Confirm.ask("Enable loudness normalization?", default=True)
    use_vocals = Confirm.ask("Enable vocal isolation (requires demucs)?", default=False)

    # karaoke
    word_ts = Prompt.ask("Word timestamps", choices=["on", "auto", "off"], default="auto")
    karaoke_mode = Prompt.ask("Karaoke mode", choices=["k", "kf", "ko"], default="kf")

    # refinement
    cps = FloatPrompt.ask("Max CPS", default=18.0)
    max_chars = IntPrompt.ask("Max chars per line", default=42)

    # BPM
    use_bpm = Confirm.ask("Enable BPM snap?", default=False)
    bpm_val = None
    if use_bpm:
        bpm_val = Prompt.ask("BPM (number or 'detect')", default="detect")

    # preset
    preset = Prompt.ask(
        "ASS preset",
        choices=["classic", "neon", "high_contrast", "landscape_1080p", "portrait_1080x1920", "mobile_safe"],
        default="classic"
    )

    do_review = Confirm.ask("Interactive review?", default=False)
    do_preview = Confirm.ask("Render preview?", default=False)
    do_ass = Confirm.ask("Generate ASS?", default=True)

    # build args and invoke
    args = [
        "--input", input_path,
        "--output", output_path,
        "--backend", backend,
        "--vad", "on" if use_vad else "off",
        "--normalize", "on" if use_norm else "off",
        "--vocal-isolation", "on" if use_vocals else "off",
        "--word-timestamps", word_ts,
        "--karaoke-mode", karaoke_mode,
        "--preset", preset,
    ]
    if do_ass:
        args.append("--ass")
    if do_review:
        args.append("--review")
    if do_preview:
        args.append("--preview")
    if bpm_val:
        args.extend(["--bpm", bpm_val, "--snap-to-beat"])

    console.print(f"\n[dim]Running: karaoke-sub transcribe {' '.join(args)}[/dim]\n")

    # re-invoke transcribe with parsed args
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, ["transcribe"] + args, catch_exceptions=False)
    if result.output:
        console.print(result.output)


# ── INIT CONFIG ───────────────────────────────────────────────────────────────

@app.command(name="init")
def init_config():
    """Generate a default config.yaml in the current directory."""
    setup_logging(Verbosity.NORMAL)
    p = Path("config.yaml")
    if p.exists():
        if not Confirm.ask("config.yaml exists. Overwrite?", default=False):
            raise typer.Exit(0)
    p.write_text(DEFAULT_CONFIG_YAML)
    success(f"Created {p}")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def app_entry():
    app()


if __name__ == "__main__":
    app_entry()
