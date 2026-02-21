r"""Karaoke ASS tag generation (\k, \kf, \ko).

Supports word-level and syllable-level progressive coloring.
"""

from __future__ import annotations

from src.transcription.base import TranscriptSegment, WordInfo


def word_duration_cs(word: WordInfo) -> int:
    r"""Duration in centiseconds for ASS \k tags."""
    return max(1, round((word.end - word.start) * 100))


def generate_karaoke_line(segment: TranscriptSegment, mode: str = "kf",
                          highlight_color: str = "") -> str:
    """Generate ASS karaoke-tagged text for a segment.
    mode: 'k' (fill), 'kf' (fade), 'ko' (outline/border wipe)
    """
    if not segment.words:
        return segment.text

    tag = f"\\{mode}"
    parts: list[str] = []

    # optional highlight color override
    color_tag = ""
    if highlight_color and mode != "ko":
        color_tag = f"\\1c{highlight_color}"

    for i, word in enumerate(segment.words):
        dur_cs = word_duration_cs(word)
        # for first word, include any color override
        if i == 0 and color_tag:
            parts.append(f"{{{tag}{dur_cs}{color_tag}}}{word.word}")
        else:
            parts.append(f"{{{tag}{dur_cs}}}{word.word}")

        # add space between words (but not after last)
        if i < len(segment.words) - 1:
            parts.append(" ")

    return "".join(parts)


def generate_syllable_karaoke_line(syllables: list, mode: str = "kf",
                                   highlight_color: str = "") -> str:
    r"""Generate ASS karaoke-tagged text from SyllableTokens.

    Each syllable becomes its own \k unit for fine-grained progressive fill.
    Expects syllable objects with start_ms, end_ms, text, word_id attributes.
    """
    if not syllables:
        return ""

    tag = f"\\{mode}"
    parts: list[str] = []

    color_tag = ""
    if highlight_color and mode != "ko":
        color_tag = f"\\1c{highlight_color}"

    prev_word_id = None
    for i, syl in enumerate(syllables):
        dur_ms = max(10, syl.end_ms - syl.start_ms)
        dur_cs = max(1, round(dur_ms / 10))

        # Add space between words (detect word boundary by word_id change)
        if prev_word_id is not None and syl.word_id != prev_word_id:
            parts.append(" ")

        if i == 0 and color_tag:
            parts.append(f"{{{tag}{dur_cs}{color_tag}}}{syl.text}")
        else:
            parts.append(f"{{{tag}{dur_cs}}}{syl.text}")

        prev_word_id = syl.word_id

    return "".join(parts)


def generate_karaoke_events(segments: list[TranscriptSegment], mode: str = "kf",
                            highlight_color: str = "",
                            style: str = "Default",
                            uncertain_style: str = "UncertainKaraoke",
                            confidence_threshold: float = 0.6,
                            fade_in_ms: int = 0,
                            fade_out_ms: int = 0) -> list[str]:
    """Generate list of ASS Dialogue events with karaoke tags.

    Fade durations are adaptive: capped at 20% of segment duration
    so short/fast segments stay readable.
    """
    events: list[str] = []
    for seg in segments:
        start = format_ass_time(seg.start)
        end = format_ass_time(seg.end)

        use_style = style
        if seg.confidence < confidence_threshold:
            use_style = uncertain_style

        text = generate_karaoke_line(seg, mode, highlight_color)
        # handle multi-line
        text = text.replace("\n", "\\N")

        # Adaptive fade: cap at 20% of segment duration, skip if segment < 400ms
        if fade_in_ms > 0 or fade_out_ms > 0:
            seg_dur_ms = max(0, int((seg.end - seg.start) * 1000))
            if seg_dur_ms >= 400:
                max_fade = int(seg_dur_ms * 0.2)
                fi = min(fade_in_ms, max_fade)
                fo = min(fade_out_ms, max_fade)
                # Ensure fade_in + fade_out don't exceed 50% of segment
                total = fi + fo
                if total > seg_dur_ms // 2:
                    ratio = (seg_dur_ms // 2) / total
                    fi = int(fi * ratio)
                    fo = int(fo * ratio)
                text = f"{{\\fad({fi},{fo})}}" + text

        events.append(
            f"Dialogue: 0,{start},{end},{use_style},,0,0,0,,{text}"
        )
    return events


def format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"
