"""ASS theme presets including mobile safe-area support."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ASSTheme:
    name: str
    playresx: int
    playresy: int
    font: str
    fontsize: int
    primary_color: str      # &HAABBGGRR
    secondary_color: str
    outline_color: str
    back_color: str
    highlight_color: str    # for karaoke
    bold: int
    outline: float
    shadow: float
    alignment: int          # numpad style
    margin_l: int
    margin_r: int
    margin_v: int
    encoding: int = 1
    spacing: float = 0.0
    fade_in_ms: int = 150
    fade_out_ms: int = 100

    def to_ass_style(self, style_name: str = "Default") -> str:
        return (
            f"Style: {style_name},{self.font},{self.fontsize},"
            f"{self.primary_color},{self.secondary_color},"
            f"{self.outline_color},{self.back_color},"
            f"{self.bold},0,0,0,100,100,{self.spacing:.1f},0,"
            f"1,{self.outline},{self.shadow},{self.alignment},"
            f"{self.margin_l},{self.margin_r},{self.margin_v},{self.encoding}"
        )

    def to_uncertain_style(self, style_name: str = "UncertainKaraoke") -> str:
        return (
            f"Style: {style_name},{self.font},{self.fontsize},"
            f"&H0000FFFF,{self.secondary_color},"
            f"{self.outline_color},{self.back_color},"
            f"{self.bold},0,0,0,100,100,{self.spacing:.1f},0,"
            f"1,{self.outline},{self.shadow},{self.alignment},"
            f"{self.margin_l},{self.margin_r},{self.margin_v},{self.encoding}"
        )


PRESETS: dict[str, ASSTheme] = {
    "classic": ASSTheme(
        name="classic",
        playresx=1920, playresy=1080,
        font="Arial", fontsize=48,
        primary_color="&H00FFFFFF",
        secondary_color="&H0000FFFF",
        outline_color="&H00000000",
        back_color="&H80000000",
        highlight_color="&H0000FFFF",
        bold=1, outline=2.5, shadow=1.5,
        alignment=2,
        margin_l=40, margin_r=40, margin_v=50,
    ),
    "neon": ASSTheme(
        name="neon",
        playresx=1920, playresy=1080,
        font="Impact", fontsize=52,
        primary_color="&H00FFFFFF",
        secondary_color="&H00FF00FF",
        outline_color="&H00FF0080",
        back_color="&H40000000",
        highlight_color="&H0000FF00",
        bold=1, outline=3.0, shadow=2.0,
        alignment=2,
        margin_l=40, margin_r=40, margin_v=50,
    ),
    "high_contrast": ASSTheme(
        name="high_contrast",
        playresx=1920, playresy=1080,
        font="Arial Black", fontsize=50,
        primary_color="&H00FFFFFF",
        secondary_color="&H0000FFFF",
        outline_color="&H00000000",
        back_color="&HC0000000",
        highlight_color="&H0000FFFF",
        bold=1, outline=4.0, shadow=0.0,
        alignment=2,
        margin_l=60, margin_r=60, margin_v=60,
    ),
    "landscape_1080p": ASSTheme(
        name="landscape_1080p",
        playresx=1920, playresy=1080,
        font="Segoe UI", fontsize=46,
        primary_color="&H00FFFFFF",
        secondary_color="&H0000FFFF",
        outline_color="&H00000000",
        back_color="&H80000000",
        highlight_color="&H0000FFFF",
        bold=1, outline=2.0, shadow=1.0,
        alignment=2,
        margin_l=80, margin_r=80, margin_v=40,
    ),
    "portrait_1080x1920": ASSTheme(
        name="portrait_1080x1920",
        playresx=1080, playresy=1920,
        font="Arial", fontsize=42,
        primary_color="&H00FFFFFF",
        secondary_color="&H0000FFFF",
        outline_color="&H00000000",
        back_color="&H80000000",
        highlight_color="&H0000FFFF",
        bold=1, outline=2.5, shadow=1.0,
        alignment=2,
        margin_l=60, margin_r=60, margin_v=300,
    ),
    "mobile_safe": ASSTheme(
        name="mobile_safe",
        playresx=1080, playresy=1920,
        font="Arial", fontsize=38,
        primary_color="&H00FFFFFF",
        secondary_color="&H0000FFFF",
        outline_color="&H00000000",
        back_color="&HA0000000",
        highlight_color="&H0000FFFF",
        bold=1, outline=3.0, shadow=0.0,
        alignment=2,
        margin_l=80, margin_r=80, margin_v=400,
    ),
}


def get_theme(preset_name: str) -> ASSTheme:
    import copy
    return copy.copy(PRESETS.get(preset_name, PRESETS["classic"]))


def apply_safe_area(theme: ASSTheme, safe_area: str = "") -> ASSTheme:
    """Apply safe-area margins override. Format: 'top,bottom,left,right' in px."""
    if not safe_area:
        return theme
    try:
        parts = [int(x.strip()) for x in safe_area.split(",")]
        if len(parts) == 4:
            top, bottom, left, right = parts
            theme.margin_l = max(theme.margin_l, left)
            theme.margin_r = max(theme.margin_r, right)
            theme.margin_v = max(theme.margin_v, bottom)
    except ValueError:
        pass
    return theme


def apply_overrides(theme: ASSTheme, **kwargs) -> ASSTheme:
    for key, val in kwargs.items():
        if val and hasattr(theme, key):
            setattr(theme, key, val)
    return theme
