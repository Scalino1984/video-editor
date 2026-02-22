"""Auto-scene generation — AI analyzes song lyrics and suggests 5 visual scenes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.utils.logging import info, warn, error, debug


# ── Lyrics extraction from editor project ─────────────────────────────────────

def extract_lyrics_from_project(pid: str) -> str:
    """Extract lyrics text from an editor project's subtitle assets or linked segments.

    Priority:
    1. Subtitle assets (SRT/ASS/VTT) — parse text only
    2. segments.json from linked karaoke job
    3. Empty string if neither found
    """
    from src.video.editor import get_project

    p = get_project(pid)
    if not p:
        return ""

    # Try subtitle assets first
    for asset in p.assets.values():
        if asset.type != "subtitle":
            continue
        path = Path(asset.path)
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            ext = path.suffix.lower()
            if ext == ".srt":
                return _lyrics_from_srt(text)
            elif ext == ".ass":
                return _lyrics_from_ass(text)
            elif ext == ".vtt":
                return _lyrics_from_vtt(text)
            elif ext == ".lrc":
                return _lyrics_from_lrc(text)
        except Exception as e:
            warn(f"[auto-scenes] Failed to parse subtitle {path.name}: {e}")
            continue

    # Try segments.json from job directory (project ID might be a job ID)
    seg_path = Path("data/output") / pid / "segments.json"
    if seg_path.exists():
        try:
            segs = json.loads(seg_path.read_text(encoding="utf-8"))
            return "\n".join(s.get("text", "").strip() for s in segs if s.get("text", "").strip())
        except Exception as e:
            warn(f"[auto-scenes] Failed to read segments.json: {e}")

    return ""


def _lyrics_from_srt(text: str) -> str:
    """Extract plain text from SRT content."""
    import re
    lines = []
    for block in text.strip().split("\n\n"):
        block_lines = block.strip().split("\n")
        text_lines = [
            l for l in block_lines
            if not re.match(r"^\d+$", l.strip())
            and not re.search(r"\d{2}:\d{2}:\d{2}", l)
        ]
        if text_lines:
            lines.append(" ".join(text_lines).strip())
    return "\n".join(lines)


def _lyrics_from_ass(text: str) -> str:
    """Extract plain text from ASS Dialogue lines."""
    import re
    lines = []
    for line in text.split("\n"):
        if not line.startswith("Dialogue:"):
            continue
        parts = line[10:].split(",", 9)
        if len(parts) < 10:
            continue
        raw = parts[9]
        # Remove ASS override tags
        clean = re.sub(r"\{[^}]*\}", "", raw)
        clean = clean.replace("\\N", " ").replace("\\n", " ").strip()
        if clean:
            lines.append(clean)
    return "\n".join(lines)


def _lyrics_from_vtt(text: str) -> str:
    """Extract plain text from WebVTT content."""
    import re
    lines = []
    in_cue = False
    for line in text.split("\n"):
        line = line.strip()
        if re.search(r"\d{2}:\d{2}[:.]\d{2}", line) and "-->" in line:
            in_cue = True
            continue
        if in_cue:
            if not line:
                in_cue = False
                continue
            # Remove VTT tags
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if clean:
                lines.append(clean)
    return "\n".join(lines)


def _lyrics_from_lrc(text: str) -> str:
    """Extract plain text from LRC content."""
    import re
    lines = []
    for line in text.split("\n"):
        # Remove timestamps like [00:12.34]
        clean = re.sub(r"\[\d+:\d+[:.]\d+\]", "", line).strip()
        # Remove metadata lines like [ti:...]
        if clean.startswith("[") and ":" in clean:
            continue
        if clean:
            lines.append(clean)
    return "\n".join(lines)


# ── AI scene suggestion ───────────────────────────────────────────────────────

SCENE_SYSTEM_PROMPT = """Du bist ein kreativer Regisseur für Musikvideos. Du analysierst Songtexte und schlägst 5 visuell perfekte Szenen vor, die als KI-generierte Videos erstellt werden können.

REGELN:
- Analysiere die Stimmung, Themen, Metaphern und den emotionalen Verlauf des Songs
- Jede Szene soll einen anderen Aspekt/Moment des Songs visuell einfangen
- Die Szenen sollen zusammen eine visuelle Geschichte erzählen
- Prompts müssen auf ENGLISCH sein (für Luma Dream Machine)
- Prompts sollen cinematisch, präzise und visuell beschreibend sein
- Jede Szene braucht: cinematic style, Lichtstimmung, Kamerabewegung, Atmosphäre
- Denke an Musikvideo-Ästhetik: dynamisch, emotional, symbolisch

ANTWORT-FORMAT (exakt JSON, keine Markdown-Code-Blöcke):
[
  {
    "title": "Kurzer deutscher Szenen-Titel (3-5 Wörter)",
    "prompt": "Detailed English Luma prompt, cinematic quality, specific lighting, camera movement, atmosphere...",
    "mood": "Stimmung auf Deutsch (1-2 Wörter)",
    "lyrics_ref": "Relevante Textzeile als Referenz"
  },
  ...
]

Genau 5 Szenen. Nur valides JSON, kein anderer Text."""


async def generate_auto_scenes(
    pid: str,
    gen_type: str = "video",
    aspect_ratio: str = "16:9",
) -> list[dict]:
    """Analyze project lyrics and generate 5 scene suggestions using AI.

    Returns a list of 5 scene dicts with: title, prompt, mood, lyrics_ref.
    """
    from src.ai.chat import get_model_name, has_ai_key
    from src.video.ai_tools import _call_ai

    if not has_ai_key():
        raise RuntimeError("Kein AI-Modell konfiguriert (AI_MODEL + API Key in .env setzen)")

    lyrics = extract_lyrics_from_project(pid)
    if not lyrics or len(lyrics.strip()) < 10:
        raise RuntimeError("Keine Lyrics/Untertitel im Projekt gefunden. Lade zuerst eine SRT/ASS-Datei hoch.")

    model_name = get_model_name()

    media_type = "Video" if gen_type == "video" else "Bild"
    orientation = {
        "16:9": "Landscape (16:9)",
        "9:16": "Portrait (9:16, TikTok/Reels)",
        "1:1": "Quadrat (1:1)",
    }.get(aspect_ratio, aspect_ratio)

    user_msg = f"""Analysiere diesen Songtext und erstelle 5 perfekte {media_type}-Szenen im Format {orientation}:

--- SONGTEXT ---
{lyrics[:3000]}
--- ENDE ---

Erstelle 5 cinematische Szenen-Vorschläge als JSON-Array."""

    messages = [
        {"role": "system", "content": SCENE_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        response = await _call_ai(model_name, messages)
    except Exception as e:
        error(f"[auto-scenes] AI call failed: {e}")
        raise RuntimeError(f"KI-Anfrage fehlgeschlagen: {e}")

    # Parse JSON from response (handle possible markdown wrapping)
    scenes = _parse_scenes_json(response)

    if not scenes or len(scenes) < 1:
        raise RuntimeError("KI konnte keine Szenen aus den Lyrics generieren")

    # Ensure exactly 5 scenes
    scenes = scenes[:5]

    info(f"[auto-scenes] Generated {len(scenes)} scenes for project {pid}")
    return scenes


def _parse_scenes_json(text: str) -> list[dict]:
    """Parse scene suggestions JSON from AI response, handling various formats."""
    import re

    # Try direct parse first
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code block
    m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    # Try finding array in text
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    warn(f"[auto-scenes] Failed to parse AI response as JSON: {text[:200]}")
    return []
