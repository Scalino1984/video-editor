"""Word-level timing SSOT: AlignmentRun, WordToken, SegmentWordMap, edit flow.

This module implements the Single Source of Truth (SSOT) for word-level
timing data.  Segment start/end times are *derived* from the underlying
WordToken timestamps via SegmentWordMap ownership.

Key concepts:
- AlignmentRun  – one alignment pass (Voxtral/Whisper) over a time window.
- WordToken     – a single word with precise timing from an AlignmentRun.
- SyllableToken – optional syllable-level timing within a WordToken.
- SegmentWordMap – maps segments to ordered lists of word_ids.

Edit flow:
1. "Remap only" – words moved between segments without re-alignment.
2. "Re-align local" – new/missing words trigger local re-alignment.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.transcription.base import TranscriptSegment, WordInfo
from src.utils.logging import debug, warn


# ── Constants ────────────────────────────────────────────────────────────────

MIN_SEGMENT_DURATION_MS = 200
DEFAULT_GAP_MIN_MS = 20
DEFAULT_GAP_MAX_MS = 120
DEFAULT_WINDOW_PADDING_MS = 1000
MAX_WINDOW_MS = 30_000
COVERAGE_THRESHOLD = 0.80
CONFIDENCE_THRESHOLD = 0.55
VOWELS_DE = re.compile(r"[aeiouyäöü]+", re.IGNORECASE)


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class WordToken:
    """Single word with precise timing from an alignment run."""
    word_id: str
    idx_in_run: int
    surface: str          # original display form
    norm: str             # normalised form (lowercase, stripped punctuation)
    start_ms: int
    end_ms: int
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "word_id": self.word_id,
            "idx_in_run": self.idx_in_run,
            "surface": self.surface,
            "norm": self.norm,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WordToken:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class SyllableToken:
    """Syllable within a WordToken (optional, for fine-grained karaoke)."""
    syll_id: str
    word_id: str
    syll_index: int
    text: str
    start_ms: int
    end_ms: int
    confidence: float = 1.0
    method_version: str = "heuristic_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "syll_id": self.syll_id,
            "word_id": self.word_id,
            "syll_index": self.syll_index,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence": self.confidence,
            "method_version": self.method_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SyllableToken:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class AlignmentRun:
    """Metadata for a single alignment pass."""
    run_id: str
    track_id: str
    window_start_ms: int
    window_end_ms: int
    model_provider: str
    model_version: str
    params_hash: str
    created_at: float = field(default_factory=time.time)
    coverage: float = 0.0
    avg_confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    words: list[WordToken] = field(default_factory=list)
    syllables: list[SyllableToken] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "track_id": self.track_id,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "model_provider": self.model_provider,
            "model_version": self.model_version,
            "params_hash": self.params_hash,
            "created_at": self.created_at,
            "coverage": self.coverage,
            "avg_confidence": self.avg_confidence,
            "warnings": self.warnings,
            "words": [w.to_dict() for w in self.words],
            "syllables": [s.to_dict() for s in self.syllables],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AlignmentRun:
        words = [WordToken.from_dict(w) for w in d.get("words", [])]
        syllables = [SyllableToken.from_dict(s) for s in d.get("syllables", [])]
        return cls(
            run_id=d["run_id"],
            track_id=d["track_id"],
            window_start_ms=d["window_start_ms"],
            window_end_ms=d["window_end_ms"],
            model_provider=d["model_provider"],
            model_version=d["model_version"],
            params_hash=d["params_hash"],
            created_at=d.get("created_at", 0.0),
            coverage=d.get("coverage", 0.0),
            avg_confidence=d.get("avg_confidence", 0.0),
            warnings=d.get("warnings", []),
            words=words,
            syllables=syllables,
        )


@dataclass
class SegmentWordMapping:
    """Maps a single segment to an ordered list of word_ids."""
    segment_id: int
    word_ids: list[str]
    map_version: int = 1
    updated_at: float = field(default_factory=time.time)
    author: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "word_ids": self.word_ids,
            "map_version": self.map_version,
            "updated_at": self.updated_at,
            "author": self.author,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SegmentWordMapping:
        return cls(
            segment_id=d["segment_id"],
            word_ids=d.get("word_ids", []),
            map_version=d.get("map_version", 1),
            updated_at=d.get("updated_at", 0.0),
            author=d.get("author", "system"),
        )


@dataclass
class WordTimeline:
    """Top-level container: alignment runs + segment-word mappings."""
    alignment_runs: list[AlignmentRun] = field(default_factory=list)
    segment_mappings: list[SegmentWordMapping] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "alignment_runs": [r.to_dict() for r in self.alignment_runs],
            "segment_mappings": [m.to_dict() for m in self.segment_mappings],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WordTimeline:
        return cls(
            version=d.get("version", 1),
            alignment_runs=[AlignmentRun.from_dict(r) for r in d.get("alignment_runs", [])],
            segment_mappings=[SegmentWordMapping.from_dict(m) for m in d.get("segment_mappings", [])],
        )

    def all_words(self) -> dict[str, WordToken]:
        """Return word_id→WordToken lookup across all runs."""
        lookup: dict[str, WordToken] = {}
        for run in self.alignment_runs:
            for w in run.words:
                lookup[w.word_id] = w
        return lookup

    def all_syllables(self) -> dict[str, list[SyllableToken]]:
        """Return word_id→list[SyllableToken] lookup."""
        lookup: dict[str, list[SyllableToken]] = {}
        for run in self.alignment_runs:
            for s in run.syllables:
                lookup.setdefault(s.word_id, []).append(s)
        for sylls in lookup.values():
            sylls.sort(key=lambda s: s.syll_index)
        return lookup

    def mapping_for_segment(self, segment_id: int) -> SegmentWordMapping | None:
        for m in self.segment_mappings:
            if m.segment_id == segment_id:
                return m
        return None


# ── Tokenizer / Normalizer ───────────────────────────────────────────────────

def normalize_token(surface: str) -> str:
    """Normalise a word token for matching: lowercase, strip non-letter chars."""
    norm = surface.lower().strip()
    norm = re.sub(r"[^\w]", "", norm, flags=re.UNICODE)
    return norm


def tokenize_text(text: str) -> list[str]:
    """Deterministic tokenisation of lyrics text.

    Separates punctuation from words while preserving surface forms.
    """
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # Split on whitespace first
    raw = text.split()
    tokens: list[str] = []
    for raw_tok in raw:
        # Separate leading punctuation
        m = re.match(r"^([^\w]*)(.*)", raw_tok, flags=re.UNICODE)
        if m and m.group(1):
            tokens.append(m.group(1))
            raw_tok = m.group(2)
        if not raw_tok:
            continue
        # Separate trailing punctuation
        m2 = re.match(r"(.*?)([^\w]*)$", raw_tok, flags=re.UNICODE)
        if m2:
            if m2.group(1):
                tokens.append(m2.group(1))
            if m2.group(2):
                tokens.append(m2.group(2))
        else:
            tokens.append(raw_tok)
    return tokens


def tokenize_text_words_only(text: str) -> list[str]:
    """Tokenise text, returning only word tokens (no pure-punctuation)."""
    return [t for t in tokenize_text(text) if normalize_token(t)]


# ── Syllable Generator v1 ───────────────────────────────────────────────────

def split_syllables_de(word: str) -> list[str]:
    """Heuristic German syllable splitting.

    Uses vowel-group detection to estimate syllable boundaries.
    Not linguistically perfect but sufficient for duration distribution.
    """
    clean = re.sub(r"[^\w]", "", word, flags=re.UNICODE)
    if not clean:
        return [word] if word else []

    # Find vowel group positions
    vowel_positions: list[tuple[int, int]] = []
    for m in VOWELS_DE.finditer(clean):
        vowel_positions.append((m.start(), m.end()))

    if len(vowel_positions) <= 1:
        return [word]

    syllables: list[str] = []
    prev_end = 0
    for i, (vs, ve) in enumerate(vowel_positions):
        if i == len(vowel_positions) - 1:
            syllables.append(clean[prev_end:])
        else:
            next_vs = vowel_positions[i + 1][0]
            # Split between current vowel end and next vowel start
            mid = (ve + next_vs) // 2
            split_point = max(ve, mid)
            syllables.append(clean[prev_end:split_point])
            prev_end = split_point

    return [s for s in syllables if s]


def generate_syllable_tokens(word_token: WordToken) -> list[SyllableToken]:
    """Generate syllable tokens for a word by distributing duration proportionally."""
    syllables = split_syllables_de(word_token.surface)
    if not syllables:
        return []
    if len(syllables) == 1:
        return [SyllableToken(
            syll_id=f"{word_token.word_id}_s0",
            word_id=word_token.word_id,
            syll_index=0,
            text=word_token.surface,
            start_ms=word_token.start_ms,
            end_ms=word_token.end_ms,
            confidence=word_token.confidence,
        )]

    word_dur = word_token.end_ms - word_token.start_ms
    # Weight by vowel richness
    weights = []
    for s in syllables:
        vowel_count = len(VOWELS_DE.findall(s))
        weights.append(max(1, vowel_count))
    total_w = sum(weights)

    tokens: list[SyllableToken] = []
    current_ms = word_token.start_ms
    for i, (syl, w) in enumerate(zip(syllables, weights)):
        dur = round(word_dur * w / total_w) if total_w > 0 else word_dur // len(syllables)
        if i == len(syllables) - 1:
            # Last syllable gets remaining time to avoid rounding drift
            end_ms = word_token.end_ms
        else:
            end_ms = current_ms + dur
        tokens.append(SyllableToken(
            syll_id=f"{word_token.word_id}_s{i}",
            word_id=word_token.word_id,
            syll_index=i,
            text=syl,
            start_ms=current_ms,
            end_ms=end_ms,
            confidence=word_token.confidence,
        ))
        current_ms = end_ms

    return tokens


# ── Build Timeline from Existing Segments ────────────────────────────────────

def build_timeline_from_segments(
    segments: list[TranscriptSegment],
    track_id: str = "default",
    model_provider: str = "existing",
    model_version: str = "1.0",
    generate_syllables: bool = False,
) -> WordTimeline:
    """Build a WordTimeline from segments that already have word timestamps.

    This bootstraps the SSOT from the current segment data.
    """
    all_words: list[WordToken] = []
    all_syllables: list[SyllableToken] = []
    mappings: list[SegmentWordMapping] = []
    word_idx = 0

    for seg_idx, seg in enumerate(segments):
        seg_word_ids: list[str] = []
        words_source = seg.words if seg.words else _approximate_words(seg)

        for w in words_source:
            wid = f"w{word_idx:04d}"
            wt = WordToken(
                word_id=wid,
                idx_in_run=word_idx,
                surface=w.word,
                norm=normalize_token(w.word),
                start_ms=round(w.start * 1000),
                end_ms=round(w.end * 1000),
                confidence=w.confidence,
            )
            all_words.append(wt)
            seg_word_ids.append(wid)

            if generate_syllables:
                sylls = generate_syllable_tokens(wt)
                all_syllables.extend(sylls)

            word_idx += 1

        mappings.append(SegmentWordMapping(
            segment_id=seg_idx,
            word_ids=seg_word_ids,
        ))

    window_start = min((w.start_ms for w in all_words), default=0)
    window_end = max((w.end_ms for w in all_words), default=0)
    avg_conf = sum(w.confidence for w in all_words) / len(all_words) if all_words else 0.0
    covered = sum(1 for w in all_words if w.confidence > 0.5)
    coverage = covered / len(all_words) if all_words else 0.0

    params_str = f"{track_id}:{model_provider}:{model_version}:{window_start}:{window_end}"
    params_hash = hashlib.sha256(params_str.encode()).hexdigest()[:16]

    run = AlignmentRun(
        run_id=f"run_{params_hash}",
        track_id=track_id,
        window_start_ms=window_start,
        window_end_ms=window_end,
        model_provider=model_provider,
        model_version=model_version,
        params_hash=params_hash,
        coverage=coverage,
        avg_confidence=avg_conf,
        words=all_words,
        syllables=all_syllables,
    )

    return WordTimeline(
        alignment_runs=[run],
        segment_mappings=mappings,
    )


def _approximate_words(seg: TranscriptSegment) -> list[WordInfo]:
    """Fallback: approximate word timestamps from segment if none exist."""
    from src.refine.alignment import approximate_word_timestamps
    return approximate_word_timestamps(seg)


# ── Derive Segment Times ────────────────────────────────────────────────────

def derive_segment_times(
    timeline: WordTimeline,
    segment_id: int,
    gap_min_ms: int = DEFAULT_GAP_MIN_MS,
    gap_max_ms: int = DEFAULT_GAP_MAX_MS,
    min_duration_ms: int = MIN_SEGMENT_DURATION_MS,
) -> tuple[int, int]:
    """Derive start_ms/end_ms for a segment from its mapped WordTokens.

    Returns (start_ms, end_ms).
    Raises ValueError if segment has no mapped words.
    """
    mapping = timeline.mapping_for_segment(segment_id)
    if not mapping or not mapping.word_ids:
        raise ValueError(f"No word mapping for segment {segment_id}")

    words_lookup = timeline.all_words()
    word_starts: list[int] = []
    word_ends: list[int] = []

    for wid in mapping.word_ids:
        wt = words_lookup.get(wid)
        if wt is None:
            warn(f"Word {wid} not found in timeline")
            continue
        word_starts.append(wt.start_ms)
        word_ends.append(wt.end_ms)

    if not word_starts:
        raise ValueError(f"No valid words for segment {segment_id}")

    start_ms = min(word_starts)
    end_ms = max(word_ends)

    # Enforce minimum duration
    if end_ms - start_ms < min_duration_ms:
        end_ms = start_ms + min_duration_ms

    return start_ms, end_ms


def derive_all_segment_times(
    timeline: WordTimeline,
    gap_min_ms: int = DEFAULT_GAP_MIN_MS,
    gap_max_ms: int = DEFAULT_GAP_MAX_MS,
    min_duration_ms: int = MIN_SEGMENT_DURATION_MS,
) -> list[tuple[int, int, int]]:
    """Derive times for all segments.

    Returns list of (segment_id, start_ms, end_ms), sorted by start_ms.
    Applies gap/clamp policy between adjacent segments.
    """
    raw_times: list[tuple[int, int, int]] = []
    for mapping in timeline.segment_mappings:
        try:
            s, e = derive_segment_times(timeline, mapping.segment_id,
                                        gap_min_ms, gap_max_ms, min_duration_ms)
            raw_times.append((mapping.segment_id, s, e))
        except ValueError as exc:
            warn(f"Skipping segment {mapping.segment_id}: {exc}")

    raw_times.sort(key=lambda x: x[1])

    # Apply gap/clamp policy: ensure no overlaps, enforce min gap
    result: list[tuple[int, int, int]] = []
    for i, (sid, start, end) in enumerate(raw_times):
        if i > 0:
            _, prev_start, prev_end = result[-1]
            gap = start - prev_end
            if gap < gap_min_ms:
                # Clamp: push this segment's start forward or previous end back
                mid = (prev_end + start) // 2
                new_prev_end = mid - gap_min_ms // 2
                new_start = mid + gap_min_ms // 2
                if new_prev_end < prev_start + min_duration_ms:
                    new_prev_end = prev_start + min_duration_ms
                    new_start = new_prev_end + gap_min_ms
                result[-1] = (result[-1][0], prev_start, new_prev_end)
                start = new_start
                if end < start + min_duration_ms:
                    end = start + min_duration_ms
            elif gap > gap_max_ms:
                # Keep original gap (don't artificially compress)
                pass
        result.append((sid, start, end))

    return result


def apply_derived_times(
    segments: list[dict],
    timeline: WordTimeline,
    gap_min_ms: int = DEFAULT_GAP_MIN_MS,
    gap_max_ms: int = DEFAULT_GAP_MAX_MS,
    min_duration_ms: int = MIN_SEGMENT_DURATION_MS,
) -> list[dict]:
    """Apply derived times back to segment dicts.

    Updates start/end from the word timeline. Also rebuilds
    word-level data from the mapped WordTokens.
    """
    derived = derive_all_segment_times(timeline, gap_min_ms, gap_max_ms, min_duration_ms)
    words_lookup = timeline.all_words()
    derived_map = {sid: (s, e) for sid, s, e in derived}

    for mapping in timeline.segment_mappings:
        sid = mapping.segment_id
        if sid >= len(segments):
            continue
        if sid not in derived_map:
            continue

        start_ms, end_ms = derived_map[sid]
        segments[sid]["start"] = round(start_ms / 1000.0, 3)
        segments[sid]["end"] = round(end_ms / 1000.0, 3)

        # Rebuild words list from mapped tokens
        new_words: list[dict] = []
        for wid in mapping.word_ids:
            wt = words_lookup.get(wid)
            if wt is None:
                continue
            new_words.append({
                "start": round(wt.start_ms / 1000.0, 3),
                "end": round(wt.end_ms / 1000.0, 3),
                "word": wt.surface,
                "confidence": wt.confidence,
            })
        segments[sid]["words"] = new_words
        segments[sid]["has_word_timestamps"] = bool(new_words)

    return segments


# ── Edit Flow ────────────────────────────────────────────────────────────────

@dataclass
class EditResult:
    """Result of a segment text edit operation."""
    action: str            # "remap" | "realign_needed"
    segments: list[dict]   # Updated segment dicts
    timeline: WordTimeline
    confidence: float      # 0.0–1.0 confidence in the result
    needs_review: bool     # True if manual review recommended
    details: dict[str, Any] = field(default_factory=dict)


def _match_tokens_to_words(
    tokens: list[str],
    words_lookup: dict[str, WordToken],
    available_word_ids: list[str],
) -> list[tuple[str, str | None]]:
    """Match text tokens to available WordTokens.

    Returns list of (token, word_id_or_None) pairs.
    Exact normalized match preferred; unmatched tokens get None.
    """
    # Build norm→word_id index (preserving order for duplicates)
    norm_to_ids: dict[str, list[str]] = {}
    for wid in available_word_ids:
        wt = words_lookup.get(wid)
        if wt:
            norm_to_ids.setdefault(wt.norm, []).append(wid)

    used: set[str] = set()
    result: list[tuple[str, str | None]] = []

    for tok in tokens:
        norm = normalize_token(tok)
        if not norm:
            # Pure punctuation — skip matching
            result.append((tok, None))
            continue
        candidates = norm_to_ids.get(norm, [])
        matched = None
        for cid in candidates:
            if cid not in used:
                matched = cid
                used.add(cid)
                break
        result.append((tok, matched))

    return result


def process_segment_edit(
    segments: list[dict],
    timeline: WordTimeline,
    edited_segments: dict[int, str],
) -> EditResult:
    """Process text edits on segments.

    Args:
        segments: Current segment dicts (from segments.json).
        timeline: Current WordTimeline.
        edited_segments: Map of segment_id→new_text for changed segments.

    Returns:
        EditResult with action="remap" if only word redistribution needed,
        or action="realign_needed" if new/missing tokens require re-alignment.
    """
    words_lookup = timeline.all_words()

    # Collect all word_ids from affected segments
    affected_ids: set[int] = set(edited_segments.keys())
    all_affected_word_ids: list[str] = []
    for sid in sorted(affected_ids):
        mapping = timeline.mapping_for_segment(sid)
        if mapping:
            all_affected_word_ids.extend(mapping.word_ids)

    # Tokenize new texts and try to match
    new_segment_tokens: dict[int, list[tuple[str, str | None]]] = {}
    all_matched = True
    unmatched_tokens: list[str] = []
    total_word_tokens = 0
    matched_word_tokens = 0

    for sid in sorted(affected_ids):
        new_text = edited_segments[sid]
        tokens = tokenize_text_words_only(new_text)
        matches = _match_tokens_to_words(tokens, words_lookup, all_affected_word_ids)
        new_segment_tokens[sid] = matches
        for tok, wid in matches:
            if normalize_token(tok):
                total_word_tokens += 1
                if wid is not None:
                    matched_word_tokens += 1
                else:
                    all_matched = False
                    unmatched_tokens.append(tok)

    match_ratio = matched_word_tokens / total_word_tokens if total_word_tokens > 0 else 0.0

    if not all_matched:
        # Re-alignment needed
        return EditResult(
            action="realign_needed",
            segments=segments,
            timeline=timeline,
            confidence=match_ratio,
            needs_review=True,
            details={
                "unmatched_tokens": unmatched_tokens,
                "match_ratio": match_ratio,
                "affected_segments": list(affected_ids),
            },
        )

    # Remap only: update SegmentWordMap
    for sid in sorted(affected_ids):
        matches = new_segment_tokens[sid]
        new_word_ids = [wid for _, wid in matches if wid is not None]

        # Update text in segment
        segments[sid]["text"] = edited_segments[sid]

        # Update mapping
        existing_mapping = timeline.mapping_for_segment(sid)
        if existing_mapping:
            existing_mapping.word_ids = new_word_ids
            existing_mapping.map_version += 1
            existing_mapping.updated_at = time.time()
            existing_mapping.author = "user"
        else:
            timeline.segment_mappings.append(SegmentWordMapping(
                segment_id=sid,
                word_ids=new_word_ids,
                author="user",
            ))

    # Derive new segment times
    segments = apply_derived_times(segments, timeline)

    return EditResult(
        action="remap",
        segments=segments,
        timeline=timeline,
        confidence=match_ratio,
        needs_review=match_ratio < 0.9,
        details={
            "match_ratio": match_ratio,
            "affected_segments": list(affected_ids),
        },
    )


# ── Windowing ────────────────────────────────────────────────────────────────

def compute_alignment_window(
    segments: list[dict],
    affected_indices: list[int],
    padding_ms: int = DEFAULT_WINDOW_PADDING_MS,
    max_window_ms: int = MAX_WINDOW_MS,
) -> tuple[int, int]:
    """Compute the time window for local re-alignment.

    Returns (window_start_ms, window_end_ms).
    """
    starts = [round(segments[i]["start"] * 1000) for i in affected_indices if i < len(segments)]
    ends = [round(segments[i]["end"] * 1000) for i in affected_indices if i < len(segments)]

    if not starts or not ends:
        return 0, 0

    window_start = max(0, min(starts) - padding_ms)
    window_end = max(ends) + padding_ms

    # Cap at max window
    if window_end - window_start > max_window_ms:
        window_end = window_start + max_window_ms

    return window_start, window_end


# ── Persistence ──────────────────────────────────────────────────────────────

TIMELINE_FILENAME = "word_timeline.json"


def save_timeline(timeline: WordTimeline, output_dir: Path) -> Path:
    """Save word timeline to JSON file."""
    p = output_dir / TIMELINE_FILENAME
    p.write_text(json.dumps(timeline.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    debug(f"Word timeline saved: {p}")
    return p


def load_timeline(output_dir: Path) -> WordTimeline | None:
    """Load word timeline from JSON file. Returns None if not found."""
    p = output_dir / TIMELINE_FILENAME
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return WordTimeline.from_dict(data)


# ── Observability ────────────────────────────────────────────────────────────

@dataclass
class TimelineMetrics:
    """Observability metrics for the word timeline system."""
    coverage_pct: float = 0.0
    avg_confidence: float = 0.0
    word_count: int = 0
    syllable_count: int = 0
    segment_count: int = 0
    remap_only: bool = False
    realign_needed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_pct": round(self.coverage_pct, 3),
            "avg_confidence": round(self.avg_confidence, 3),
            "word_count": self.word_count,
            "syllable_count": self.syllable_count,
            "segment_count": self.segment_count,
            "remap_only": self.remap_only,
            "realign_needed": self.realign_needed,
        }


def compute_metrics(timeline: WordTimeline) -> TimelineMetrics:
    """Compute observability metrics for a word timeline."""
    all_w = timeline.all_words()
    all_s = timeline.all_syllables()
    total_sylls = sum(len(sl) for sl in all_s.values())

    words = list(all_w.values())
    covered = sum(1 for w in words if w.confidence > 0.5)
    avg_conf = sum(w.confidence for w in words) / len(words) if words else 0.0
    coverage = covered / len(words) if words else 0.0

    return TimelineMetrics(
        coverage_pct=coverage,
        avg_confidence=avg_conf,
        word_count=len(words),
        syllable_count=total_sylls,
        segment_count=len(timeline.segment_mappings),
    )


# ── ASS Export Helpers ───────────────────────────────────────────────────────

def timeline_words_for_segment(
    timeline: WordTimeline,
    segment_id: int,
) -> list[WordInfo]:
    """Get WordInfo list for a segment from the timeline (for ASS export)."""
    mapping = timeline.mapping_for_segment(segment_id)
    if not mapping:
        return []
    words_lookup = timeline.all_words()
    result: list[WordInfo] = []
    for wid in mapping.word_ids:
        wt = words_lookup.get(wid)
        if wt:
            result.append(WordInfo(
                start=wt.start_ms / 1000.0,
                end=wt.end_ms / 1000.0,
                word=wt.surface,
                confidence=wt.confidence,
            ))
    return result


def timeline_syllables_for_segment(
    timeline: WordTimeline,
    segment_id: int,
) -> list[SyllableToken]:
    """Get syllable tokens for a segment from the timeline."""
    mapping = timeline.mapping_for_segment(segment_id)
    if not mapping:
        return []
    all_sylls = timeline.all_syllables()
    result: list[SyllableToken] = []
    for wid in mapping.word_ids:
        sylls = all_sylls.get(wid, [])
        result.extend(sylls)
    return result
