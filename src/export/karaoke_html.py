"""Standalone Karaoke HTML export.

Generates a self-contained .html file with:
- Embedded CSS karaoke animation (word-level or char-level)
- Optional base64-embedded audio
- Playback controls, progress bar, fullscreen
- Responsive design (works on mobile)
- No external dependencies
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from src.transcription.base import TranscriptSegment
from src.utils.logging import info


def export_karaoke_html(
    segments: list[TranscriptSegment],
    output_path: Path,
    title: str = "Karaoke",
    audio_path: Path | None = None,
    embed_audio: bool = False,
    theme: str = "dark",         # "dark" | "light" | "neon" | "cinema"
    font_size: int = 32,
    highlight_color: str = "#00e5a0",
    bg_color: str | None = None,
    text_color: str | None = None,
    show_progress: bool = True,
    show_timestamps: bool = False,
    lines_visible: int = 3,
) -> Path:
    """Export segments as a standalone karaoke HTML file.

    Args:
        segments: Transcribed segments with word timestamps
        output_path: Where to write the .html file
        title: Song title displayed in the player
        audio_path: Path to audio file (for embedding or reference)
        embed_audio: If True, base64-encode audio into the HTML
        theme: Visual theme preset
        font_size: Lyrics font size in pixels
        highlight_color: Color for the active word highlight
        bg_color: Override background color
        text_color: Override text color
        show_progress: Show progress bar
        show_timestamps: Show timestamps per line
        lines_visible: Number of lines visible at once

    Returns:
        Path to the generated HTML file
    """
    # Theme presets
    themes = {
        "dark":   {"bg": "#0a0a0f", "text": "#e0e0e0", "dim": "#555", "accent": highlight_color},
        "light":  {"bg": "#f5f5f5", "text": "#1a1a1a", "dim": "#999", "accent": highlight_color},
        "neon":   {"bg": "#0d001a", "text": "#e0d0ff", "dim": "#4a2080", "accent": "#ff00ff"},
        "cinema": {"bg": "#000000", "text": "#ffffff", "dim": "#333", "accent": "#ffd700"},
    }
    t = themes.get(theme, themes["dark"])
    if bg_color: t["bg"] = bg_color
    if text_color: t["text"] = text_color

    # Prepare segment data
    seg_data = []
    for seg in segments:
        s = {"start": seg.start, "end": seg.end, "text": seg.text, "words": []}
        if seg.words:
            s["words"] = [{"s": w.start, "e": w.end, "w": w.word} for w in seg.words]
        seg_data.append(s)

    # Audio embedding
    audio_html = ""
    if audio_path and embed_audio and audio_path.exists():
        mime = "audio/mpeg" if audio_path.suffix == ".mp3" else \
               "audio/wav" if audio_path.suffix == ".wav" else \
               "audio/mp4" if audio_path.suffix in (".m4a", ".mp4") else \
               "audio/ogg" if audio_path.suffix in (".ogg", ".opus") else "audio/mpeg"
        b64 = base64.b64encode(audio_path.read_bytes()).decode()
        audio_html = f'<audio id="au" preload="auto"><source src="data:{mime};base64,{b64}"></audio>'
        info(f"Embedded audio: {audio_path.name} ({len(b64)//1024}KB base64)")
    elif audio_path:
        audio_html = f'<audio id="au" preload="auto"><source src="{audio_path.name}"></audio>'
    else:
        audio_html = '<audio id="au"></audio>'

    seg_json = json.dumps(seg_data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🎤 {_esc(title)}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:{t['bg']};color:{t['text']};font-family:'Segoe UI',system-ui,sans-serif;
  display:flex;flex-direction:column;height:100vh;overflow:hidden;user-select:none}}
.header{{padding:12px 20px;display:flex;align-items:center;gap:12px;
  background:rgba(255,255,255,0.03);border-bottom:1px solid rgba(255,255,255,0.06)}}
.title{{font-size:14px;opacity:.7;flex:1}}
.badge{{font-size:11px;padding:2px 8px;border-radius:10px;background:rgba(255,255,255,0.06)}}
.lyrics-area{{flex:1;display:flex;flex-direction:column;justify-content:center;
  align-items:center;padding:40px 20px;overflow:hidden;position:relative}}
.line{{font-size:{font_size}px;font-weight:700;line-height:1.5;text-align:center;
  padding:8px 16px;transition:all .3s ease;opacity:.2;transform:scale(.92);
  max-width:90vw;word-wrap:break-word}}
.line.active{{opacity:1;transform:scale(1)}}
.line.past{{opacity:.15;transform:scale(.88)}}
.line.next{{opacity:.35}}
.word{{display:inline-block;transition:color .15s ease,text-shadow .15s ease}}
.word.sung{{color:{t['accent']};text-shadow:0 0 20px {t['accent']}40,0 0 40px {t['accent']}20}}
.controls{{padding:16px 20px;background:rgba(255,255,255,0.02);
  border-top:1px solid rgba(255,255,255,0.06)}}
.progress-bar{{width:100%;height:4px;background:rgba(255,255,255,0.08);
  border-radius:2px;cursor:pointer;margin-bottom:12px;position:relative}}
.progress-fill{{height:100%;background:linear-gradient(90deg,{t['accent']},{t['accent']}dd);
  border-radius:2px;transition:width .1s linear;width:0}}
.btn-row{{display:flex;align-items:center;justify-content:center;gap:16px}}
.btn{{background:none;border:none;color:{t['text']};font-size:24px;cursor:pointer;
  padding:8px;border-radius:50%;transition:all .15s ease;opacity:.7}}
.btn:hover{{opacity:1;background:rgba(255,255,255,0.05)}}
.btn.play{{font-size:36px;opacity:1;background:rgba(255,255,255,0.06);
  width:56px;height:56px;display:flex;align-items:center;justify-content:center}}
.time{{font-size:12px;color:{t['dim']};font-variant-numeric:tabular-nums;min-width:90px}}
.time.right{{text-align:right}}
{''.join(f'.line:nth-child({i+1}){{animation-delay:{i*0.05}s}}' for i in range(lines_visible*2+1))}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(20px)}}to{{opacity:.2;transform:translateY(0)}}}}
.countdown{{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
  font-size:120px;font-weight:900;color:{t['accent']};opacity:0;
  text-shadow:0 0 60px {t['accent']}60;pointer-events:none;z-index:10}}
.countdown.show{{animation:pulse .8s ease-out}}
@keyframes pulse{{0%{{opacity:1;transform:translate(-50%,-50%) scale(1.5)}}
  100%{{opacity:0;transform:translate(-50%,-50%) scale(.8)}}}}
.fullscreen-btn{{position:fixed;top:12px;right:12px;z-index:100}}
</style>
</head>
<body>
<div class="header">
  <span style="font-size:20px">🎤</span>
  <span class="title">{_esc(title)}</span>
  <span class="badge" id="bpm"></span>
  <span class="badge" id="segInfo"></span>
</div>

<div class="lyrics-area" id="lyrics"></div>

<div class="countdown" id="cd"></div>

<div class="controls">
  {'<div class="progress-bar" id="pbar" onclick="seek(event)"><div class="progress-fill" id="pfill"></div></div>' if show_progress else ''}
  <div class="btn-row">
    <span class="time" id="tCur">0:00</span>
    <button class="btn" onclick="skip(-5)">⏪</button>
    <button class="btn play" id="playBtn" onclick="toggle()">▶</button>
    <button class="btn" onclick="skip(5)">⏩</button>
    <span class="time right" id="tDur">0:00</span>
  </div>
</div>

<button class="btn fullscreen-btn" onclick="goFS()" title="Fullscreen">⛶</button>

{audio_html}

<script>
const S={seg_json};
const au=document.getElementById('au');
const lyrics=document.getElementById('lyrics');
const VISIBLE={lines_visible};
let playing=false,curIdx=-1;

document.getElementById('segInfo').textContent=S.length+' lines';

function fmt(s){{const m=Math.floor(s/60);return m+':'+(''+(Math.floor(s)%60)).padStart(2,'0')}}

au.onloadedmetadata=()=>{{document.getElementById('tDur').textContent=fmt(au.duration)}};
au.ontimeupdate=()=>{{
  const t=au.currentTime;
  document.getElementById('tCur').textContent=fmt(t);
  {'document.getElementById("pfill").style.width=(t/au.duration*100)+"%";' if show_progress else ''}
  // Find active segment
  let idx=S.findIndex(s=>t>=s.start&&t<=s.end);
  if(idx<0)idx=S.findIndex(s=>t<s.start)-1;
  if(idx!==curIdx){{curIdx=idx;renderLines()}}
  // Word highlighting
  if(idx>=0&&S[idx].words.length){{
    document.querySelectorAll('.line.active .word').forEach(el=>{{
      const ws=parseFloat(el.dataset.s),we=parseFloat(el.dataset.e);
      el.classList.toggle('sung',t>=ws)
    }})
  }}
}};
au.onended=()=>{{playing=false;document.getElementById('playBtn').textContent='▶'}};

function renderLines(){{
  let h='';
  const start=Math.max(0,curIdx-1);
  const end=Math.min(S.length,curIdx+VISIBLE+1);
  for(let i=start;i<end;i++){{
    const s=S[i];
    const cls=i<curIdx?'past':i===curIdx?'active':i===curIdx+1?'next':'';
    if(s.words&&s.words.length){{
      const words=s.words.map(w=>
        `<span class="word" data-s="${{w.s}}" data-e="${{w.e}}">${{esc(w.w)}} </span>`
      ).join('');
      h+=`<div class="line ${{cls}}">${{words}}</div>`;
    }}else{{
      h+=`<div class="line ${{cls}}">${{esc(s.text)}}</div>`;
    }}
  }}
  lyrics.innerHTML=h;
}}

function toggle(){{
  if(au.paused){{au.play();playing=true;document.getElementById('playBtn').textContent='⏸'}}
  else{{au.pause();playing=false;document.getElementById('playBtn').textContent='▶'}}
}}
function skip(s){{au.currentTime=Math.max(0,Math.min(au.duration,au.currentTime+s))}}
function seek(e){{const r=e.currentTarget.getBoundingClientRect();au.currentTime=((e.clientX-r.left)/r.width)*au.duration}}
function goFS(){{document.documentElement.requestFullscreen?.()}}
function esc(t){{return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}}

// Keyboard
document.addEventListener('keydown',e=>{{
  if(e.code==='Space'){{e.preventDefault();toggle()}}
  if(e.key==='ArrowLeft')skip(-3);
  if(e.key==='ArrowRight')skip(3);
  if(e.key==='f'||e.key==='F')goFS();
}});

// Init
renderLines();
</script>
</body>
</html>"""

    output_path = output_path.with_suffix(".html")
    output_path.write_text(html, encoding="utf-8")
    info(f"Karaoke HTML exported: {output_path.name} ({len(html)//1024}KB)")
    return output_path


def _esc(text: str) -> str:
    """HTML-escape text."""
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;"))
