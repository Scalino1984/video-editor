"""Rhyme scheme detection for lyrics segments.

Analyzes end-rhymes, internal rhymes, and multisyllabic patterns.
Optimized for German rap with support for Reimketten, Doppelreime, etc.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations

from src.utils.logging import info, debug


# ── Phonetic helpers (simplified German/English) ──────────────────────────────

# German vowel digraphs and common endings
_VOWEL_GROUPS = re.compile(r"[aeiouyäöü]+", re.IGNORECASE)
_CONSONANT_STRIP = re.compile(r"^[^aeiouyäöü]*", re.IGNORECASE)

# Common German suffixes that don't affect rhyme quality
_WEAK_SUFFIXES = {"en", "er", "es", "em", "et", "ung", "heit", "keit", "lich", "isch"}

# Phonetic equivalences for German
_PHONETIC_MAP = {
    "ph": "f", "ck": "k", "th": "t", "dt": "t", "tz": "z",
    "ss": "s", "ß": "s", "ae": "ä", "oe": "ö", "ue": "ü",
    "ei": "ai", "ey": "ai", "ay": "ai",
    "eu": "oi", "äu": "oi",
    "ie": "ii", "ih": "ii", "ieh": "ii",
    "ah": "aa", "eh": "ee", "oh": "oo", "uh": "uu",
}


def _normalize_phonetic(word: str) -> str:
    """Rough phonetic normalization for rhyme comparison."""
    w = word.lower().strip()
    w = unicodedata.normalize("NFC", w)
    w = re.sub(r"[^a-zäöüß]", "", w)
    for old, new in _PHONETIC_MAP.items():
        w = w.replace(old, new)
    return w


def _get_rhyme_tail(word: str, min_chars: int = 2) -> str:
    """Extract the rhyming tail of a word (from last stressed vowel onward)."""
    p = _normalize_phonetic(word)
    if len(p) < min_chars:
        return p

    # Find last vowel cluster position
    vowels = list(_VOWEL_GROUPS.finditer(p))
    if not vowels:
        return p[-min_chars:]

    # For multisyllabic: use from second-to-last vowel if available
    if len(vowels) >= 2:
        return p[vowels[-2].start():]
    return p[vowels[-1].start():]


def _get_end_word(line: str) -> str:
    """Extract the last meaningful word from a line."""
    words = re.findall(r"[\wäöüß]+", line, re.IGNORECASE)
    if not words:
        return ""
    # Skip trailing weak words
    w = words[-1]
    if len(words) >= 2 and len(w) <= 3:
        return words[-2]
    return w


def _rhyme_score(word_a: str, word_b: str) -> float:
    """Score how well two words rhyme (0.0 – 1.0)."""
    if not word_a or not word_b:
        return 0.0
    a = _normalize_phonetic(word_a)
    b = _normalize_phonetic(word_b)
    if a == b:
        return 0.3  # identical words aren't real rhymes

    tail_a = _get_rhyme_tail(word_a)
    tail_b = _get_rhyme_tail(word_b)

    if not tail_a or not tail_b:
        return 0.0

    # Exact tail match
    if tail_a == tail_b:
        return 1.0

    # Suffix match (last N chars)
    max_len = min(len(tail_a), len(tail_b))
    common = 0
    for i in range(1, max_len + 1):
        if tail_a[-i] == tail_b[-i]:
            common += 1
        else:
            break

    if common >= 3:
        return 0.9
    elif common >= 2:
        return 0.7
    elif common >= 1:
        return 0.4

    # Fuzzy phonetic similarity
    return SequenceMatcher(None, tail_a, tail_b).ratio() * 0.6


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class RhymePair:
    """A detected rhyme between two lines."""
    line_a: int
    line_b: int
    word_a: str
    word_b: str
    score: float
    rhyme_type: str  # "end" | "internal" | "multi"

@dataclass
class RhymeScheme:
    """Full rhyme analysis for a set of lyrics lines."""
    total_lines: int
    scheme_labels: list[str]       # e.g. ["A", "B", "A", "B"]
    scheme_pattern: str            # e.g. "ABAB"
    rhyme_pairs: list[RhymePair]
    rhyme_density: float           # ratio of rhyming lines
    internal_rhymes: list[RhymePair]
    multi_rhymes: list[RhymePair]  # multisyllabic rhymes

    def to_dict(self) -> dict:
        return {
            "total_lines": self.total_lines,
            "scheme": self.scheme_pattern,
            "labels": self.scheme_labels,
            "density": round(self.rhyme_density, 2),
            "pairs": [
                {"a": p.line_a, "b": p.line_b, "words": [p.word_a, p.word_b],
                 "score": round(p.score, 2), "type": p.rhyme_type}
                for p in self.rhyme_pairs
            ],
            "internal": [
                {"a": p.line_a, "b": p.line_b, "words": [p.word_a, p.word_b],
                 "score": round(p.score, 2)}
                for p in self.internal_rhymes
            ],
            "multi": [
                {"a": p.line_a, "b": p.line_b, "words": [p.word_a, p.word_b],
                 "score": round(p.score, 2)}
                for p in self.multi_rhymes
            ],
        }


# ── Main analysis ─────────────────────────────────────────────────────────────

def detect_rhyme_scheme(
    lines: list[str],
    threshold: float = 0.6,
    window: int = 8,
) -> RhymeScheme:
    """Detect rhyme scheme in lyrics lines.

    Args:
        lines: Text lines to analyze
        threshold: Minimum rhyme score to count as a rhyme
        window: How many lines forward to look for rhyme partners
    """
    n = len(lines)
    if n == 0:
        return RhymeScheme(0, [], "", [], 0.0, [], [])

    # Extract end words
    end_words = [_get_end_word(line) for line in lines]

    # Find all end-rhyme pairs within window
    pairs: list[RhymePair] = []
    pair_matrix: dict[int, list[tuple[int, float]]] = {}

    for i in range(n):
        for j in range(i + 1, min(i + window + 1, n)):
            score = _rhyme_score(end_words[i], end_words[j])
            if score >= threshold:
                pairs.append(RhymePair(i, j, end_words[i], end_words[j], score, "end"))
                pair_matrix.setdefault(i, []).append((j, score))
                pair_matrix.setdefault(j, []).append((i, score))

    # Assign scheme labels (greedy)
    labels = [""] * n
    current_label = 0

    for i in range(n):
        if labels[i]:
            continue
        # Check if this line rhymes with any previous labeled line
        best_match = None
        best_score = 0.0
        for j, score in pair_matrix.get(i, []):
            if j < i and labels[j] and score > best_score:
                best_match = j
                best_score = score

        if best_match is not None:
            labels[i] = labels[best_match]
        else:
            labels[i] = chr(ord("A") + current_label % 26)
            current_label += 1

        # Forward-assign: same label to rhyming unlabeled lines
        for j, score in pair_matrix.get(i, []):
            if j > i and not labels[j] and score >= threshold:
                labels[j] = labels[i]

    # Detect internal rhymes (words within the same line or across lines)
    internal: list[RhymePair] = []
    for i in range(n):
        words_i = re.findall(r"[\wäöüß]+", lines[i], re.IGNORECASE)
        if len(words_i) >= 4:
            # Check internal rhyme within line (first half vs second half)
            mid = len(words_i) // 2
            for wa in words_i[:mid]:
                for wb in words_i[mid:]:
                    score = _rhyme_score(wa, wb)
                    if score >= threshold and wa.lower() != wb.lower():
                        internal.append(RhymePair(i, i, wa, wb, score, "internal"))
                        break
                if internal and internal[-1].line_a == i:
                    break

    # Detect multisyllabic rhymes (2+ syllable matches)
    multi: list[RhymePair] = []
    for pair in pairs:
        tail_a = _get_rhyme_tail(pair.word_a, min_chars=4)
        tail_b = _get_rhyme_tail(pair.word_b, min_chars=4)
        if len(tail_a) >= 4 and len(tail_b) >= 4:
            sim = SequenceMatcher(None, tail_a, tail_b).ratio()
            if sim >= 0.7:
                multi.append(RhymePair(
                    pair.line_a, pair.line_b, pair.word_a, pair.word_b,
                    sim, "multi"
                ))

    # Calculate density
    rhyming_lines = set()
    for p in pairs:
        rhyming_lines.add(p.line_a)
        rhyming_lines.add(p.line_b)
    density = len(rhyming_lines) / n if n > 0 else 0.0

    scheme = RhymeScheme(
        total_lines=n,
        scheme_labels=labels,
        scheme_pattern="".join(labels),
        rhyme_pairs=pairs,
        rhyme_density=density,
        internal_rhymes=internal,
        multi_rhymes=multi,
    )

    info(f"Rhyme: {scheme.scheme_pattern[:40]}{'...' if n > 40 else ''} "
         f"({len(pairs)} pairs, density={density:.0%})")

    return scheme
