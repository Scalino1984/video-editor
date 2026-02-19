"""BPM-Grid snap for aligning subtitle timestamps to musical beats."""

from __future__ import annotations

from copy import deepcopy

from src.transcription.base import TranscriptSegment
from src.utils.logging import info, debug, warn


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
        avg_confidence = float(beats_confidence.mean()) if len(beats_confidence) > 0 else 0

        info(f"Essentia BPM: {bpm:.1f} (confidence: {avg_confidence:.2f}, {len(beats)} beats)")
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
    """Snap segment and word boundaries to BPM grid."""
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

    return result
