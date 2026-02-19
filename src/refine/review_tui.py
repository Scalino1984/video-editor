"""Interactive terminal review mode for transcript segments."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, IntPrompt, FloatPrompt, Confirm

from src.transcription.base import TranscriptSegment


console = Console()

HELP_TEXT = """
[bold]Review Commands:[/bold]
  n/enter  — Next segment
  p        — Previous segment
  e        — Edit text
  s        — Split segment at cursor
  m        — Merge with next segment
  +/-      — Nudge start time ±50ms
  ++/--    — Nudge start time ±250ms
  >/<      — Nudge end time ±50ms
  >>/<<    — Nudge end time ±250ms
  b        — Snap to beat (if BPM available)
  j N      — Jump to segment N
  q        — Quit and save
  ?        — Show this help
"""


def format_time(secs: float) -> str:
    m, s = divmod(secs, 60)
    h, m = divmod(int(m), 60)
    return f"{h:02d}:{int(m):02d}:{s:06.3f}"


def display_segment(seg: TranscriptSegment, index: int, total: int) -> None:
    conf_color = "green" if seg.confidence >= 0.8 else "yellow" if seg.confidence >= 0.6 else "red"
    wt_label = "real" if seg.has_word_timestamps else "approx"

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_row("[dim]Time:[/dim]", f"{format_time(seg.start)} → {format_time(seg.end)}")
    table.add_row("[dim]Duration:[/dim]", f"{seg.end - seg.start:.3f}s")
    table.add_row("[dim]Confidence:[/dim]", f"[{conf_color}]{seg.confidence:.2f}[/{conf_color}]")
    table.add_row("[dim]Word times:[/dim]", wt_label)
    table.add_row("[dim]CPS:[/dim]", f"{len(seg.text) / max(seg.end - seg.start, 0.1):.1f}")

    panel = Panel(
        f"[bold white]{seg.text}[/bold white]\n\n{table}",
        title=f"Segment {index + 1}/{total}",
        border_style="cyan",
    )
    console.print(panel)


def review_segments(segments: list[TranscriptSegment],
                    beats: list[float] | None = None) -> tuple[list[TranscriptSegment], list[dict]]:
    """Interactive review loop. Returns modified segments and a patch log."""
    segments = [deepcopy(s) for s in segments]
    patches: list[dict] = []
    idx = 0

    console.print(HELP_TEXT)

    while 0 <= idx < len(segments):
        console.clear()
        display_segment(segments[idx], idx, len(segments))
        cmd = Prompt.ask("[cyan]Command[/cyan]", default="n").strip().lower()

        if cmd in ("n", ""):
            idx += 1
        elif cmd == "p":
            idx = max(0, idx - 1)
        elif cmd == "e":
            new_text = Prompt.ask("New text", default=segments[idx].text)
            patches.append({"action": "edit", "index": idx, "old": segments[idx].text, "new": new_text})
            segments[idx].text = new_text
        elif cmd == "+":
            segments[idx].start += 0.05
            patches.append({"action": "nudge_start", "index": idx, "delta": 0.05})
        elif cmd == "-":
            segments[idx].start = max(0, segments[idx].start - 0.05)
            patches.append({"action": "nudge_start", "index": idx, "delta": -0.05})
        elif cmd == "++":
            segments[idx].start += 0.25
            patches.append({"action": "nudge_start", "index": idx, "delta": 0.25})
        elif cmd == "--":
            segments[idx].start = max(0, segments[idx].start - 0.25)
            patches.append({"action": "nudge_start", "index": idx, "delta": -0.25})
        elif cmd == ">":
            segments[idx].end += 0.05
            patches.append({"action": "nudge_end", "index": idx, "delta": 0.05})
        elif cmd == "<":
            segments[idx].end = max(segments[idx].start + 0.1, segments[idx].end - 0.05)
            patches.append({"action": "nudge_end", "index": idx, "delta": -0.05})
        elif cmd == ">>":
            segments[idx].end += 0.25
            patches.append({"action": "nudge_end", "index": idx, "delta": 0.25})
        elif cmd == "<<":
            segments[idx].end = max(segments[idx].start + 0.1, segments[idx].end - 0.25)
            patches.append({"action": "nudge_end", "index": idx, "delta": -0.25})
        elif cmd == "m" and idx + 1 < len(segments):
            nxt = segments.pop(idx + 1)
            segments[idx].end = nxt.end
            segments[idx].text += " " + nxt.text
            segments[idx].words.extend(nxt.words)
            patches.append({"action": "merge", "index": idx})
        elif cmd == "s":
            from src.refine.segmentation import split_segment
            parts = split_segment(segments[idx])
            if len(parts) > 1:
                segments[idx:idx + 1] = parts
                patches.append({"action": "split", "index": idx})
        elif cmd.startswith("j"):
            try:
                target = int(cmd[1:].strip()) - 1
                if 0 <= target < len(segments):
                    idx = target
            except ValueError:
                pass
        elif cmd == "q":
            break
        elif cmd == "?":
            console.print(HELP_TEXT)
            Prompt.ask("Press Enter to continue")

    return segments, patches


def save_patches(patches: list[dict], output_path: Path) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(patches, f, indent=2)
