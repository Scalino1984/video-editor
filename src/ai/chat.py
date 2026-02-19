"""AI Chat Agent — PydanticAI v2 with segment-aware tools.

Follows the official PydanticAI chat_app.py pattern:
- Agent with model from .env
- message_history for conversation continuity
- run_stream with stream_output
- Tools for reading/modifying segments

.env configuration (single model, auto-detects reasoning):
    AI_MODEL=openai:gpt-5.2                       # OpenAI (reasoning auto-detected)
    AI_MODEL=openai:o3-mini                        # OpenAI reasoning
    AI_MODEL=anthropic:claude-sonnet-4-20250514    # Anthropic
    AI_MODEL=mistral:mistral-large-latest          # Mistral
    AI_MODEL=mistral:codestral-latest              # Mistral Codestral
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, RunContext

from src.utils.logging import info, warn, error, debug


# ── Deps context for agent tools ─────────────────────────────────────────────

@dataclass
class ChatDeps:
    """Runtime dependencies passed to agent tools via RunContext."""
    job_id: str
    segments: list[dict]
    output_dir: Path
    metadata: dict = field(default_factory=dict)

    def save_segments(self) -> None:
        seg_path = self.output_dir / self.job_id / "segments.json"
        seg_path.write_text(
            json.dumps(self.segments, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get_lyrics_text(self) -> str:
        return "\n".join(
            f"[{i+1}] ({s.get('start',0):.1f}s-{s.get('end',0):.1f}s) {s.get('text','')}"
            for i, s in enumerate(self.segments)
        )

    def get_plain_text(self) -> str:
        return "\n".join(s.get("text", "") for s in self.segments)


# ── Model configuration — single AI_MODEL, auto-detect reasoning ─────────────

# Known reasoning models (extended thinking / chain-of-thought built-in)
_REASONING_MODELS = {
    # OpenAI reasoning series
    "o1", "o1-mini", "o1-preview", "o3", "o3-mini", "o3-pro", "o4-mini",
    # GPT-5+ natively support reasoning
    "gpt-5", "gpt-5-mini", "gpt-5.1", "gpt-5.2",
    # Anthropic extended thinking
    "claude-opus-4", "claude-opus-4-20250514",
    # Mistral reasoning (if future models)
    "mistral-reasoning",
}

# Patterns that indicate reasoning capability
_REASONING_PATTERNS = (
    "o1", "o3", "o4",          # OpenAI o-series
    "gpt-5",                   # GPT-5 family
    "-thinking",               # any model with -thinking suffix
    "deepseek-r1",             # DeepSeek reasoning
)


def get_model_name() -> str:
    return os.environ.get("AI_MODEL", "openai:gpt-5.2")


def is_reasoning_model(model: str | None = None) -> bool:
    """Auto-detect if a model supports reasoning/extended thinking."""
    m = model or get_model_name()
    # Strip provider prefix (openai:gpt-5.2 -> gpt-5.2)
    short = m.split(":", 1)[-1].lower() if ":" in m else m.lower()
    # Check exact match
    if short in _REASONING_MODELS:
        return True
    # Check pattern match
    return any(p in short for p in _REASONING_PATTERNS)


def has_ai_key() -> bool:
    """Check if any AI provider API key is configured."""
    model = get_model_name().lower()
    # Check provider-specific key
    if model.startswith("openai:"):
        return bool(os.environ.get("OPENAI_API_KEY"))
    if model.startswith("anthropic:"):
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if model.startswith("mistral:"):
        return bool(os.environ.get("MISTRAL_API_KEY"))
    if model.startswith("google:"):
        return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    # Fallback: any key present
    return bool(
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("MISTRAL_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Du bist ein KI-Audio-Engineer-Assistent im Karaoke Sub Tool. Du hilfst beim Bearbeiten \
von Songtexten und Untertiteln die aus Audio transkribiert wurden.

Du hast Zugriff auf die transkribierten Segmente des aktuellen Jobs. Jedes Segment hat:
- Index (1-basiert), Start/End-Zeit, Text, Confidence, optional Speaker-Label

Du kannst folgende Aktionen mit deinen Tools ausfuehren:
1. Lyrics korrigieren — Transkriptionsfehler kontextbasiert fixen (update_segment_text / update_multiple_segments)
2. Interpunktion setzen — Satzzeichen und Zeilenumbrueche einfuegen
3. Struktur erkennen — Verse, Hook, Bridge, Outro taggen (set_speaker_labels)
4. Uebersetzen — Lyrics in andere Sprache, Reimschema beachtend
5. Lyrics generieren — Fehlende/unverstaendliche Texte basierend auf Kontext erstellen

Wenn du Segmente aenderst, nutze IMMER die passenden Tools. Beschreibe dem User was du tust.
Antworte auf Deutsch wenn der User Deutsch spricht.
Sei praezise und musikaffin — du kennst Reimschemata, Flow, Bars und Songstrukturen.\
"""


# ── Command-specific prompts ─────────────────────────────────────────────────

COMMAND_PROMPTS: dict[str, str] = {
    "correct": (
        "Analysiere die Lyrics und korrigiere Transkriptionsfehler. Beachte Reimschemata, "
        "Slang, Kontext der umliegenden Zeilen. Nutze update_multiple_segments um die "
        "korrigierten Texte zu setzen. Gib eine Zusammenfassung der Aenderungen."
    ),
    "punctuate": (
        "Setze Interpunktion in die Lyrics: Kommas, Punkte, Fragezeichen, Ausrufezeichen. "
        "Keine Aenderung am Wortlaut, NUR Zeichensetzung. Nutze update_multiple_segments."
    ),
    "structure": (
        "Analysiere die Song-Struktur und weise Speaker-Labels zu: "
        "Intro, Verse 1, Verse 2, Pre-Hook, Hook, Bridge, Outro, Ad-lib. "
        "Nutze set_speaker_labels um die Labels fuer alle Segmente zu setzen."
    ),
    "translate": (
        "Uebersetze die Lyrics. Versuche Reimschemata beizubehalten, "
        "Slang angemessen zu uebertragen, Silbenanzahl aehnlich zu halten. "
        "Nutze update_multiple_segments um die uebersetzten Texte einzusetzen."
    ),
    "generate": (
        "Generiere fehlende oder unverstaendliche Lyrics basierend auf dem Kontext, "
        "Genre, Reimschema und Flow der bestehenden Texte. "
        "Nutze update_multiple_segments um die generierten Texte einzusetzen."
    ),
    "refcorrect": (
        "Der User gibt dir einen Referenztext. Vergleiche ihn Zeile fuer Zeile mit den "
        "aktuellen Segmenten und korrigiere NUR inhaltliche Fehler (falsch transkribierte Woerter). "
        "NICHT aendern: Zeitcodes, Segmentstruktur, Zeilenumbrueche, ASS-Tags. "
        "Nutze update_multiple_segments fuer alle Korrekturen. "
        "Gib eine Zusammenfassung mit Segment-Nummern und was geaendert wurde."
    ),
}


# ── Agent factory ─────────────────────────────────────────────────────────────

def create_agent() -> Agent[ChatDeps, str]:
    """Create a PydanticAI v2 agent with segment tools.

    Uses single AI_MODEL from .env. Reasoning is auto-detected.
    """
    model = get_model_name()
    reasoning = is_reasoning_model(model)
    info(f"AI agent: {model} (reasoning={'yes' if reasoning else 'no'})")

    agent = Agent(
        model,
        system_prompt=SYSTEM_PROMPT,
        deps_type=ChatDeps,
        retries=2,
    )

    # ── Read tools ────────────────────────────────────────────────────────

    @agent.tool
    async def get_all_segments(ctx: RunContext[ChatDeps]) -> str:
        """Gibt alle Segmente mit Index, Zeitstempel, Text und Confidence zurueck."""
        return ctx.deps.get_lyrics_text()

    @agent.tool
    async def get_segment(ctx: RunContext[ChatDeps], index: int) -> str:
        """Gibt ein einzelnes Segment zurueck (1-basierter Index)."""
        i = index - 1
        if i < 0 or i >= len(ctx.deps.segments):
            return f"Segment {index} nicht gefunden (1-{len(ctx.deps.segments)})"
        s = ctx.deps.segments[i]
        words_info = ""
        if s.get("words"):
            words_info = "\nWoerter: " + " | ".join(
                f"{w['word']}({w.get('confidence',0):.0%})" for w in s["words"]
            )
        return (
            f"Segment {index}: [{s['start']:.2f}s - {s['end']:.2f}s]\n"
            f"Text: {s.get('text','')}\n"
            f"Confidence: {s.get('confidence',1):.0%}\n"
            f"Speaker: {s.get('speaker','')}"
            f"{words_info}"
        )

    @agent.tool
    async def get_low_confidence_segments(
        ctx: RunContext[ChatDeps], threshold: float = 0.6
    ) -> str:
        """Gibt alle Segmente mit Confidence unter dem Schwellwert zurueck."""
        low = []
        for i, s in enumerate(ctx.deps.segments):
            conf = s.get("confidence", 1.0)
            if conf < threshold:
                low.append(f"[{i+1}] ({conf:.0%}) {s.get('text','')}")
        if not low:
            return f"Keine Segmente unter {threshold:.0%} Confidence."
        return f"{len(low)} Segmente unter {threshold:.0%}:\n" + "\n".join(low)

    @agent.tool
    async def get_song_metadata(ctx: RunContext[ChatDeps]) -> str:
        """Gibt Song-Metadaten zurueck (Backend, Sprache, Dauer, Segment-Anzahl)."""
        m = ctx.deps.metadata
        return (
            f"Segmente: {len(ctx.deps.segments)}\n"
            f"Backend: {m.get('backend','?')}\n"
            f"Sprache: {m.get('language','?')}\n"
            f"Dauer: {m.get('duration',0):.1f}s\n"
            f"Word-Timestamps: {m.get('word_timestamps', False)}"
        )

    # ── Write tools ───────────────────────────────────────────────────────

    @agent.tool
    async def update_segment_text(
        ctx: RunContext[ChatDeps], index: int, new_text: str
    ) -> str:
        """Aendert den Text eines Segments (1-basierter Index)."""
        i = index - 1
        if i < 0 or i >= len(ctx.deps.segments):
            return f"Segment {index} nicht gefunden."
        old = ctx.deps.segments[i].get("text", "")
        ctx.deps.segments[i]["text"] = new_text
        ctx.deps.save_segments()
        return f"Segment {index}: '{old}' -> '{new_text}'"

    @agent.tool
    async def update_multiple_segments(
        ctx: RunContext[ChatDeps], changes: str
    ) -> str:
        """Aendert mehrere Segmente auf einmal.
        Format: Eine Aenderung pro Zeile als 'NUMMER: neuer text'
        Beispiel: '3: Korrigierter Text\\n7: Anderer Text'
        """
        updated = []
        for line in changes.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            match = re.match(r"(\d+)\s*:\s*(.+)", line)
            if not match:
                continue
            idx = int(match.group(1)) - 1
            text = match.group(2).strip()
            if 0 <= idx < len(ctx.deps.segments):
                old = ctx.deps.segments[idx].get("text", "")
                ctx.deps.segments[idx]["text"] = text
                updated.append(f"  [{idx+1}] '{old}' -> '{text}'")
        if updated:
            ctx.deps.save_segments()
            return f"{len(updated)} Segmente geaendert:\n" + "\n".join(updated)
        return "Keine Segmente geaendert."

    @agent.tool
    async def set_speaker_labels(ctx: RunContext[ChatDeps], labels: str) -> str:
        """Setzt Speaker-Labels fuer Segmente.
        Format: 'NUMMER: Label' pro Zeile, oder Bereiche: '1-4: Verse 1'
        """
        count = 0
        for line in labels.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            match = re.match(r"(\d+)(?:\s*-\s*(\d+))?\s*:\s*(.+)", line)
            if not match:
                continue
            start = int(match.group(1)) - 1
            end = int(match.group(2)) - 1 if match.group(2) else start
            label = match.group(3).strip()
            for i in range(max(0, start), min(len(ctx.deps.segments), end + 1)):
                ctx.deps.segments[i]["speaker"] = label
                count += 1
        if count:
            ctx.deps.save_segments()
            return f"{count} Segmente gelabelt."
        return "Keine Labels gesetzt."

    @agent.tool
    async def add_to_dictionary(ctx: RunContext[ChatDeps], entries: str) -> str:
        """Fuegt Eintraege zum Custom Dictionary hinzu.
        Format: 'falsch=richtig' pro Zeile.
        """
        dict_path = Path("custom_words.txt")
        existing = dict_path.read_text(encoding="utf-8") if dict_path.exists() else ""
        added = []
        for line in entries.strip().split("\n"):
            line = line.strip()
            if "=" in line and line not in existing:
                existing += line + "\n"
                added.append(line)
        dict_path.write_text(existing, encoding="utf-8")
        if added:
            return f"{len(added)} Eintraege: " + ", ".join(added)
        return "Keine neuen Eintraege."

    return agent
