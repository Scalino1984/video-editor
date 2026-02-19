"""AI Chat API routes — streaming via PydanticAI v2.

Follows chat_app.py pattern:
- GET /api/ai/chat/{job_id} — load history (newline-delimited JSON)
- POST /api/ai/chat/{job_id} — send message, stream response
- DELETE /api/ai/chat/{job_id} — clear history
- GET /api/ai/health — check AI config
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from pydantic_ai import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UnexpectedModelBehavior,
    UserPromptPart,
)

from src.api import tasks
from src.ai.chat import (
    ChatDeps, create_agent, COMMAND_PROMPTS,
    get_model_name, is_reasoning_model, has_ai_key,
)
from src.ai.database import get_db
from src.utils.logging import info, error

router = APIRouter(prefix="/api/ai", tags=["ai"])


# ── Chat message format for frontend (from chat_app.py) ──────────────────────

def to_chat_message(m: ModelMessage) -> dict[str, str]:
    """Convert a PydanticAI ModelMessage to simple dict for the frontend."""
    first_part = m.parts[0]
    if isinstance(m, ModelRequest):
        if isinstance(first_part, UserPromptPart):
            content = first_part.content if isinstance(first_part.content, str) else str(first_part.content)
            return {
                "role": "user",
                "timestamp": first_part.timestamp.isoformat(),
                "content": content,
            }
    elif isinstance(m, ModelResponse):
        if isinstance(first_part, TextPart):
            return {
                "role": "model",
                "timestamp": m.timestamp.isoformat(),
                "content": first_part.content,
            }
    # Fallback for tool calls etc — skip them in UI
    return {
        "role": "model",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "content": "",
    }


# ── Build deps context from job ──────────────────────────────────────────────

def _build_deps(job_id: str) -> ChatDeps:
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments found")
    segments = json.loads(seg_path.read_text())
    job = tasks.get_job(job_id)
    metadata = {}
    if job and job.result:
        metadata = {
            "backend": job.result.backend,
            "language": job.result.language,
            "duration": job.result.duration_sec,
            "word_timestamps": job.result.word_timestamps_available,
        }
    return ChatDeps(
        job_id=job_id, segments=segments,
        output_dir=tasks.OUTPUT_DIR, metadata=metadata,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def ai_health():
    """Check if AI is configured."""
    model = get_model_name()
    return {
        "available": has_ai_key(),
        "model": model,
        "reasoning": is_reasoning_model(model),
    }


@router.get("/chat/{job_id}")
async def get_chat(job_id: str):
    """Get chat history — newline-delimited JSON (same format as chat_app.py)."""
    db = get_db(job_id, tasks.OUTPUT_DIR)
    msgs = await db.get_messages()
    # Filter to only user prompts and text responses (skip tool calls in UI)
    chat_msgs = []
    for m in msgs:
        cm = to_chat_message(m)
        if cm["content"]:  # skip empty (tool call) messages
            chat_msgs.append(cm)
    return Response(
        b"\n".join(json.dumps(m).encode("utf-8") for m in chat_msgs),
        media_type="text/plain",
    )


@router.delete("/chat/{job_id}")
async def clear_chat(job_id: str):
    db = get_db(job_id, tasks.OUTPUT_DIR)
    count = await db.clear()
    return {"cleared": count}


class ChatRequest(BaseModel):
    prompt: str
    command: str | None = None
    target_language: str = "English"


@router.post("/chat/{job_id}")
async def post_chat(job_id: str, req: ChatRequest):
    """Send a message and stream the AI response.

    Follows chat_app.py pattern: newline-delimited JSON stream.
    """
    deps = _build_deps(job_id)
    db = get_db(job_id, tasks.OUTPUT_DIR)

    # Build the full prompt
    user_prompt = req.prompt
    if req.command and req.command in COMMAND_PROMPTS:
        cmd_prefix = COMMAND_PROMPTS[req.command]
        lyrics_ctx = deps.get_lyrics_text()
        if req.command == "translate":
            cmd_prefix += f"\nZielsprache: {req.target_language}"
        user_prompt = f"{cmd_prefix}\n\nAktuelle Lyrics:\n{lyrics_ctx}"
        if req.prompt:
            user_prompt += f"\n\nZusaetzliche Anweisung: {req.prompt}"

    async def stream_messages():
        """Stream newline-delimited JSON messages to the client."""
        # Stream user prompt first so it shows immediately
        display_text = req.prompt
        if req.command:
            cmd_labels = {
                "correct": "Lyrics korrigieren",
                "punctuate": "Interpunktion setzen",
                "structure": "Struktur erkennen",
                "translate": f"Uebersetzen -> {req.target_language}",
                "generate": "Lyrics generieren",
            }
            label = cmd_labels.get(req.command, req.command)
            display_text = f"/{label}" + (f": {req.prompt}" if req.prompt else "")

        yield (
            json.dumps({
                "role": "user",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "content": display_text,
            }).encode("utf-8") + b"\n"
        )

        try:
            # Get message history for context
            messages = await db.get_messages()

            # Create agent and stream
            agent = create_agent()
            async with agent.run_stream(
                user_prompt, message_history=messages, deps=deps
            ) as result:
                async for text in result.stream_output(debounce_by=0.01):
                    m = ModelResponse(
                        parts=[TextPart(text)], timestamp=result.timestamp()
                    )
                    yield (
                        json.dumps(to_chat_message(m)).encode("utf-8") + b"\n"
                    )

            # Store new messages (user prompt + agent response + tool calls)
            await db.add_messages(result.new_messages_json())

            # Reload segments if agent modified them
            seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
            if seg_path.exists():
                yield (
                    json.dumps({
                        "role": "system",
                        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                        "content": "__SEGMENTS_UPDATED__",
                    }).encode("utf-8") + b"\n"
                )

        except Exception as e:
            error(f"AI chat error: {e}")
            yield (
                json.dumps({
                    "role": "model",
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "content": f"Fehler: {e}",
                }).encode("utf-8") + b"\n"
            )

    return StreamingResponse(stream_messages(), media_type="text/plain")
