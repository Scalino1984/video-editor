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


def _safe_get(obj, key, default=None):
    """Safely get attribute from dict or object (SDK may return either)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class VoxtralBackend(TranscriptionBackend):
    name = "voxtral"

    def __init__(self, api_key: str | None = None, model: str = "voxtral-mini-latest",
                 diarize: bool = True):
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        self.model = model
        self.diarize = diarize

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
                segments.append({
                    "start": float(_safe_get(s, "start", 0.0) or 0.0),
                    "end": float(_safe_get(s, "end", 0.0) or 0.0),
                    "text": (_safe_get(s, "text", "") or "").strip(),
                    "speaker": _safe_get(s, "speaker", None),
                })
            return segments

        # try .data.segments (alternative response structure)
        data = _safe_get(transcription, "data")
        data_segments = _safe_get(data, "segments") if data else None
        if data_segments:
            for s in data_segments:
                segments.append({
                    "start": float(_safe_get(s, "start", 0.0) or 0.0),
                    "end": float(_safe_get(s, "end", 0.0) or 0.0),
                    "text": (_safe_get(s, "text", "") or "").strip(),
                    "speaker": _safe_get(s, "speaker", None),
                })
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

        try:
            with audio_path.open("rb") as f:
                file_data = f.read()

            info(f"  Sending to Mistral API...")
            transcription = client.audio.transcriptions.complete(
                model=self.model,
                file={
                    "content": file_data,
                    "file_name": audio_path.name,
                },
                diarize=self.diarize,
                timestamp_granularities=["segment"],
            )
        except Exception as e:
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

            # Voxtral liefert segment-level timestamps, keine word-level
            # → Words werden spaeter im Alignment-Schritt approximiert
            # Speaker-Info in Text einbauen wenn vorhanden
            if speaker:
                text = f"[{speaker}] {text}"

            segments.append(TranscriptSegment(
                start=seg_start,
                end=seg_end,
                text=text,
                words=[],
                confidence=0.9,  # Voxtral liefert keine Confidence-Werte
                has_word_timestamps=False,
            ))

        detected_language = language
        lang_attr = _safe_get(transcription, "language")
        if lang_attr and isinstance(lang_attr, str):
            detected_language = lang_attr

        info(f"Voxtral: {len(segments)} Segmente, Sprache: {detected_language}")

        return TranscriptResult(
            segments=segments,
            language=detected_language,
            backend=self.name,
            duration=elapsed,
        )
