"""WhisperX transcription backend with forced word-level alignment.

WhisperX provides significantly better word-level timestamps than standard
Whisper through phoneme-based forced alignment (wav2vec2). It also includes
built-in VAD (silero) and optional speaker diarization.

Install: pip install whisperx torch
GPU recommended for reasonable speed.

CPU thread limiting (prevents system freeze on CPU-only machines):
    Config:  whisperx.cpu_threads  (0 = auto = half of cores)
    Env:     WHISPERX_THREADS      (overrides config)
    Affects: torch, OMP_NUM_THREADS, MKL_NUM_THREADS, OPENBLAS_NUM_THREADS
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


def _apply_thread_limits(cpu_threads: int = 0) -> int:
    """Set thread limits for torch/OMP/MKL BEFORE loading any models.

    Must be called before the first torch import or model load.
    Returns the effective thread count.
    """
    # Resolve thread count: env override > config > auto
    env_threads = os.environ.get("WHISPERX_THREADS", "")
    if env_threads.isdigit() and int(env_threads) > 0:
        threads = int(env_threads)
    elif cpu_threads > 0:
        threads = cpu_threads
    else:
        # Auto: half of cores, minimum 2, maximum 6
        cores = os.cpu_count() or 4
        threads = max(2, min(cores // 2, 6))

    # Set env vars BEFORE torch import (affects OpenMP, MKL, BLAS, CTranslate2)
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS",
                "CT2_INTER_THREADS", "CT2_INTRA_THREADS"):
        os.environ[var] = str(threads)

    # Set torch thread limits (if already imported)
    try:
        import torch
        torch.set_num_threads(threads)
        torch.set_num_interop_threads(max(1, threads // 2))
    except (ImportError, RuntimeError):
        pass  # torch not loaded yet or already initialized — env vars will apply

    info(f"WhisperX CPU thread limit: {threads} (cores={os.cpu_count()})")
    return threads


class WhisperXBackend(TranscriptionBackend):
    name = "whisperx"

    def __init__(self, model_size: str = "large-v3", device: str = "auto",
                 compute_type: str = "float16", batch_size: int = 16,
                 hf_token: str = "", cpu_threads: int = 0):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.batch_size = batch_size
        self.hf_token = hf_token or os.environ.get("HF_TOKEN", "")
        self.cpu_threads = cpu_threads
        self._model = None
        self._align_models: dict[str, Any] = {}
        self._threads_applied = False

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

    def _ensure_thread_limits(self) -> None:
        """Apply CPU thread limits once before first model load."""
        if not self._threads_applied:
            device = self._resolve_device()
            if device == "cpu":
                _apply_thread_limits(self.cpu_threads)
            self._threads_applied = True

    # Models too heavy for CPU — auto-downgrade to a practical model
    _CPU_MODEL_DOWNGRADE: dict[str, str] = {
        "large-v3": "medium",
        "large-v2": "medium",
        "large-v1": "medium",
        "large": "medium",
    }

    def _get_model(self):
        if self._model is None:
            self._ensure_thread_limits()
            import whisperx
            device = self._resolve_device()
            compute = self.compute_type if device == "cuda" else "int8"

            model_name = self.model_size
            effective_batch = self.batch_size

            if device == "cpu":
                # Auto-downgrade heavy models — large-v3 on CPU eats all RAM + cores
                downgrade = self._CPU_MODEL_DOWNGRADE.get(model_name)
                if downgrade:
                    warn(f"WhisperX: '{model_name}' too heavy for CPU, downgrading to '{downgrade}'")
                    model_name = downgrade
                # batch_size=1 on CPU to prevent multi-process CPU saturation
                effective_batch = 1
                info(f"WhisperX: batch_size set to {effective_batch} for CPU mode")

            self._effective_batch_size = effective_batch
            self._actual_model_name = model_name
            info(f"Loading WhisperX model: {model_name} on {device} ({compute})")
            self._model = whisperx.load_model(
                model_name,
                device=device,
                compute_type=compute,
                threads=max(1, int(os.environ.get("OMP_NUM_THREADS", "2"))),
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

    def unload(self) -> None:
        """Release all models from memory (WhisperX + alignment models)."""
        if self._model is not None:
            del self._model
            self._model = None
        if self._align_models:
            self._align_models.clear()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except (ImportError, RuntimeError):
            pass
        info("WhisperX models unloaded")

    def transcribe(self, audio_path: Path, language: str = "auto",
                   word_timestamps: bool = True, **kwargs: Any) -> TranscriptResult:
        ok, msg = self.check_available()
        if not ok:
            raise RuntimeError(f"WhisperX not available: {msg}")

        import whisperx

        device = self._resolve_device()
        model = self._get_model()
        actual_model = getattr(self, '_actual_model_name', self.model_size)
        info(f"Transcribing with WhisperX ({actual_model}): {audio_path.name}")

        start_time = time.time()

        # load audio
        audio = whisperx.load_audio(str(audio_path))

        # step 1: transcribe with whisper
        effective_batch = getattr(self, '_effective_batch_size', self.batch_size)
        transcribe_opts: dict[str, Any] = {"batch_size": effective_batch}
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
                # Keep pre-alignment result to validate alignment quality
                pre_align_segments = result["segments"]
                try:
                    aligned_result = whisperx.align(
                        pre_align_segments,
                        model_a,
                        metadata,
                        audio,
                        device,
                        return_char_alignments=False,
                    )
                    # Validate: check if alignment produced sane timestamps
                    if self._alignment_is_sane(aligned_result.get("segments", [])):
                        result = aligned_result
                        aligned = True
                        debug("WhisperX forced alignment complete")
                    else:
                        warn("WhisperX alignment produced aberrant timestamps, falling back to segment-level")
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

        # Post-transcription sanity: split absurdly long segments
        segments = self._sanitize_segment_durations(segments)

        info(f"WhisperX: {len(segments)} segments, "
             f"{'aligned' if aligned else 'segment-level'} timestamps, "
             f"language: {detected_lang}")

        return TranscriptResult(
            segments=segments,
            language=detected_lang,
            backend=self.name,
            duration=elapsed,
        )

    # ── Post-processing helpers ───────────────────────────────────────────

    @staticmethod
    def _alignment_is_sane(aligned_segs: list[dict]) -> bool:
        """Check if aligned segments have reasonable timestamps.

        Returns False if any segment has absurd duration relative to its
        word count (e.g. 114s for 3 words), which indicates alignment failure.
        """
        if not aligned_segs:
            return True
        for seg in aligned_segs:
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            duration = end - start
            words = seg.get("words", [])
            word_count = len(words) if words else max(1, len(seg.get("text", "").split()))
            if word_count == 0:
                continue
            # Max reasonable: ~3s per word (very slow speech). Anything beyond is broken.
            if duration > word_count * 3.0 and duration > 15.0:
                return False
        return True

    @staticmethod
    def _sanitize_segment_durations(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        """Split segments that are absurdly long relative to their word count.

        This catches cases where WhisperX produces e.g. a 114s segment for 3 words.
        Segments exceeding ~3s/word AND > 15s total are split into per-word segments
        (if word timestamps exist) or clamped to a reasonable duration.
        """
        result: list[TranscriptSegment] = []
        for seg in segments:
            duration = seg.end - seg.start
            words_text = seg.text.split()
            word_count = max(1, len(words_text))
            max_reasonable = max(15.0, word_count * 3.0)

            if duration <= max_reasonable:
                result.append(seg)
                continue

            # Segment is aberrant
            warn(f"WhisperX: aberrant segment {seg.start:.2f}-{seg.end:.2f} "
                 f"({duration:.1f}s, {word_count} words) — splitting/clamping")

            if seg.words and len(seg.words) >= 2:
                # Split into individual word-level segments
                for w in seg.words:
                    w_dur = w.end - w.start
                    # Also clamp individual words if needed
                    if w_dur > 5.0:
                        w = WordInfo(start=w.start, end=w.start + min(1.0, w_dur), word=w.word, confidence=w.confidence)
                    result.append(TranscriptSegment(
                        start=w.start, end=w.end, text=w.word,
                        words=[w], confidence=w.confidence,
                        has_word_timestamps=True,
                    ))
            else:
                # No word timestamps — clamp duration to reasonable estimate
                clamped_end = seg.start + min(word_count * 1.5, 10.0)
                result.append(TranscriptSegment(
                    start=seg.start, end=clamped_end, text=seg.text,
                    words=seg.words, confidence=seg.confidence * 0.5,
                    has_word_timestamps=seg.has_word_timestamps,
                ))
        return result
