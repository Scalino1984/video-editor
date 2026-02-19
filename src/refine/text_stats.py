"""Segment text statistics — vocabulary richness, word frequency, etc.

Analyzes transcribed text for:
- Vocabulary diversity (type-token ratio, hapax legomena)
- Word frequency distribution
- Average word/sentence length
- Language-specific metrics
- Flow analysis (syllable patterns for rap/poetry)
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from src.utils.logging import info


# Approximate syllable counter (works for German & English)
_VOWEL_RE = re.compile(r"[aeiouyäöü]+", re.IGNORECASE)

def _count_syllables(word: str) -> int:
    """Approximate syllable count."""
    w = word.lower().strip()
    if not w:
        return 0
    matches = _VOWEL_RE.findall(w)
    count = len(matches)
    # Adjustments
    if w.endswith("e") and count > 1:
        count -= 1  # silent e
    if w.endswith("le") and count == 0:
        count = 1
    return max(1, count)


@dataclass
class TextStats:
    """Complete text statistics for a transcription."""
    total_words: int
    unique_words: int
    total_chars: int
    total_syllables: int
    total_lines: int
    avg_words_per_line: float
    avg_word_length: float
    avg_syllables_per_word: float
    type_token_ratio: float          # unique/total — vocabulary richness
    hapax_legomena: int              # words appearing exactly once
    hapax_ratio: float               # hapax/unique
    top_words: list[tuple[str, int]]  # most frequent words
    top_bigrams: list[tuple[str, int]]
    syllable_distribution: dict[int, int]  # syllable_count → word_count
    flow_score: float                # rhythmic consistency (0-1)
    reading_time_sec: float          # estimated reading time

    def to_dict(self) -> dict:
        return {
            "total_words": self.total_words,
            "unique_words": self.unique_words,
            "total_chars": self.total_chars,
            "total_syllables": self.total_syllables,
            "total_lines": self.total_lines,
            "avg_words_per_line": round(self.avg_words_per_line, 1),
            "avg_word_length": round(self.avg_word_length, 1),
            "avg_syllables_per_word": round(self.avg_syllables_per_word, 2),
            "type_token_ratio": round(self.type_token_ratio, 3),
            "hapax_legomena": self.hapax_legomena,
            "hapax_ratio": round(self.hapax_ratio, 3),
            "top_words": [{"word": w, "count": c} for w, c in self.top_words],
            "top_bigrams": [{"bigram": b, "count": c} for b, c in self.top_bigrams],
            "syllable_distribution": self.syllable_distribution,
            "flow_score": round(self.flow_score, 2),
            "reading_time_sec": round(self.reading_time_sec, 1),
        }


def _tokenize(text: str) -> list[str]:
    """Extract word tokens from text."""
    return [w for w in re.findall(r"[\wäöüß']+", text.lower()) if len(w) > 0]


def _get_bigrams(words: list[str]) -> list[str]:
    """Get word bigrams."""
    return [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]


def analyze_text_stats(
    lines: list[str],
    top_n: int = 20,
    stop_words: set[str] | None = None,
) -> TextStats:
    """Analyze text statistics for a list of lines.

    Args:
        lines: Text lines (one per segment)
        top_n: Number of top words/bigrams to return
        stop_words: Words to exclude from frequency analysis
    """
    if stop_words is None:
        stop_words = {
            # German
            "ich", "du", "er", "sie", "es", "wir", "ihr", "die", "der", "das",
            "den", "dem", "des", "ein", "eine", "einen", "einem", "einer",
            "und", "oder", "aber", "auch", "noch", "schon", "mal", "nur",
            "ist", "bin", "bist", "sind", "hat", "hab", "haben", "war",
            "nicht", "kein", "keine", "keinen", "auf", "in", "mit", "von",
            "zu", "an", "für", "bei", "nach", "aus", "um", "wie", "so",
            "wenn", "weil", "dass", "was", "wer", "wo", "hier", "da",
            "mein", "dein", "sein", "ihr",
            # English
            "the", "a", "an", "is", "am", "are", "was", "were", "be",
            "to", "of", "and", "in", "that", "it", "for", "on", "with",
            "i", "you", "he", "she", "we", "they", "my", "your", "his",
            "her", "its", "our", "this", "not", "but", "or", "so",
        }

    all_words: list[str] = []
    line_word_counts: list[int] = []
    line_syllable_counts: list[int] = []

    for line in lines:
        tokens = _tokenize(line)
        all_words.extend(tokens)
        line_word_counts.append(len(tokens))
        line_syllable_counts.append(sum(_count_syllables(w) for w in tokens))

    if not all_words:
        return TextStats(0, 0, 0, 0, len(lines), 0, 0, 0, 0, 0, 0,
                         [], [], {}, 0, 0)

    n = len(all_words)
    word_freq = Counter(all_words)
    unique = len(word_freq)
    hapax = sum(1 for w, c in word_freq.items() if c == 1)

    # Syllable analysis
    syllable_counts = [_count_syllables(w) for w in all_words]
    total_syllables = sum(syllable_counts)
    syl_dist = Counter(syllable_counts)

    # Top words (excluding stop words)
    content_freq = Counter(w for w in all_words if w not in stop_words and len(w) > 1)
    top_words = content_freq.most_common(top_n)

    # Bigrams
    bigrams = _get_bigrams(all_words)
    bigram_freq = Counter(bigrams)
    top_bigrams = bigram_freq.most_common(top_n)

    # Flow score: how consistent are line lengths (syllable-based)
    if len(line_syllable_counts) >= 2:
        avg_syl = sum(line_syllable_counts) / len(line_syllable_counts)
        if avg_syl > 0:
            variance = sum((s - avg_syl) ** 2 for s in line_syllable_counts) / len(line_syllable_counts)
            cv = (variance ** 0.5) / avg_syl  # coefficient of variation
            flow = max(0.0, 1.0 - cv)  # lower variation = higher flow
        else:
            flow = 0.0
    else:
        flow = 0.5

    stats = TextStats(
        total_words=n,
        unique_words=unique,
        total_chars=sum(len(w) for w in all_words),
        total_syllables=total_syllables,
        total_lines=len(lines),
        avg_words_per_line=n / max(len(lines), 1),
        avg_word_length=sum(len(w) for w in all_words) / n,
        avg_syllables_per_word=total_syllables / n,
        type_token_ratio=unique / n,
        hapax_legomena=hapax,
        hapax_ratio=hapax / max(unique, 1),
        top_words=top_words,
        top_bigrams=top_bigrams,
        syllable_distribution=dict(sorted(syl_dist.items())),
        flow_score=flow,
        reading_time_sec=n / 3.5,  # ~3.5 words/sec for singing
    )

    info(f"Text stats: {n} words, {unique} unique, TTR={stats.type_token_ratio:.3f}, "
         f"flow={flow:.2f}")

    return stats
