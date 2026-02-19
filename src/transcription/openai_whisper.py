"""OpenAI Whisper v3 API transcription backend."""

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
from src.utils.logging import info, debug, error


class OpenAIWhisperBackend(TranscriptionBackend):
    name = "openai_whisper"

    def __init__(self, api_key: str | None = None, model: str = "whisper-1"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model

    def check_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "OPENAI_API_KEY not set"
        try:
            import openai  # noqa: F401
            return True, "OK"
        except ImportError:
            return False, "openai package not installed (pip install openai)"

    def transcribe(self, audio_path: Path, language: str = "auto",
                   word_timestamps: bool = True, **kwargs: Any) -> TranscriptResult:
        ok, msg = self.check_available()
        if not ok:
            raise RuntimeError(f"OpenAI Whisper not available: {msg}")

        from openai import OpenAI

        info(f"Transcribing with OpenAI Whisper: {audio_path.name}")
        client = OpenAI(api_key=self.api_key)

        start_time = time.time()
        with open(audio_path, "rb") as f:
            params: dict[str, Any] = {
                "model": self.model,
                "file": f,
                "response_format": "verbose_json",
                "timestamp_granularities": ["word", "segment"],
            }
            if language != "auto":
                params["language"] = language

            response = client.audio.transcriptions.create(**params)

        elapsed = time.time() - start_time
        debug(f"OpenAI Whisper response in {elapsed:.1f}s")

        data = response.model_dump() if hasattr(response, "model_dump") else dict(response)

        segments = []
        raw_segments = data.get("segments", [])
        raw_words = data.get("words", [])

        word_idx = 0
        for seg in raw_segments:
            seg_start = float(seg.get("start", 0))
            seg_end = float(seg.get("end", 0))
            seg_text = seg.get("text", "").strip()

            words: list[WordInfo] = []
            while word_idx < len(raw_words):
                w = raw_words[word_idx]
                w_start = float(w.get("start", 0))
                w_end = float(w.get("end", 0))
                if w_start >= seg_end:
                    break
                if w_start >= seg_start:
                    words.append(WordInfo(
                        start=w_start, end=w_end,
                        word=w.get("word", "").strip(),
                        confidence=1.0,
                    ))
                word_idx += 1

            segments.append(TranscriptSegment(
                start=seg_start, end=seg_end, text=seg_text,
                words=words,
                confidence=float(seg.get("avg_logprob", 0)) + 1.0,
                has_word_timestamps=bool(words),
            ))

        return TranscriptResult(
            segments=segments,
            language=data.get("language", language),
            backend=self.name,
            duration=elapsed,
            raw_output=data,
        )
