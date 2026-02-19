"""Local Whisper v3 transcription backend using faster-whisper."""

from __future__ import annotations

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


class LocalWhisperBackend(TranscriptionBackend):
    name = "local_whisper"

    def __init__(self, model_size: str = "large-v3", device: str = "auto",
                 compute_type: str = "float16"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def check_available(self) -> tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
            return True, "OK"
        except ImportError:
            return False, "faster-whisper not installed (pip install faster-whisper)"

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            info(f"Loading Whisper model: {self.model_size}")
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def transcribe(self, audio_path: Path, language: str = "auto",
                   word_timestamps: bool = True, **kwargs: Any) -> TranscriptResult:
        ok, msg = self.check_available()
        if not ok:
            raise RuntimeError(f"Local Whisper not available: {msg}")

        info(f"Transcribing with local Whisper: {audio_path.name}")
        model = self._get_model()

        start_time = time.time()
        lang = language if language != "auto" else None

        raw_segments, detect_info = model.transcribe(
            str(audio_path),
            language=lang,
            word_timestamps=word_timestamps,
            beam_size=5,
            vad_filter=True,
        )

        detected_lang = detect_info.language if hasattr(detect_info, "language") else language

        segments = []
        for seg in raw_segments:
            words: list[WordInfo] = []
            if seg.words:
                for w in seg.words:
                    words.append(WordInfo(
                        start=w.start,
                        end=w.end,
                        word=w.word.strip(),
                        confidence=w.probability if hasattr(w, "probability") else 0.9,
                    ))

            segments.append(TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                words=words,
                confidence=float(seg.avg_logprob + 1.0) if seg.avg_logprob else 0.8,
                has_word_timestamps=bool(words),
            ))

        elapsed = time.time() - start_time
        debug(f"Local Whisper completed in {elapsed:.1f}s")

        return TranscriptResult(
            segments=segments,
            language=detected_lang,
            backend=self.name,
            duration=elapsed,
        )
