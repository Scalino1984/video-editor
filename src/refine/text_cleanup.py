"""Text cleanup and correction pipeline for transcription output."""

from __future__ import annotations

import re
from pathlib import Path

from src.transcription.base import TranscriptSegment


def normalize_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_quotes(text: str) -> str:
    text = text.replace("``", '"').replace("''", '"')
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    return text


def normalize_punctuation(text: str) -> str:
    text = text.replace("...", "\u2026")
    text = re.sub(r"\.{2,}", "\u2026", text)
    text = re.sub(r"-{2,}", "\u2014", text)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return text


def capitalize_sentences(text: str) -> str:
    if not text:
        return text
    result = text[0].upper() + text[1:]
    result = re.sub(r"([.!?]\s+)(\w)", lambda m: m.group(1) + m.group(2).upper(), result)
    return result


_compiled_patterns: dict[str, re.Pattern] = {}


def _get_pattern(word: str) -> re.Pattern:
    if word not in _compiled_patterns:
        _compiled_patterns[word] = re.compile(re.escape(word), re.IGNORECASE)
    return _compiled_patterns[word]


def apply_dictionary(text: str, dictionary: dict[str, str]) -> str:
    for wrong, correct in dictionary.items():
        pattern = _get_pattern(wrong)
        text = pattern.sub(correct, text)
    return text


def load_dictionary(path: str | Path) -> dict[str, str]:
    d: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return d
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("=", 1)
            if len(parts) == 2:
                d[parts[0].strip()] = parts[1].strip()
    return d


def clean_segment_text(text: str, dictionary: dict[str, str] | None = None,
                       capitalize: bool = True) -> str:
    text = normalize_whitespace(text)
    text = normalize_quotes(text)
    text = normalize_punctuation(text)
    if dictionary:
        text = apply_dictionary(text, dictionary)
    if capitalize:
        text = capitalize_sentences(text)
    return text


def clean_all_segments(segments: list[TranscriptSegment],
                       dictionary: dict[str, str] | None = None,
                       capitalize: bool = True) -> list[TranscriptSegment]:
    for seg in segments:
        seg.text = clean_segment_text(seg.text, dictionary, capitalize)
        for w in seg.words:
            w.word = normalize_whitespace(w.word)
    return segments
