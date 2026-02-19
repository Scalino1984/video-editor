"""ASS subtitle writer with karaoke support, themes, and template merging."""

from __future__ import annotations

from pathlib import Path

from src.export.themes import ASSTheme, get_theme, apply_safe_area, apply_overrides
from src.export.karaoke_tags import generate_karaoke_events
from src.export.ass_template import load_template, merge_template
from src.transcription.base import TranscriptSegment
from src.utils.logging import info


def build_script_info(theme: ASSTheme, title: str = "Karaoke Subtitles") -> str:
    return (
        f"[Script Info]\n"
        f"Title: {title}\n"
        f"ScriptType: v4.00+\n"
        f"WrapStyle: 0\n"
        f"ScaledBorderAndShadow: yes\n"
        f"PlayResX: {theme.playresx}\n"
        f"PlayResY: {theme.playresy}\n"
        f"YCbCr Matrix: TV.709"
    )


def build_styles_section(theme: ASSTheme, include_uncertain: bool = True) -> str:
    lines = [
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        theme.to_ass_style("Default"),
    ]
    if include_uncertain:
        lines.append(theme.to_uncertain_style("UncertainKaraoke"))
    return "\n".join(lines)


def build_events_section(events: list[str]) -> str:
    lines = [
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines.extend(events)
    return "\n".join(lines)


def write_ass(
    segments: list[TranscriptSegment],
    output_path: Path,
    preset: str = "classic",
    karaoke_mode: str = "kf",
    highlight_color: str = "",
    safe_area: str = "",
    template_path: Path | None = None,
    replace_events_only: bool = True,
    confidence_threshold: float = 0.6,
    title: str = "Karaoke Subtitles",
    **theme_overrides,
) -> Path:
    theme = get_theme(preset)
    theme = apply_safe_area(theme, safe_area)
    theme = apply_overrides(theme, **{k: v for k, v in theme_overrides.items() if v})

    effective_highlight = highlight_color or theme.highlight_color

    events = generate_karaoke_events(
        segments,
        mode=karaoke_mode,
        highlight_color=effective_highlight,
        confidence_threshold=confidence_threshold,
        fade_in_ms=theme.fade_in_ms,
        fade_out_ms=theme.fade_out_ms,
    )

    if template_path and template_path.exists():
        info(f"Using ASS template: {template_path}")
        template_sections = load_template(template_path)
        styles_text = build_styles_section(theme)
        events_text = build_events_section(events)
        content = merge_template(template_sections, events_text, styles_text, replace_events_only)
    else:
        script_info = build_script_info(theme, title)
        styles = build_styles_section(theme)
        events_section = build_events_section(events)
        content = f"{script_info}\n\n{styles}\n\n{events_section}\n"

    output_path.write_text(content, encoding="utf-8-sig")
    info(f"ASS written: {output_path}")
    return output_path
