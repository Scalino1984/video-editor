"""ASS template loading and merging support."""

from __future__ import annotations

import re
from pathlib import Path


def load_template(path: Path) -> dict[str, str]:
    """Load an ASS template file and split into sections."""
    content = path.read_text(encoding="utf-8-sig")
    sections: dict[str, str] = {}
    current_section = ""
    current_lines: list[str] = []

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if current_section:
                sections[current_section] = "\n".join(current_lines)
            current_section = stripped
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines)

    return sections


def merge_template(template_sections: dict[str, str], events_text: str,
                   styles_text: str = "", replace_events_only: bool = True) -> str:
    """Merge generated content into a template."""
    sections = dict(template_sections)

    # always replace events
    sections["[Events]"] = events_text

    # optionally add/merge styles
    if styles_text and not replace_events_only:
        if "[V4+ Styles]" in sections:
            existing = sections["[V4+ Styles]"]
            # append new styles that don't exist
            for line in styles_text.split("\n"):
                if line.startswith("Style:"):
                    style_name = line.split(",")[0].replace("Style:", "").strip()
                    if style_name not in existing:
                        existing += "\n" + line
            sections["[V4+ Styles]"] = existing
        else:
            sections["[V4+ Styles]"] = styles_text

    # reconstruct
    order = ["[Script Info]", "[V4+ Styles]", "[Events]"]
    result_parts: list[str] = []
    seen = set()
    for key in order:
        if key in sections:
            result_parts.append(sections[key])
            seen.add(key)
    for key, val in sections.items():
        if key not in seen:
            result_parts.append(val)

    return "\n\n".join(result_parts) + "\n"
