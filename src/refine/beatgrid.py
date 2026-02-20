"""BPM-Grid snap for aligning subtitle timestamps to musical beats."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from src.transcription.base import TranscriptSegment
from src.utils.logging import info, debug, warn


@dataclass
class BPMSubtitleParams:
    """Recommended subtitle parameters derived from BPM + format."""
    bpm: float
    cps: float
    max_chars_per_line: int
    max_lines: int
    min_duration: float
    max_duration: float
    min_gap_ms: int
    rationale: str

    def to_dict(self) -> dict:
        return {
            "bpm": self.bpm,
            "cps": round(self.cps, 1),
            "max_chars_per_line": self.max_chars_per_line,
            "max_lines": self.max_lines,
            "min_duration": round(self.min_duration, 2),
            "max_duration": round(self.max_duration, 2),
            "min_gap_ms": self.min_gap_ms,
            "rationale": self.rationale,
        }


def calculate_subtitle_params(bpm: float, format: str = "ass") -> BPMSubtitleParams:
    """Calculate optimal subtitle parameters from BPM and export format.

    The idea: faster BPM → faster text delivery → higher CPS limit and shorter lines.
    For karaoke (ASS), word-level timing makes higher CPS acceptable.

    BPM ranges (approximate genre mapping):
        60-80   → Ballad / Slow R&B
        80-100  → Pop / Reggae
        100-130 → Dance / Electronic / Pop-Rap
        130-160 → Drum & Bass / Fast Rap
        160+    → Hardcore / Speed-Rap
    """
    # Base beat interval in seconds
    beat_sec = 60.0 / max(bpm, 40)

    # ── CPS: scales with BPM ──────────────────────────────────────────────
    # Slow songs: ~14 CPS, fast songs: up to ~28 CPS
    # Karaoke (ASS) can afford ~20% higher CPS since words highlight individually
    if bpm <= 80:
        cps = 14.0
    elif bpm <= 100:
        cps = 14.0 + (bpm - 80) * 0.15  # 14 → 17
    elif bpm <= 130:
        cps = 17.0 + (bpm - 100) * 0.13  # 17 → 20.9
    elif bpm <= 160:
        cps = 21.0 + (bpm - 130) * 0.1   # 21 → 24
    else:
        cps = min(28.0, 24.0 + (bpm - 160) * 0.08)

    if format == "ass":
        cps *= 1.2  # karaoke word-level = more readable at higher CPS

    # ── Max chars per line: inversely related to speed ────────────────────
    if bpm <= 80:
        max_chars = 48
    elif bpm <= 120:
        max_chars = 42
    elif bpm <= 150:
        max_chars = 36
    else:
        max_chars = 30

    # ── Max lines: 2 for most, 1 for very fast ───────────────────────────
    max_lines = 1 if bpm > 150 else 2

    # ── Duration: based on beat groupings ─────────────────────────────────
    # min_duration = 2 beats, max_duration = 8 beats (capped)
    min_duration = max(0.8, beat_sec * 2)
    max_duration = min(8.0, beat_sec * 8)

    # ── Gap: at least half a beat, minimum 40ms ──────────────────────────
    min_gap_ms = max(40, int(beat_sec * 500))  # half a beat in ms

    # Rationale string
    if bpm <= 80:
        tempo = "langsam"
    elif bpm <= 120:
        tempo = "mittel"
    elif bpm <= 150:
        tempo = "schnell"
    else:
        tempo = "sehr schnell"

    rationale = (
        f"{bpm:.0f} BPM ({tempo}): "
        f"CPS={cps:.0f}, {max_chars} Zeichen/Zeile × {max_lines} Zeilen, "
        f"Dauer {min_duration:.1f}–{max_duration:.1f}s, Gap {min_gap_ms}ms"
    )

    return BPMSubtitleParams(
        bpm=bpm,
        cps=round(cps, 1),
        max_chars_per_line=max_chars,
        max_lines=max_lines,
        min_duration=round(min_duration, 2),
        max_duration=round(max_duration, 2),
        min_gap_ms=min_gap_ms,
        rationale=rationale,
    )


def detect_bpm(audio_path) -> float | None:
    """Detect BPM — tries Essentia first, falls back to librosa."""
    bpm = _detect_bpm_essentia(audio_path)
    if bpm is not None:
        return bpm
    return _detect_bpm_librosa(audio_path)


def _detect_bpm_essentia(audio_path) -> float | None:
    """BPM detection using Essentia (more accurate, especially for electronic/rap)."""
    try:
        import essentia.standard as es

        info(f"Detecting BPM with Essentia: {audio_path}")
        loader = es.MonoLoader(filename=str(audio_path), sampleRate=44100)
        audio = loader()

        # RhythmExtractor2013 is Essentia's best BPM estimator
        rhythm = es.RhythmExtractor2013(method="multifeature")
        bpm, beats, beats_confidence, _, beat_intervals = rhythm(audio)

        bpm = float(bpm)
        try:
            import numpy as np
            avg_confidence = float(np.mean(beats_confidence)) if np.size(beats_confidence) > 0 else 0
        except Exception:
            avg_confidence = float(beats_confidence) if isinstance(beats_confidence, (int, float)) else 0

        num_beats = int(np.size(beats)) if 'np' in dir() else 0
        info(f"Essentia BPM: {bpm:.1f} (confidence: {avg_confidence:.2f}, {num_beats} beats)")
        if bpm > 0:
            return bpm
        return None

    except ImportError:
        debug("essentia not installed — trying librosa fallback")
        return None
    except Exception as e:
        warn(f"Essentia BPM detection failed: {e}")
        return None


def _detect_bpm_librosa(audio_path) -> float | None:
    """BPM detection using librosa (fallback)."""
    try:
        import librosa
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True, duration=60)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
        info(f"librosa BPM: {bpm:.1f}")
        return bpm
    except ImportError:
        warn("Neither essentia nor librosa available — cannot detect BPM")
        return None
    except Exception as e:
        warn(f"librosa BPM detection failed: {e}")
        return None


def generate_beat_grid(bpm: float, duration: float, time_signature: str = "4/4",
                       beat_offset_ms: float = 0.0) -> list[float]:
    """Generate list of beat timestamps in seconds."""
    beat_interval = 60.0 / bpm
    offset = beat_offset_ms / 1000.0
    beats = []
    t = offset
    while t <= duration:
        beats.append(round(t, 4))
        t += beat_interval
    return beats


def snap_to_nearest_beat(time_sec: float, beats: list[float],
                         tolerance_ms: float = 80.0, strength: float = 0.5) -> float:
    """Snap a timestamp to the nearest beat within tolerance."""
    if not beats:
        return time_sec

    tolerance = tolerance_ms / 1000.0
    nearest = min(beats, key=lambda b: abs(b - time_sec))
    distance = abs(nearest - time_sec)

    if distance <= tolerance:
        # blend between original and snapped based on strength
        return time_sec + (nearest - time_sec) * strength
    return time_sec


def snap_segments_to_grid(segments: list[TranscriptSegment], bpm: float,
                          duration: float, time_signature: str = "4/4",
                          beat_offset_ms: float = 0.0,
                          snap_tolerance_ms: float = 80.0,
                          snap_strength: float = 0.5) -> list[TranscriptSegment]:
    """Snap segment and word boundaries to BPM grid.

    Guardrails:
    - First segment always starts at 0.0 (intro is never lost)
    - Last segment extends to *duration* (tail is never lost)
    - Segments stay sorted by start time and gap-free
    """
    if not segments:
        return segments

    beats = generate_beat_grid(bpm, duration, time_signature, beat_offset_ms)
    if not beats:
        return segments

    info(f"Snapping to {bpm:.1f} BPM grid ({len(beats)} beats)")
    result = []
    for seg in segments:
        new_seg = deepcopy(seg)
        new_seg.start = snap_to_nearest_beat(seg.start, beats, snap_tolerance_ms, snap_strength)
        new_seg.end = snap_to_nearest_beat(seg.end, beats, snap_tolerance_ms, snap_strength)

        if new_seg.end <= new_seg.start:
            new_seg.end = new_seg.start + 0.1

        for w in new_seg.words:
            w.start = snap_to_nearest_beat(w.start, beats, snap_tolerance_ms, snap_strength)
            w.end = snap_to_nearest_beat(w.end, beats, snap_tolerance_ms, snap_strength)
            if w.end <= w.start:
                w.end = w.start + 0.05

        result.append(new_seg)

    # ── Guardrails ────────────────────────────────────────────────────────
    result.sort(key=lambda s: s.start)

    # C1: First segment must start at 0.0 — never lose the intro
    if result[0].start > 0.0:
        debug(f"BPM snap: clamping first segment start {result[0].start:.3f}s -> 0.0s")
        result[0].start = 0.0
        if result[0].words:
            result[0].words[0].start = 0.0

    # C1: Last segment must reach audio duration
    if duration > 0 and result[-1].end < duration:
        debug(f"BPM snap: extending last segment end {result[-1].end:.3f}s -> {duration:.3f}s")
        result[-1].end = duration
        if result[-1].words:
            result[-1].words[-1].end = duration

    # C2: Ensure segments are gap-free (close gaps introduced by snapping)
    for i in range(1, len(result)):
        if result[i].start > result[i - 1].end:
            result[i - 1].end = result[i].start
        elif result[i].start < result[i - 1].end:
            result[i].start = result[i - 1].end

    return result
