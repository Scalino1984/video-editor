"""WhisperX transcription backend with forced word-level alignment.

WhisperX provides significantly better word-level timestamps than standard
Whisper through phoneme-based forced alignment (wav2vec2). It also includes
built-in VAD (silero) and optional speaker diarization.

Install: pip install whisperx torch
GPU recommended for reasonable speed.
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


class WhisperXBackend(TranscriptionBackend):
    name = "whisperx"

    def __init__(self, model_size: str = "large-v3", device: str = "auto",
                 compute_type: str = "float16", batch_size: int = 16,
                 hf_token: str = ""):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.batch_size = batch_size
        self.hf_token = hf_token or os.environ.get("HF_TOKEN", "")
        self._model = None
        self._align_models: dict[str, Any] = {}

    def check_available(self) -> tuple[bool, str]:
        try:
            import whisperx  # noqa: F401
            return True, "OK"
        except ImportError:
            return False, "whisperx not installed (pip install whisperx)"

    def _resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _get_model(self):
        if self._model is None:
            import whisperx
            device = self._resolve_device()
            compute = self.compute_type if device == "cuda" else "int8"
            info(f"Loading WhisperX model: {self.model_size} on {device} ({compute})")
            self._model = whisperx.load_model(
                self.model_size,
                device=device,
                compute_type=compute,
            )
        return self._model

    def _get_align_model(self, language: str, device: str):
        if language not in self._align_models:
            import whisperx
            info(f"Loading alignment model for '{language}'")
            try:
                model_a, metadata = whisperx.load_align_model(
                    language_code=language,
                    device=device,
                )
                self._align_models[language] = (model_a, metadata)
            except Exception as e:
                warn(f"Could not load alignment model for '{language}': {e}")
                return None, None
        return self._align_models[language]

    def transcribe(self, audio_path: Path, language: str = "auto",
                   word_timestamps: bool = True, **kwargs: Any) -> TranscriptResult:
        ok, msg = self.check_available()
        if not ok:
            raise RuntimeError(f"WhisperX not available: {msg}")

        import whisperx

        device = self._resolve_device()
        info(f"Transcribing with WhisperX ({self.model_size}): {audio_path.name}")

        start_time = time.time()

        # load audio
        audio = whisperx.load_audio(str(audio_path))

        # step 1: transcribe with whisper
        model = self._get_model()
        transcribe_opts: dict[str, Any] = {"batch_size": self.batch_size}
        if language != "auto":
            transcribe_opts["language"] = language

        result = model.transcribe(audio, **transcribe_opts)
        detected_lang = result.get("language", language if language != "auto" else "en")
        debug(f"WhisperX transcription done, detected language: {detected_lang}")

        # step 2: forced alignment for word-level timestamps
        aligned = False
        if word_timestamps:
            model_a, metadata = self._get_align_model(detected_lang, device)
            if model_a is not None:
                try:
                    result = whisperx.align(
                        result["segments"],
                        model_a,
                        metadata,
                        audio,
                        device,
                        return_char_alignments=False,
                    )
                    aligned = True
                    debug("WhisperX forced alignment complete")
                except Exception as e:
                    warn(f"Alignment failed, using segment-level timestamps: {e}")

        # step 3 (optional): speaker diarization
        diarize_segments = None
        if self.hf_token and kwargs.get("diarize", False):
            try:
                diarize_model = whisperx.DiarizationPipeline(
                    use_auth_token=self.hf_token,
                    device=device,
                )
                diarize_segments = diarize_model(audio)
                result = whisperx.assign_word_speakers(diarize_segments, result)
                debug("WhisperX diarization complete")
            except Exception as e:
                warn(f"Diarization failed: {e}")

        elapsed = time.time() - start_time

        # convert to our format
        segments: list[TranscriptSegment] = []
        for seg in result.get("segments", []):
            seg_start = float(seg.get("start", 0))
            seg_end = float(seg.get("end", 0))
            text = seg.get("text", "").strip()
            if not text:
                continue

            speaker = seg.get("speaker")
            if speaker:
                text = f"[{speaker}] {text}"

            words: list[WordInfo] = []
            raw_words = seg.get("words", [])
            for w in raw_words:
                w_start = w.get("start")
                w_end = w.get("end")
                w_word = w.get("word", "").strip()
                w_score = w.get("score", 0.9)

                if w_start is not None and w_end is not None and w_word:
                    words.append(WordInfo(
                        start=float(w_start),
                        end=float(w_end),
                        word=w_word,
                        confidence=float(w_score) if w_score else 0.8,
                    ))

            has_words = bool(words) and aligned
            segments.append(TranscriptSegment(
                start=seg_start,
                end=seg_end,
                text=text,
                words=words,
                confidence=sum(w.confidence for w in words) / len(words) if words else 0.85,
                has_word_timestamps=has_words,
            ))

        info(f"WhisperX: {len(segments)} segments, "
             f"{'aligned' if aligned else 'segment-level'} timestamps, "
             f"language: {detected_lang}")

        return TranscriptResult(
            segments=segments,
            language=detected_lang,
            backend=self.name,
            duration=elapsed,
        )
