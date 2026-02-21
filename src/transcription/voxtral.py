"""Voxtral transcription backend via official Mistral AI SDK.

Uses client.audio.transcriptions.complete() with voxtral-mini-latest.
Reference implementation: vox_studio.py
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from src.transcription.base import (
    TranscriptionBackend,
    TranscriptResult,
    TranscriptSegment,
    WordInfo,
)
from src.utils.logging import info, debug, warn, error

# Segment duration sanity thresholds
_MAX_SEC_PER_WORD = 8.0  # max seconds per word before flagging
_ABS_MAX_SEGMENT_SEC = 120.0  # absolute max segment duration


def _safe_get(obj, key, default=None):
    """Safely get attribute from dict or object (SDK may return either)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _load_context_bias(custom_words_path: str | Path = "custom_words.txt", max_terms: int = 100) -> list[str] | None:
    """Load context_bias terms from custom_words.txt for Voxtral API.

    Extracts the *correct* spellings from 'wrong=correct' pairs plus
    any standalone lines (non-comment, no '=' sign) as direct bias terms.
    Returns None if no terms found or file missing.
    """
    p = Path(custom_words_path)
    if not p.exists():
        return None
    terms: list[str] = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("=", 1)
                if len(parts) == 2:
                    # Add the correct spelling as bias
                    correct = parts[1].strip()
                    if correct:
                        terms.append(correct)
                else:
                    # Standalone term (no '=' sign) — use directly
                    terms.append(line)
    except OSError:
        return None
    if not terms:
        return None
    # Mistral API supports up to 100 terms
    return terms[:max_terms]


class VoxtralBackend(TranscriptionBackend):
    name = "voxtral"

    def __init__(self, api_key: str | None = None, model: str = "voxtral-mini-latest",
                 diarize: bool = True, temperature: float = 0.0):
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self.model = model
        self.diarize = diarize
        self.temperature = temperature

    def check_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "MISTRAL_API_KEY not set"
        try:
            from mistralai import Mistral  # noqa: F401
            return True, "OK"
        except ImportError:
            return False, "mistralai package not installed (pip install mistralai)"

    def _extract_segments(self, transcription) -> list[dict]:
        """Extract segments from transcription response (handles SDK object or dict)."""
        segments = []

        # try direct .segments
        direct_segments = _safe_get(transcription, "segments")
        if direct_segments:
            for s in direct_segments:
                seg = {
                    "start": float(_safe_get(s, "start", 0.0) or 0.0),
                    "end": float(_safe_get(s, "end", 0.0) or 0.0),
                    "text": (_safe_get(s, "text", "") or "").strip(),
                    "speaker": _safe_get(s, "speaker", None),
                }
                # Extract word-level timestamps if available
                words_raw = _safe_get(s, "words")
                if words_raw:
                    seg["words"] = [
                        {
                            "start": float(_safe_get(w, "start", 0.0) or 0.0),
                            "end": float(_safe_get(w, "end", 0.0) or 0.0),
                            "word": (_safe_get(w, "text", "") or _safe_get(w, "word", "") or "").strip(),
                        }
                        for w in words_raw
                    ]
                segments.append(seg)
            return segments

        # try .data.segments (alternative response structure)
        data = _safe_get(transcription, "data")
        data_segments = _safe_get(data, "segments") if data else None
        if data_segments:
            for s in data_segments:
                seg = {
                    "start": float(_safe_get(s, "start", 0.0) or 0.0),
                    "end": float(_safe_get(s, "end", 0.0) or 0.0),
                    "text": (_safe_get(s, "text", "") or "").strip(),
                    "speaker": _safe_get(s, "speaker", None),
                }
                words_raw = _safe_get(s, "words")
                if words_raw:
                    seg["words"] = [
                        {
                            "start": float(_safe_get(w, "start", 0.0) or 0.0),
                            "end": float(_safe_get(w, "end", 0.0) or 0.0),
                            "word": (_safe_get(w, "text", "") or _safe_get(w, "word", "") or "").strip(),
                        }
                        for w in words_raw
                    ]
                segments.append(seg)
            return segments

        return segments

    def _extract_full_text(self, transcription, segments: list[dict]) -> str:
        """Extract full text from transcription response."""
        t = _safe_get(transcription, "text")
        if isinstance(t, str) and t.strip():
            return t.strip()
        return "\n".join(s["text"] for s in segments if s.get("text"))

    def transcribe(self, audio_path: Path, language: str = "auto",
                   word_timestamps: bool = True, **kwargs: Any) -> TranscriptResult:
        ok, msg = self.check_available()
        if not ok:
            raise RuntimeError(f"Voxtral not available: {msg}")

        from mistralai import Mistral

        info(f"Transcribing with Voxtral ({self.model}): {audio_path.name}")
        client = Mistral(api_key=self.api_key, timeout_ms=300_000)  # 5 min timeout

        start_time = time.time()

        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        info(f"  File size: {file_size_mb:.1f} MB")

        # ── Build API parameters ──────────────────────────────────────
        # Mistral API constraint: diarize=True requires granularity="segment".
        # Word-level timestamps require diarize=False.
        if word_timestamps:
            granularities = ["word", "segment"]  # request both like OpenAI
            use_diarize = False
        else:
            granularities = ["segment"]
            use_diarize = self.diarize

        api_params: dict[str, Any] = {
            "model": self.model,
            "diarize": use_diarize,
            "timestamp_granularities": granularities,
            "temperature": self.temperature,
        }

        # Mistral API: timestamp_granularities is currently NOT compatible with language.
        # When timestamps are requested, skip language to avoid silent parameter drop.
        lang_for_api = language if language != "auto" else None
        if lang_for_api and granularities:
            warn(f"Voxtral: language='{lang_for_api}' + timestamp_granularities are "
                 "incompatible per Mistral API docs — skipping language parameter "
                 "(relying on auto-detection for better timestamp quality)")
            lang_for_api = None
        if lang_for_api:
            api_params["language"] = lang_for_api

        # context_bias: pass domain-specific terms from custom_words.txt
        context_bias = kwargs.get("context_bias") or _load_context_bias()
        if context_bias:
            api_params["context_bias"] = context_bias
            info(f"  Context bias: {len(context_bias)} terms")

        try:
            with audio_path.open("rb") as f:
                file_data = f.read()

            info(f"  Sending to Mistral API...")
            transcription = client.audio.transcriptions.complete(
                file={
                    "content": file_data,
                    "file_name": audio_path.name,
                },
                **api_params,
            )
        except Exception as e:
            # Fallback: if dual granularity fails, retry with single "word" only
            if word_timestamps and len(granularities) > 1:
                warn(f"Voxtral: dual granularity failed ({e}), retrying with 'word' only")
                api_params["timestamp_granularities"] = ["word"]
                try:
                    with audio_path.open("rb") as f:
                        file_data = f.read()
                    transcription = client.audio.transcriptions.complete(
                        file={
                            "content": file_data,
                            "file_name": audio_path.name,
                        },
                        **api_params,
                    )
                except Exception as e2:
                    error(f"Voxtral transcription failed: {e2}")
                    error(f"  (file: {audio_path.name}, size: {file_size_mb:.1f} MB)")
                    raise RuntimeError(f"Voxtral API error: {e2}") from e2
            else:
                error(f"Voxtral transcription failed: {e}")
                error(f"  (file: {audio_path.name}, size: {file_size_mb:.1f} MB)")
                raise RuntimeError(f"Voxtral API error: {e}") from e

        elapsed = time.time() - start_time
        debug(f"Voxtral response in {elapsed:.1f}s")

        # extract segments (handles both dict and SDK object responses)
        raw_segments = self._extract_segments(transcription)
        full_text = self._extract_full_text(transcription, raw_segments)

        if not raw_segments:
            warn("No segments with timestamps returned — creating single segment from full text")
            if full_text:
                return TranscriptResult(
                    segments=[TranscriptSegment(start=0, end=0, text=full_text)],
                    language=language if language != "auto" else "unknown",
                    backend=self.name,
                    duration=elapsed,
                )
            raise RuntimeError("Voxtral returned no text and no segments")

        # convert to our segment format
        segments: list[TranscriptSegment] = []
        for raw in raw_segments:
            text = raw["text"]
            if not text:
                continue

            seg_start = raw["start"]
            seg_end = raw["end"]
            speaker = raw.get("speaker")

            # Speaker-Info in Text einbauen wenn vorhanden
            if speaker:
                text = f"[{speaker}] {text}"

            # Word-level timestamps from Voxtral (if granularity includes "word")
            words: list[WordInfo] = []
            if raw.get("words"):
                for w in raw["words"]:
                    word_text = w.get("word", "").strip()
                    if word_text:
                        words.append(WordInfo(
                            start=w["start"],
                            end=w["end"],
                            word=word_text,
                            confidence=0.9,
                        ))

            segments.append(TranscriptSegment(
                start=seg_start,
                end=seg_end,
                text=text,
                words=words,
                confidence=0.9,  # Voxtral liefert keine Confidence-Werte
                has_word_timestamps=bool(words),
            ))

        detected_language = language
        lang_attr = _safe_get(transcription, "language")
        if lang_attr and isinstance(lang_attr, str):
            detected_language = lang_attr

        # ── Post-processing: sanitize segment durations ────────────
        segments = self._sanitize_segment_durations(segments)

        # Diagnostic: log time range for coverage analysis
        if segments:
            info(f"Voxtral: {len(segments)} Segmente, Sprache: {detected_language}, "
                 f"range: {segments[0].start:.1f}s – {segments[-1].end:.1f}s"
                 + (f", word_timestamps: {segments[0].has_word_timestamps}" if segments else ""))
        else:
            info(f"Voxtral: 0 Segmente, Sprache: {detected_language}")

        return TranscriptResult(
            segments=segments,
            language=detected_language,
            backend=self.name,
            duration=elapsed,
        )

    # ── Post-processing helpers ───────────────────────────────────────

    @staticmethod
    def _sanitize_segment_durations(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        """Split absurdly long segments that indicate hallucination or alignment failure."""
        result: list[TranscriptSegment] = []
        for seg in segments:
            duration = seg.end - seg.start
            word_count = len(seg.text.split())
            if word_count == 0:
                continue

            # Flag if segment is absurdly long relative to word count
            if duration > _ABS_MAX_SEGMENT_SEC or (word_count > 0 and duration / word_count > _MAX_SEC_PER_WORD):
                warn(f"Voxtral: overlong segment ({duration:.1f}s, {word_count} words) — "
                     f"lowering confidence: '{seg.text[:60]}...'")
                seg.confidence = min(seg.confidence, 0.3)

            result.append(seg)
        return result
