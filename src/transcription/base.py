"""Base transcription interface — all backends implement this contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WordInfo:
    start: float
    end: float
    word: str
    confidence: float = 1.0


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: list[WordInfo] = field(default_factory=list)
    confidence: float = 1.0
    has_word_timestamps: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "confidence": self.confidence,
            "has_word_timestamps": self.has_word_timestamps,
            "words": [
                {"start": w.start, "end": w.end, "word": w.word, "confidence": w.confidence}
                for w in self.words
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TranscriptSegment:
        words = [WordInfo(**w) for w in d.get("words", [])]
        return cls(
            start=d["start"],
            end=d["end"],
            text=d["text"],
            confidence=d.get("confidence", 1.0),
            has_word_timestamps=d.get("has_word_timestamps", bool(words)),
            words=words,
        )


@dataclass
class TranscriptResult:
    segments: list[TranscriptSegment]
    language: str = "unknown"
    backend: str = "unknown"
    duration: float = 0.0
    raw_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "language": self.language,
            "duration": self.duration,
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TranscriptResult:
        return cls(
            backend=d.get("backend", "unknown"),
            language=d.get("language", "unknown"),
            duration=d.get("duration", 0.0),
            segments=[TranscriptSegment.from_dict(s) for s in d.get("segments", [])],
        )


class TranscriptionBackend(ABC):
    name: str = "base"

    @abstractmethod
    def transcribe(self, audio_path: Path, language: str = "auto",
                   word_timestamps: bool = True, **kwargs: Any) -> TranscriptResult:
        ...

    def check_available(self) -> tuple[bool, str]:
        return True, "OK"
