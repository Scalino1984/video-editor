"""AI Chat API routes — streaming via PydanticAI v2.

Follows chat_app.py pattern:
- GET /api/ai/chat/{job_id} — load history (newline-delimited JSON)
- POST /api/ai/chat/{job_id} — send message, stream response
- DELETE /api/ai/chat/{job_id} — clear history
- GET /api/ai/health — check AI config
- POST /api/ai/chat/{job_id}/refcorrect — reference text correction (dry-run + apply)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
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
        if req.command == "refcorrect" and req.prompt:
            # For refcorrect, the prompt IS the reference text
            user_prompt = f"{cmd_prefix}\n\nAktuelle Lyrics:\n{lyrics_ctx}\n\nReferenztext:\n{req.prompt}"
        else:
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
                "refcorrect": "Referenz-Korrektur (AI)",
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


# ── Reference Text Correction ─────────────────────────────────────────────────

def _compute_ref_diff(
    segments: list[dict], ref_lines: list[str]
) -> list[dict]:
    """Word-for-word alignment between segment texts and reference text.

    Each segment word is individually replaced by its aligned reference word.
    Segment boundaries and word counts are preserved as closely as possible.

    Algorithm:
    1. Flatten segment & reference words into parallel streams
    2. SequenceMatcher aligns them by normalized form (case/punctuation-insensitive)
    3. For each segment word position, determine its replacement ref word(s)
    4. Rebuild each segment from its mapped words — no cross-segment shifting
    """
    import re
    from difflib import SequenceMatcher

    if not segments or not ref_lines:
        return []

    seg_texts = [s.get("text", "").strip() for s in segments]
    seg_word_lists = [t.split() for t in seg_texts]

    # Flatten segment words
    flat_seg: list[str] = []
    for words in seg_word_lists:
        flat_seg.extend(words)

    # Flatten reference words
    flat_ref: list[str] = []
    for line in ref_lines:
        flat_ref.extend(line.split())

    if not flat_seg or not flat_ref:
        return []

    # Coverage guard: skip when reference is much shorter than segments
    if len(flat_ref) < len(flat_seg) * 0.3:
        return []

    def _norm(w: str) -> str:
        return re.sub(r"[^\w]", "", w.lower())

    s_norm = [_norm(w) for w in flat_seg]
    r_norm = [_norm(w) for w in flat_ref]

    matcher = SequenceMatcher(None, s_norm, r_norm, autojunk=False)

    # Build replacement map: seg flat pos → list of ref words
    repl: list[list[str]] = [[] for _ in range(len(flat_seg))]

    for op, s1, s2, r1, r2 in matcher.get_opcodes():
        rw = flat_ref[r1:r2]
        s_len = s2 - s1
        r_len = r2 - r1

        if op == "equal":
            # Use ref words (preserves correct case/punctuation from reference)
            for k in range(s_len):
                repl[s1 + k] = [rw[k]]

        elif op == "replace":
            # Map 1:1 as far as possible
            n = min(s_len, r_len)
            for k in range(n):
                repl[s1 + k] = [rw[k]]
            if r_len > s_len:
                # Extra ref words → attach to last seg position in block
                repl[s2 - 1].extend(rw[s_len:])
            # If s_len > r_len: remaining positions stay empty → words dropped

        elif op == "insert":
            # Extra ref words with no seg match → attach to preceding position
            if s1 > 0:
                repl[s1 - 1].extend(rw)
            elif flat_seg:
                repl[0] = list(rw) + repl[0]

        # op == "delete": seg words with no ref match → repl stays empty → dropped

    # Reconstruct each segment from its word positions
    changes: list[dict] = []
    pos = 0
    for si, words in enumerate(seg_word_lists):
        new_words: list[str] = []
        for _ in words:
            new_words.extend(repl[pos])
            pos += 1
        new_text = " ".join(new_words)
        old_text = seg_texts[si]
        if new_text and old_text != new_text:
            changes.append({"index": si, "old_text": old_text, "new_text": new_text})

    return changes


def _write_correction_log(
    job_id: str, changes: list[dict], filename: str
) -> Path:
    """Write an audit log for applied corrections."""
    log_path = tasks.OUTPUT_DIR / job_id / "corrections.log"
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [f"\n{'='*60}", f"Correction applied: {ts}", f"Source: {filename}", f"{'='*60}"]
    for c in changes:
        lines.append(
            f"  Segment #{c['index']+1}:\n"
            f"    OLD: {c['old_text']}\n"
            f"    NEW: {c['new_text']}"
        )
    lines.append(f"Total: {len(changes)} segment(s) changed\n")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return log_path


class RefCorrectRequest(BaseModel):
    reference_text: str
    filename: str = "inline"
    apply: bool = False


@router.post("/chat/{job_id}/refcorrect")
async def ref_correct(job_id: str, req: RefCorrectRequest):
    """Reference text correction — dry-run or apply.

    Accepts reference text as string (pasted or from uploaded file).
    In dry-run mode (apply=False): returns planned changes.
    In apply mode (apply=True): applies changes, logs them, syncs SRT.
    """
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments found")
    segments = json.loads(seg_path.read_text(encoding="utf-8"))

    # Parse reference lines (skip empty lines and [Section] markers)
    ref_lines = []
    for line in req.reference_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip section markers like [Verse 1], [Hook], etc.
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        ref_lines.append(stripped)

    if not ref_lines:
        raise HTTPException(400, "Reference text is empty")

    # Compute diff
    changes = _compute_ref_diff(segments, ref_lines)

    if not req.apply:
        # Dry-run mode — return planned changes
        return {
            "mode": "dry_run",
            "total_segments": len(segments),
            "total_ref_lines": len(ref_lines),
            "changes": changes,
            "unchanged": len(segments) - len(changes),
        }

    # Apply mode
    if not changes:
        return {"mode": "applied", "changes": [], "message": "Keine Änderungen nötig"}

    # Push undo before mutation
    tasks.push_undo(job_id)

    # Apply changes to segments
    for c in changes:
        segments[c["index"]]["text"] = c["new_text"]

    # Save segments + sync SRT
    seg_path.write_text(
        json.dumps(segments, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Import _sync_srt from routes to keep SRT in sync
    from src.api.routes import _sync_srt
    _sync_srt(job_id, segments)

    # Write audit log
    log_path = _write_correction_log(job_id, changes, req.filename)
    info(f"Reference correction applied: {len(changes)} changes for job {job_id}")

    return {
        "mode": "applied",
        "changes": changes,
        "message": f"{len(changes)} Segmente korrigiert",
        "log_file": str(log_path),
    }


@router.post("/chat/{job_id}/refcorrect/upload")
async def ref_correct_upload(
    job_id: str,
    file: UploadFile = File(...),
    apply: bool = Form(False),
):
    """Reference correction via file upload (txt/lrc).

    Reads the uploaded file and delegates to ref_correct logic.
    """
    if not file.filename:
        raise HTTPException(400, "No filename")

    # Validate file type
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".txt", ".lrc", ".srt", ".vtt"}:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Use .txt, .lrc, .srt, or .vtt")

    # Read content with size limit (1MB)
    content = await file.read()
    if len(content) > 1_048_576:
        raise HTTPException(400, "File too large (max 1MB)")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except Exception:
            raise HTTPException(400, "Cannot decode file — use UTF-8 encoding")

    # For SRT/VTT: extract only text lines (skip timecodes, indices, headers)
    if suffix in {".srt", ".vtt"}:
        text = _extract_text_from_subtitle(text, suffix)

    req = RefCorrectRequest(reference_text=text, filename=file.filename, apply=apply)
    return await ref_correct(job_id, req)


def _extract_text_from_subtitle(content: str, suffix: str) -> str:
    """Extract plain text lines from SRT/VTT content."""
    import re
    lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip SRT index numbers
        if re.match(r"^\d+$", line):
            continue
        # Skip timecodes (00:00:00,000 --> 00:00:01,000)
        if re.match(r"\d{1,2}:\d{2}:\d{2}[.,]\d{3}\s*-->", line):
            continue
        # Skip VTT header
        if line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        lines.append(line)
    return "\n".join(lines)


# ── Segment Merge (Smart Auto-Merge) ─────────────────────────────────────────

# Defaults — can be overridden per request
MERGE_GAP_THRESHOLD_MS = 150
MERGE_CPS_LIMIT = 18.0
MERGE_MIN_WORDS = 3  # segments with fewer words are merge candidates


class MergeRequest(BaseModel):
    dry_run: bool = True
    gap_threshold_ms: int = MERGE_GAP_THRESHOLD_MS
    cps_limit: float = MERGE_CPS_LIMIT
    min_words: int = MERGE_MIN_WORDS


class MergeCandidate(BaseModel):
    index_a: int
    index_b: int
    text_a: str
    text_b: str
    merged_text: str
    start: float
    end: float
    gap_ms: float
    cps_before_a: float
    cps_before_b: float
    cps_after: float
    decision: str  # "MERGE" or "SKIP"
    skip_reason: str = ""


def _visible_len(text: str) -> int:
    """Length of visible text (strip ASS override tags like {\\k100})."""
    import re
    return len(re.sub(r"\{[^}]*\}", "", text).strip())


def _calc_cps(text: str, duration: float) -> float:
    """Chars per second for visible text."""
    if duration <= 0:
        return 999.0
    return round(_visible_len(text) / duration, 2)


def _normalize_merged(text: str) -> str:
    """Minimal normalization of merged text: double spaces, space before punctuation."""
    import re
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,!?;:»\u201d\u201c\u2019])", r"\1", text)
    return text


def _has_ass_overrides(text: str) -> bool:
    """Check if text contains ASS override tags."""
    return "{" in text and "\\" in text


def _ass_styles_compatible(seg_a: dict, seg_b: dict) -> bool:
    """Check if two segments have compatible ASS style/layer/speaker."""
    if seg_a.get("speaker") and seg_b.get("speaker"):
        if seg_a["speaker"] != seg_b["speaker"]:
            return False
    if seg_a.get("style") and seg_b.get("style"):
        if seg_a["style"] != seg_b["style"]:
            return False
    if seg_a.get("layer") is not None and seg_b.get("layer") is not None:
        if seg_a["layer"] != seg_b["layer"]:
            return False
    return True


def _find_merge_candidates(
    segments: list[dict],
    gap_threshold_ms: int = MERGE_GAP_THRESHOLD_MS,
    cps_limit: float = MERGE_CPS_LIMIT,
    min_words: int = MERGE_MIN_WORDS,
) -> list[MergeCandidate]:
    """Scan segments and identify adjacent pairs eligible for merging.

    A pair (i, i+1) is a candidate when EITHER segment has fewer than min_words words.
    Then validation decides MERGE vs SKIP.
    """
    candidates: list[MergeCandidate] = []
    skip_next = False

    for i in range(len(segments) - 1):
        if skip_next:
            skip_next = False
            continue

        a, b = segments[i], segments[i + 1]
        words_a = len(a.get("text", "").split())
        words_b = len(b.get("text", "").split())

        # Only consider pairs where at least one segment is short
        if words_a >= min_words and words_b >= min_words:
            continue

        text_a = a.get("text", "").strip()
        text_b = b.get("text", "").strip()
        merged_text = _normalize_merged(text_a + " " + text_b)

        gap_ms = round((b["start"] - a["end"]) * 1000, 1)
        duration_a = max(a["end"] - a["start"], 0.01)
        duration_b = max(b["end"] - b["start"], 0.01)
        duration_merged = max(b["end"] - a["start"], 0.01)

        cps_a = _calc_cps(text_a, duration_a)
        cps_b = _calc_cps(text_b, duration_b)
        cps_merged = _calc_cps(merged_text, duration_merged)

        decision = "MERGE"
        skip_reason = ""

        # Rule 3.2: Gap threshold
        if gap_ms > gap_threshold_ms:
            decision = "SKIP"
            skip_reason = f"GAP_TOO_LARGE ({gap_ms:.0f}ms > {gap_threshold_ms}ms)"

        # Rule 3.3: ASS style compatibility
        elif not _ass_styles_compatible(a, b):
            decision = "SKIP"
            skip_reason = "STYLE_MISMATCH"

        elif _has_ass_overrides(text_a) or _has_ass_overrides(text_b):
            decision = "SKIP"
            skip_reason = "ASS_TAG_RISK"

        # Rule 3.4: CPS limit
        elif cps_merged > cps_limit:
            decision = "SKIP"
            skip_reason = f"CPS_LIMIT ({cps_merged:.1f} > {cps_limit})"

        candidates.append(MergeCandidate(
            index_a=i,
            index_b=i + 1,
            text_a=text_a,
            text_b=text_b,
            merged_text=merged_text,
            start=a["start"],
            end=b["end"],
            gap_ms=gap_ms,
            cps_before_a=cps_a,
            cps_before_b=cps_b,
            cps_after=cps_merged,
            decision=decision,
            skip_reason=skip_reason,
        ))

        # If this pair will merge, skip i+1 so it can't also be merged with i+2
        if decision == "MERGE":
            skip_next = True

    return candidates


def _write_merge_log(
    job_id: str, candidates: list[MergeCandidate], mode: str
) -> Path:
    """Write audit log for merge operation."""
    log_path = tasks.OUTPUT_DIR / job_id / "merge.log"
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"\n{'='*60}",
        f"Merge {mode}: {ts}",
        f"Job: {job_id}",
        f"{'='*60}",
    ]
    merges = [c for c in candidates if c.decision == "MERGE"]
    skips = [c for c in candidates if c.decision == "SKIP"]
    lines.append(f"Candidates: {len(candidates)} total, {len(merges)} merge, {len(skips)} skip")
    for c in candidates:
        lines.append(
            f"  [{c.decision}] #{c.index_a+1}+#{c.index_b+1}: "
            f"gap={c.gap_ms:.0f}ms cps={c.cps_after:.1f} "
            f"{'(' + c.skip_reason + ') ' if c.skip_reason else ''}"
            f'"{c.text_a}" + "{c.text_b}" → "{c.merged_text}"'
        )
    lines.append("")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return log_path


def _apply_merges(
    segments: list[dict], candidates: list[MergeCandidate]
) -> list[dict]:
    """Apply approved merges to segment list. Returns new list.

    Processes in reverse order so indices stay valid.
    Only segments with decision="MERGE" are applied.
    """
    result = list(segments)  # shallow copy
    merges = [c for c in candidates if c.decision == "MERGE"]
    # Apply in reverse index order to preserve indices
    for c in sorted(merges, key=lambda c: c.index_a, reverse=True):
        a_idx, b_idx = c.index_a, c.index_b
        if b_idx >= len(result):
            continue
        seg_a = result[a_idx]
        seg_b = result[b_idx]
        merged = {
            "start": seg_a["start"],
            "end": seg_b["end"],
            "text": c.merged_text,
            "confidence": min(seg_a.get("confidence", 1.0), seg_b.get("confidence", 1.0)),
            "has_word_timestamps": False,
            "words": [],
        }
        # Preserve optional fields from seg_a
        for key in ("speaker", "pinned"):
            if key in seg_a:
                merged[key] = seg_a[key]
        result[a_idx:b_idx + 1] = [merged]
    return result


@router.post("/segments/{job_id}/merge")
async def smart_merge(job_id: str, req: MergeRequest):
    """Smart auto-merge of short/single-word segments.

    Dry-run (default): returns merge candidates with validation details.
    Apply (dry_run=False): executes approved merges, persists, syncs SRT.
    """
    seg_path = tasks.OUTPUT_DIR / job_id / "segments.json"
    if not seg_path.exists():
        raise HTTPException(404, "No segments found")
    segments = json.loads(seg_path.read_text(encoding="utf-8"))

    candidates = _find_merge_candidates(
        segments,
        gap_threshold_ms=req.gap_threshold_ms,
        cps_limit=req.cps_limit,
        min_words=req.min_words,
    )

    merges = [c for c in candidates if c.decision == "MERGE"]
    skips = [c for c in candidates if c.decision == "SKIP"]

    if req.dry_run:
        _write_merge_log(job_id, candidates, "dry_run")
        return {
            "mode": "dry_run",
            "total_segments": len(segments),
            "candidates": [c.model_dump() for c in candidates],
            "merge_count": len(merges),
            "skip_count": len(skips),
            "result_segments": len(segments) - len(merges),
        }

    # Apply mode
    if not merges:
        return {"mode": "applied", "changes": 0, "message": "Keine Merges nötig"}

    tasks.push_undo(job_id)
    new_segments = _apply_merges(segments, candidates)

    seg_path.write_text(
        json.dumps(new_segments, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    from src.api.routes import _sync_srt
    _sync_srt(job_id, new_segments)

    _write_merge_log(job_id, candidates, "applied")
    info(f"Smart merge: {len(merges)} merges applied for job {job_id}")

    return {
        "mode": "applied",
        "changes": len(merges),
        "new_total": len(new_segments),
        "message": f"{len(merges)} Segmente zusammengeführt",
    }
