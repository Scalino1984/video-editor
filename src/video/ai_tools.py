"""AI Chat agent for Video Editor — full timeline manipulation via conversation.

Tools: read timeline, add/remove/modify clips, apply effects, adjust timing,
configure render, trigger render, manage tracks/layers.
"""

from __future__ import annotations

import json
import os
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

from src.ai.chat import is_reasoning_model
from src.utils.logging import info, warn, error
from src.video.editor import (
    get_project, add_clip, remove_clip, update_clip,
    split_clip, add_effect, remove_effect,
    undo, redo, get_timeline_summary,
    render_project, _push_undo,
    add_track, remove_track, update_track, reorder_tracks,
    TRACK_TYPES,
)


# ── Action allowlist ──────────────────────────────────────────────────────────

ACTION_ALLOWLIST = frozenset({
    # Existing actions
    "add_clip", "remove_clip", "update_clip", "split_clip",
    "add_effect", "remove_effect", "update_project",
    "undo", "redo", "render",
    # Track/layer actions (v2)
    "add_track", "remove_track", "rename_track",
    "set_track_props", "reorder_tracks",
})

# Input length limit for chat messages
MAX_CHAT_MESSAGE_LENGTH = 4000


# ── Deps ──────────────────────────────────────────────────────────────────────

@dataclass
class EditorChatDeps:
    pid: str
    message_history: list[dict] = field(default_factory=list)


# ── System prompt ─────────────────────────────────────────────────────────────

EDITOR_SYSTEM = """Du bist ein KI-Video-Editor-Assistent mit Vollzugriff auf die Timeline.
Du kannst Clips hinzufügen, entfernen, bearbeiten, Effekte anwenden, Timing ändern und Renders starten.
Du kannst auch Spuren/Ebenen verwalten (hinzufügen, entfernen, umbenennen, umsortieren).

VERFÜGBARE AKTIONEN (nutze diese als JSON-Blöcke in deiner Antwort):
```action
{"action": "add_clip", "asset_id": "...", "track": "video|audio|subtitle", "start": 0, "duration": 5, "loop": false}
{"action": "remove_clip", "clip_id": "..."}
{"action": "update_clip", "clip_id": "...", "start": 1.5, "duration": 3.0, "speed": 1.5, "volume": 0.8}
{"action": "split_clip", "clip_id": "...", "at_time": 5.0}
{"action": "add_effect", "clip_id": "...", "type": "fade_in|fade_out|blur|grayscale|sepia|brightness|contrast|saturation|vignette|sharpen|rotate|flip_h|flip_v|zoom|overlay_text", "params": {...}}
{"action": "remove_effect", "clip_id": "...", "index": 0}
{"action": "update_project", "name": "...", "width": 1920, "height": 1080, "fps": 30, "crf": 20}
{"action": "add_track", "type": "video|audio|subtitle", "name": "V2"}
{"action": "remove_track", "track_id": "...", "force": false}
{"action": "rename_track", "track_id": "...", "name": "Neuer Name"}
{"action": "set_track_props", "track_id": "...", "enabled": true, "locked": false, "mute": false}
{"action": "reorder_tracks", "track_ids": ["id1", "id2", "id3"]}
{"action": "undo"}
{"action": "redo"}
{"action": "render"}
```

REGELN:
- Antworte auf Deutsch
- Beschreibe kurz was du tust, dann führe die Aktionen aus
- Du kannst mehrere Aktionen in einer Antwort ausführen
- Nutze die Timeline-Zusammenfassung um den aktuellen Stand zu verstehen
- Bei Unsicherheit frage nach
- Track-Typen: video, audio, subtitle

EFFEKT-PARAMETER:
- fade_in/fade_out: {"duration": 1.0}
- brightness: {"value": 0.1} (-1.0 bis 1.0)
- contrast: {"value": 1.2} (0.0 bis 3.0)
- saturation: {"value": 1.5} (0.0 bis 3.0)
- blur: {"sigma": 5}
- rotate: {"angle": 90|180|270}
- zoom: {"factor": 1.3}
- overlay_text: {"text": "...", "size": 48, "color": "white", "x": "(w-text_w)/2", "y": "h-80"}
"""


# ── Rule-based chat parser (deterministic, before AI) ─────────────────────────

def parse_chat_command(message: str, pid: str) -> list[dict] | None:
    """Try to parse a direct command from the chat message.

    Returns a list of action dicts if recognized, or None to fall through to AI.
    Supports German and English layer/track commands.
    """
    msg = message.strip().lower()

    # Track add patterns: "+ video", "füge eine video-ebene hinzu", "neue spur audio"
    add_patterns = [
        _re.compile(r"^\+\s*(video|audio|subtitle)$"),
        _re.compile(r"(?:füge|erstelle|add)\s+(?:eine?\s+)?(?:neue?\s+)?(video|audio|subtitle)[\s-]*(?:spur|ebene|track|layer)?(?:\s+hinzu)?"),
        _re.compile(r"(?:neue?|new)\s+(?:spur|ebene|track|layer)\s+(video|audio|subtitle)"),
        _re.compile(r"(?:neue?|new)\s+(video|audio|subtitle)\s+(?:spur|ebene|track|layer)"),
    ]
    for pat in add_patterns:
        m = pat.search(msg)
        if m:
            return [{"action": "add_track", "type": m.group(1)}]

    # Track remove patterns: "- ebene 2", "entferne spur 3", "- subtitle"
    remove_idx_patterns = [
        _re.compile(r"^-\s*(?:ebene|spur|track|layer)\s*(\d+)(?:\s+force)?$"),
        _re.compile(r"(?:entferne|lösche|remove|delete)\s+(?:ebene|spur|track|layer)\s*(\d+)(?:\s+force)?"),
    ]
    for pat in remove_idx_patterns:
        m = pat.search(msg)
        if m:
            idx = int(m.group(1)) - 1  # 1-based to 0-based
            force = "force" in msg
            p = get_project(pid)
            if p and 0 <= idx < len(p.tracks):
                track = sorted(p.tracks, key=lambda t: t.index)[idx]
                return [{"action": "remove_track", "track_id": track.id, "force": force}]

    # Remove by type: "- subtitle", "entferne video spur"
    remove_type_patterns = [
        _re.compile(r"^-\s*(video|audio|subtitle)$"),
        _re.compile(r"(?:entferne|lösche|remove|delete)\s+(?:die\s+)?(video|audio|subtitle)[\s-]*(?:spur|ebene|track|layer)?(?:\s+force)?"),
    ]
    for pat in remove_type_patterns:
        m = pat.search(msg)
        if m:
            track_type = m.group(1)
            force = "force" in msg
            p = get_project(pid)
            if p:
                tracks_of_type = sorted(
                    [t for t in p.tracks if t.type == track_type],
                    key=lambda t: t.index, reverse=True,
                )
                if tracks_of_type:
                    return [{"action": "remove_track", "track_id": tracks_of_type[0].id, "force": force}]

    # Undo/redo
    if msg in ("undo", "rückgängig", "zurück"):
        return [{"action": "undo"}]
    if msg in ("redo", "wiederholen", "vorwärts"):
        return [{"action": "redo"}]

    return None


# ── Chat execution ────────────────────────────────────────────────────────────

async def run_editor_chat(
    pid: str, message: str, history: list[dict]
) -> AsyncGenerator[str, None]:
    """Run an AI chat turn with editor tool execution.

    Yields text chunks for streaming. First tries rule-based parsing for
    direct commands, then falls through to AI for complex requests.
    Parses ```action blocks from AI responses and executes them.
    """
    # Input validation
    if len(message) > MAX_CHAT_MESSAGE_LENGTH:
        yield f"⚠️ Nachricht zu lang (max {MAX_CHAT_MESSAGE_LENGTH} Zeichen)"
        return

    summary = get_timeline_summary(pid)

    # Try rule-based parser first (deterministic, no AI call needed)
    parsed = parse_chat_command(message, pid)
    if parsed:
        for action in parsed:
            act_name = action.get("action", "?")
            if act_name not in ACTION_ALLOWLIST:
                yield f"⚠️ Aktion nicht erlaubt: {act_name}\n"
                continue
            try:
                result = _execute_action(pid, action)
                yield f"✅ `{act_name}`: {result}\n"
            except Exception as e:
                yield f"❌ Fehler bei Aktion: {e}\n"
        new_summary = get_timeline_summary(pid)
        if new_summary != summary:
            yield f"\n---\n📋 **Timeline aktualisiert:**\n```\n{new_summary}\n```\n"
        info(f"[editor-ai] Rule-based command executed for project {pid}: {message[:80]}")
        return

    # Fall through to AI
    from src.ai.chat import get_model_name, has_ai_key

    if not has_ai_key():
        yield "⚠️ Kein AI-Modell konfiguriert. Setze AI_MODEL + API Key in .env"
        return

    model_name = get_model_name()

    # Build messages
    messages = [
        {"role": "system", "content": EDITOR_SYSTEM + f"\n\nAKTUELLE TIMELINE:\n{summary}"},
    ]
    for h in history[-20:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    # Call AI
    try:
        response_text = await _call_ai(model_name, messages)
    except Exception as e:
        yield f"❌ AI Fehler: {e}"
        return

    # Parse and execute action blocks
    import re
    parts = re.split(r"```action\s*\n(.*?)```", response_text, flags=re.DOTALL)

    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Text part
            text = part.strip()
            if text:
                yield text + "\n"
        else:
            # Action block
            for line in part.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    action = json.loads(line)
                    act_name = action.get("action", "?")
                    if act_name not in ACTION_ALLOWLIST:
                        yield f"\n⚠️ Aktion nicht erlaubt: {act_name}\n"
                        continue
                    result = _execute_action(pid, action)
                    yield f"\n✅ `{act_name}`: {result}\n"
                except json.JSONDecodeError:
                    yield f"\n⚠️ Ungültige Aktion: {line}\n"
                except Exception as e:
                    yield f"\n❌ Fehler bei Aktion: {e}\n"

    # Yield updated summary
    new_summary = get_timeline_summary(pid)
    if new_summary != summary:
        yield f"\n---\n📋 **Timeline aktualisiert:**\n```\n{new_summary}\n```\n"
    info(f"[editor-ai] AI chat executed for project {pid}: {message[:80]}")


def _execute_action(pid: str, action: dict) -> str:
    """Execute a single editor action. Returns status message."""
    act = action.get("action", "")
    p = get_project(pid)
    if not p:
        return "Project not found"

    if act == "add_clip":
        clip = add_clip(
            pid, action["asset_id"],
            track=action.get("track", "video"),
            start=action.get("start", -1),
            duration=action.get("duration", 0),
            loop=action.get("loop", False),
            volume=action.get("volume", 1.0),
            speed=action.get("speed", 1.0),
        )
        return f"Clip {clip.id} hinzugefügt" if clip else "Fehler"

    elif act == "remove_clip":
        ok = remove_clip(pid, action["clip_id"])
        return "Clip entfernt" if ok else "Clip nicht gefunden"

    elif act == "update_clip":
        action_copy = dict(action)
        cid = action_copy.pop("clip_id")
        action_copy.pop("action")
        clip = update_clip(pid, cid, **action_copy)
        return f"Clip {cid} aktualisiert" if clip else "Clip nicht gefunden"

    elif act == "split_clip":
        result = split_clip(pid, action["clip_id"], action["at_time"])
        if result:
            return f"Clip gesplittet: {result[0].id} + {result[1].id}"
        return "Split fehlgeschlagen"

    elif act == "add_effect":
        eff = add_effect(pid, action["clip_id"], action["type"],
                         action.get("params", {}))
        return f"Effekt {action['type']} hinzugefügt" if eff else "Fehler"

    elif act == "remove_effect":
        ok = remove_effect(pid, action["clip_id"], action["index"])
        return "Effekt entfernt" if ok else "Fehler"

    elif act == "update_project":
        _push_undo(pid)
        for k in ("name", "width", "height", "fps", "crf", "audio_bitrate", "preset"):
            if k in action:
                setattr(p, k, action[k])
        return f"Projekt aktualisiert: {p.name} ({p.width}x{p.height})"

    # ── Track/layer actions (v2) ──
    elif act == "add_track":
        track_type = action.get("type", "")
        if track_type not in TRACK_TYPES:
            return f"Ungültiger Track-Typ: {track_type}"
        track = add_track(pid, track_type, name=action.get("name", ""))
        return f"Track {track.name} ({track.type}) hinzugefügt" if track else "Fehler"

    elif act == "remove_track":
        ok = remove_track(
            pid, action["track_id"],
            force=action.get("force", False),
            migrate_to_track_id=action.get("migrate_to_track_id"),
        )
        return "Track entfernt" if ok else "Track konnte nicht entfernt werden"

    elif act == "rename_track":
        track = update_track(pid, action["track_id"], name=action["name"])
        return f"Track umbenannt: {track.name}" if track else "Track nicht gefunden"

    elif act == "set_track_props":
        props = {k: v for k, v in action.items() if k not in ("action", "track_id")}
        track = update_track(pid, action["track_id"], **props)
        return f"Track aktualisiert: {track.name}" if track else "Track nicht gefunden"

    elif act == "reorder_tracks":
        ok = reorder_tracks(pid, action["track_ids"])
        return "Tracks umsortiert" if ok else "Umsortierung fehlgeschlagen"

    elif act == "undo":
        ok = undo(pid)
        return "Undo erfolgreich" if ok else "Nichts zum Rückgängigmachen"

    elif act == "redo":
        ok = redo(pid)
        return "Redo erfolgreich" if ok else "Nichts zum Wiederholen"

    elif act == "render":
        output, err = render_project(pid)
        if output:
            mb = output.stat().st_size / (1024 * 1024)
            return f"Gerendert: {output.name} ({mb:.1f} MB)"
        return f"Render fehlgeschlagen: {err}"

    return f"Unbekannte Aktion: {act}"


async def _call_ai(model_name: str, messages: list[dict]) -> str:
    """Call the configured AI model. Supports OpenAI, Anthropic, Mistral, Google.

    Automatically detects reasoning models and adjusts parameters:
    - Reasoning models: no temperature, use max_completion_tokens (OpenAI)
    - Standard models: temperature=0.3, max_tokens=4096
    """
    provider, model = model_name.split(":", 1) if ":" in model_name else ("openai", model_name)
    reasoning = is_reasoning_model(model_name)

    if provider == "openai":
        from openai import AsyncOpenAI
        client = AsyncOpenAI()
        params: dict = {"model": model, "messages": messages}
        if reasoning:
            params["max_completion_tokens"] = 16384
        else:
            params["max_tokens"] = 4096
            params["temperature"] = 0.3
        r = await client.chat.completions.create(**params)
        return r.choices[0].message.content or ""

    elif provider == "anthropic":
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic()
        system = messages[0]["content"] if messages[0]["role"] == "system" else ""
        chat_msgs = [m for m in messages if m["role"] != "system"]
        params = {"model": model, "system": system, "messages": chat_msgs}
        if reasoning:
            params["max_tokens"] = 16384
        else:
            params["max_tokens"] = 4096
            params["temperature"] = 0.3
        r = await client.messages.create(**params)
        return r.content[0].text if r.content else ""

    elif provider == "mistral":
        from mistralai import Mistral
        client = Mistral(api_key=os.environ.get("MISTRAL_API_KEY", ""))
        params = {"model": model, "messages": messages}
        if reasoning:
            params["max_tokens"] = 16384
        else:
            params["max_tokens"] = 4096
            params["temperature"] = 0.3
        r = client.chat.complete(**params)
        return r.choices[0].message.content or ""

    elif provider == "google":
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GOOGLE_API_KEY", ""))
        gm = genai.GenerativeModel(model)
        # Convert to Gemini format
        system = ""
        parts = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                parts.append({"role": m["role"], "parts": [m["content"]]})
        gen_config: dict = {"max_output_tokens": 16384 if reasoning else 4096}
        r = gm.generate_content(parts, generation_config=gen_config)
        return r.text or ""

    raise ValueError(f"Unknown provider: {provider}")
