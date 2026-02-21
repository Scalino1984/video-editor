"""Lyrics alignment — map uploaded lyrics lines onto transcribed word timestamps.

When a user provides a .txt lyrics file alongside the audio:
1. Transcribe normally → get word-level timestamps
2. Read lyrics.txt → each non-empty line = one output segment
3. Flatten all transcribed words into a sequence
4. For each lyrics line, greedily match words from the flat sequence
5. Segment timing = first matched word start → last matched word end
6. Segment text = exact lyrics line (preserving user's formatting)

This ensures SRT/ASS files use the exact line structure from the uploaded lyrics.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from src.transcription.base import TranscriptSegment, WordInfo
from src.utils.logging import info, warn, debug


def parse_lyrics_file(lyrics_path: Path) -> list[str]:
    """Parse a lyrics .txt file into lines.

    - Strips BOM and leading/trailing whitespace
    - Removes lines that are purely section markers like [Verse 1], [Hook], etc.
    - Preserves empty lines as segment separators
    - Returns list of non-empty lines (each = one subtitle segment)
    """
    text = lyrics_path.read_text(encoding="utf-8-sig").strip()
    lines = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        # Skip section markers like [Verse 1], [Hook], (Intro) etc.
        if re.match(r"^\[.*\]$", line) or re.match(r"^\(.*\)$", line):
            continue
        if line:
            lines.append(line)
    info(f"Lyrics file: {len(lines)} lines parsed from {lyrics_path.name}")
    return lines


def _normalize_word(w: str) -> str:
    """Normalize a word for fuzzy matching: lowercase, strip punctuation."""
    w = w.lower().strip()
    w = re.sub(r"[^\w\s]", "", w)  # strip punctuation
    w = unicodedata.normalize("NFC", w)
    return w


def _tokenize(text: str) -> list[str]:
    """Split text into normalized word tokens."""
    return [_normalize_word(w) for w in text.split() if _normalize_word(w)]


def align_lyrics_to_segments(
    segments: list[TranscriptSegment],
    lyrics_lines: list[str],
    similarity_threshold: float = 0.4,
) -> list[TranscriptSegment]:
    """Align lyrics lines to transcribed segments using word-level timestamps.

    Strategy:
    1. Flatten all words with timestamps from transcription
    2. For each lyrics line, consume words from the flat list greedily
    3. Match by normalized word similarity
    4. Output segments with lyrics text + transcription timing

    Args:
        segments: Transcribed segments (with or without word timestamps)
        lyrics_lines: Lines from the uploaded .txt file
        similarity_threshold: Minimum similarity ratio for word matching

    Returns:
        New segment list with lyrics text and transcription timing
    """
    # Flatten all words with timestamps
    all_words: list[WordInfo] = []
    for seg in segments:
        if seg.words:
            all_words.extend(seg.words)
        else:
            # No word timestamps — create a pseudo-word for the whole segment
            all_words.append(WordInfo(
                start=seg.start, end=seg.end,
                word=seg.text, confidence=seg.confidence,
            ))

    if not all_words:
        warn("No words available for lyrics alignment")
        return segments

    info(f"Lyrics alignment: {len(lyrics_lines)} lines ← {len(all_words)} words")

    result: list[TranscriptSegment] = []
    word_idx = 0

    for line_num, lyrics_line in enumerate(lyrics_lines):
        target_tokens = _tokenize(lyrics_line)
        if not target_tokens:
            continue

        # Find best starting position for this line
        best_start_idx = _find_best_match_start(
            all_words, word_idx, target_tokens, similarity_threshold
        )

        if best_start_idx is None:
            # No good match found — interpolate from neighbours for smooth timing
            if result:
                seg_start = result[-1].end + 0.05
            elif word_idx < len(all_words):
                seg_start = all_words[word_idx].start
            else:
                seg_start = segments[-1].end if segments else 0

            # Estimate duration: use average of surrounding segments if available
            if result and line_num + 1 < len(lyrics_lines):
                avg_dur = sum(s.end - s.start for s in result) / len(result)
                est_duration = max(0.8, min(avg_dur, 4.0))
            else:
                est_duration = max(1.0, len(lyrics_line) / 15.0)
            seg_end = seg_start + est_duration

            # Build approximate word timestamps from text distribution
            line_tokens = lyrics_line.split()
            total_chars = max(sum(len(t) for t in line_tokens), 1)
            pseudo_words: list[WordInfo] = []
            cursor = seg_start
            for token in line_tokens:
                frac = len(token) / total_chars
                w_dur = est_duration * frac
                pseudo_words.append(WordInfo(
                    start=round(cursor, 3),
                    end=round(cursor + w_dur, 3),
                    word=token,
                    confidence=0.3,
                ))
                cursor += w_dur

            warn(f"  Line {line_num+1}: no match, estimated timing {seg_start:.1f}s-{seg_end:.1f}s")
            result.append(TranscriptSegment(
                start=round(seg_start, 3),
                end=round(seg_end, 3),
                text=lyrics_line,
                words=pseudo_words,
                confidence=0.3,
                has_word_timestamps=True,
            ))
            continue

        # Consume words for this line
        consumed_words: list[WordInfo] = []
        scan_idx = best_start_idx
        tokens_remaining = list(target_tokens)

        while tokens_remaining and scan_idx < len(all_words):
            w_norm = _normalize_word(all_words[scan_idx].word)
            t_norm = tokens_remaining[0]

            if _word_match(w_norm, t_norm, similarity_threshold):
                consumed_words.append(all_words[scan_idx])
                tokens_remaining.pop(0)
                scan_idx += 1
            elif w_norm:
                # Non-matching word — only allow limited slack after we started matching
                if len(consumed_words) > 0:
                    # Allow max 2 consecutive non-matching words as slack
                    # Look ahead to see if next target token matches soon
                    slack_ok = False
                    for lookahead in range(1, min(3, len(all_words) - scan_idx)):
                        future_norm = _normalize_word(all_words[scan_idx + lookahead].word)
                        if _word_match(future_norm, t_norm, similarity_threshold):
                            slack_ok = True
                            break
                    if slack_ok:
                        consumed_words.append(all_words[scan_idx])
                        scan_idx += 1
                    else:
                        break  # Stop consuming — we've diverged from the lyrics
                else:
                    scan_idx += 1
            else:
                scan_idx += 1

            # Safety: don't consume way more words than the line has
            if len(consumed_words) > len(target_tokens) * 2:
                break

        if consumed_words:
            seg_start = consumed_words[0].start
            seg_end = consumed_words[-1].end
            avg_conf = sum(w.confidence for w in consumed_words) / len(consumed_words)

            # Build word-level info mapped to lyrics tokens
            line_words = _build_line_words(lyrics_line, consumed_words)

            result.append(TranscriptSegment(
                start=round(seg_start, 3),
                end=round(max(seg_end, seg_start + 0.1), 3),
                text=lyrics_line,
                words=line_words,
                confidence=round(avg_conf, 3),
                has_word_timestamps=bool(line_words),
            ))
            word_idx = scan_idx  # advance past consumed words
            debug(f"  Line {line_num+1}: {seg_start:.1f}s-{seg_end:.1f}s ({len(consumed_words)} words)")
        else:
            # Fallback — shouldn't happen after find_best_match_start
            warn(f"  Line {line_num+1}: matched start but no words consumed")

    info(f"Lyrics alignment complete: {len(result)} segments")
    return result


def _find_best_match_start(
    all_words: list[WordInfo],
    start_from: int,
    target_tokens: list[str],
    threshold: float,
) -> int | None:
    """Find the best starting word index for matching a lyrics line."""
    if not target_tokens or start_from >= len(all_words):
        return None

    first_target = target_tokens[0]
    best_idx = None
    best_score = 0.0

    # Search window: capped to avoid O(n²) when corpus is large
    max_window = max(50, len(target_tokens) * 3)
    search_end = min(len(all_words), start_from + max_window)

    for i in range(start_from, search_end):
        w_norm = _normalize_word(all_words[i].word)
        score = _similarity(w_norm, first_target)
        if score >= threshold and score > best_score:
            # Verify that subsequent words also match somewhat
            lookahead_score = _lookahead_score(all_words, i, target_tokens, threshold)
            total = score * 0.3 + lookahead_score * 0.7
            if total > best_score:
                best_score = total
                best_idx = i

    return best_idx


def _lookahead_score(
    all_words: list[WordInfo],
    start: int,
    target_tokens: list[str],
    threshold: float,
) -> float:
    """Score how well words starting at `start` match the target tokens."""
    if not target_tokens:
        return 0.0
    matches = 0
    scan = start
    for token in target_tokens[:8]:  # check up to 8 tokens
        while scan < min(len(all_words), start + len(target_tokens) * 2):
            w_norm = _normalize_word(all_words[scan].word)
            scan += 1
            if _word_match(w_norm, token, threshold):
                matches += 1
                break
    return matches / min(len(target_tokens), 8)


def _word_match(a: str, b: str, threshold: float) -> bool:
    """Check if two normalized words match."""
    if not a or not b:
        return False
    if a == b:
        return True
    return _similarity(a, b) >= threshold


def _similarity(a: str, b: str) -> float:
    """Quick similarity ratio between two strings."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def correct_words_from_lyrics(
    segments: list[TranscriptSegment],
    lyrics_text: list[str],
    similarity_threshold: float = 0.4,
) -> list[TranscriptSegment]:
    """Correct ASR word text using lyrics as reference — keep segmentation & timing.

    Unlike align_lyrics_to_segments(), this mode does NOT restructure segments.
    It only walks through all ASR words and all lyrics words in parallel,
    replacing each ASR word's text with the matching lyrics word when the
    similarity is high enough.

    Args:
        segments: Transcribed segments (untouched structure)
        lyrics_text: Lines from lyrics file (will be flattened to word list)
        similarity_threshold: Minimum similarity to accept a correction

    Returns:
        Same segment list with corrected word and segment texts
    """
    # Flatten lyrics into a word list
    lyrics_words = []
    for line in lyrics_text:
        for w in line.split():
            if w.strip():
                lyrics_words.append(w.strip())

    if not lyrics_words:
        warn("correct_words_from_lyrics: no lyrics words available")
        return segments

    # Flatten all ASR words
    all_asr_words: list[tuple[int, int, WordInfo]] = []  # (seg_idx, word_idx, word)
    for si, seg in enumerate(segments):
        if seg.words:
            for wi, w in enumerate(seg.words):
                all_asr_words.append((si, wi, w))

    if not all_asr_words:
        # No word-level data — fall back to segment-level correction
        return _correct_segment_texts(segments, lyrics_words, similarity_threshold)

    info(f"Word correction: {len(all_asr_words)} ASR words ← {len(lyrics_words)} lyrics words")

    lyr_idx = 0
    corrections = 0

    for si, wi, asr_word in all_asr_words:
        if lyr_idx >= len(lyrics_words):
            break

        asr_norm = _normalize_word(asr_word.word)
        if not asr_norm:
            continue

        # Try to find a matching lyrics word within a small window
        best_offset = None
        best_score = 0.0
        search_limit = min(lyr_idx + 5, len(lyrics_words))

        for offset in range(lyr_idx, search_limit):
            lyr_norm = _normalize_word(lyrics_words[offset])
            score = _similarity(asr_norm, lyr_norm)
            if score > best_score:
                best_score = score
                best_offset = offset

        if best_offset is not None and best_score >= similarity_threshold:
            # Replace ASR word text with lyrics word (preserves timing)
            if best_score < 1.0:
                segments[si].words[wi] = WordInfo(
                    start=asr_word.start,
                    end=asr_word.end,
                    word=lyrics_words[best_offset],
                    confidence=asr_word.confidence,
                )
                corrections += 1
            lyr_idx = best_offset + 1
        else:
            # No good match — skip this ASR word, don't advance lyrics pointer
            pass

    # Rebuild segment texts from corrected words
    for seg in segments:
        if seg.words:
            seg.text = " ".join(w.word for w in seg.words)

    info(f"Word correction complete: {corrections} words corrected")
    return segments


def _correct_segment_texts(
    segments: list[TranscriptSegment],
    lyrics_words: list[str],
    threshold: float,
) -> list[TranscriptSegment]:
    """Fallback: correct segment-level text when no word timestamps exist."""
    lyr_idx = 0
    for seg in segments:
        seg_tokens = seg.text.split()
        new_tokens = []
        for token in seg_tokens:
            if lyr_idx >= len(lyrics_words):
                new_tokens.append(token)
                continue
            t_norm = _normalize_word(token)
            l_norm = _normalize_word(lyrics_words[lyr_idx])
            if _word_match(t_norm, l_norm, threshold):
                new_tokens.append(lyrics_words[lyr_idx])
                lyr_idx += 1
            else:
                # Look ahead in lyrics for a match
                found = False
                for la in range(1, min(4, len(lyrics_words) - lyr_idx)):
                    la_norm = _normalize_word(lyrics_words[lyr_idx + la])
                    if _word_match(t_norm, la_norm, threshold):
                        new_tokens.append(lyrics_words[lyr_idx + la])
                        lyr_idx = lyr_idx + la + 1
                        found = True
                        break
                if not found:
                    new_tokens.append(token)
        seg.text = " ".join(new_tokens)
    return segments


def _build_line_words(
    lyrics_line: str,
    consumed_words: list[WordInfo],
) -> list[WordInfo]:
    """Map consumed transcription words to lyrics line words.

    Uses best-effort 1:1 matching when counts differ — distributes excess
    consumed words across output tokens proportionally, averaging their timing
    rather than purely character-based interpolation.
    """
    line_tokens = lyrics_line.split()
    if not line_tokens or not consumed_words:
        return []

    # If counts match, map 1:1
    if len(line_tokens) == len(consumed_words):
        return [
            WordInfo(
                start=consumed_words[i].start,
                end=consumed_words[i].end,
                word=line_tokens[i],
                confidence=consumed_words[i].confidence,
            )
            for i in range(len(line_tokens))
        ]

    n_out = len(line_tokens)
    n_in = len(consumed_words)
    result = []

    if n_in >= n_out:
        # More consumed words than lyrics tokens — group consumed words per token
        # Distribute evenly, with remainder going to later tokens
        base_per_token = n_in // n_out
        remainder = n_in % n_out
        idx = 0
        for i, token in enumerate(line_tokens):
            count = base_per_token + (1 if i < remainder else 0)
            group = consumed_words[idx:idx + count]
            idx += count
            if group:
                avg_conf = sum(w.confidence for w in group) / len(group)
                result.append(WordInfo(
                    start=group[0].start,
                    end=group[-1].end,
                    word=token,
                    confidence=round(avg_conf, 3),
                ))
            else:
                # Should not happen, but safety fallback
                prev_end = result[-1].end if result else consumed_words[0].start
                result.append(WordInfo(
                    start=prev_end,
                    end=prev_end + 0.05,
                    word=token,
                    confidence=0.3,
                ))
    else:
        # Fewer consumed words than lyrics tokens — split consumed words across tokens
        # Use character-proportional timing from the consumed word spans
        total_start = consumed_words[0].start
        total_end = consumed_words[-1].end
        total_dur = max(total_end - total_start, 0.1)
        total_chars = max(sum(len(t) for t in line_tokens), 1)

        cursor = total_start
        for token in line_tokens:
            frac = len(token) / total_chars
            word_dur = total_dur * frac
            word_end = cursor + word_dur
            # Find closest consumed word for confidence
            closest = min(consumed_words, key=lambda w: abs(w.start - cursor))
            result.append(WordInfo(
                start=round(cursor, 3),
                end=round(word_end, 3),
                word=token,
                confidence=closest.confidence,
            ))
            cursor = word_end

    return result
