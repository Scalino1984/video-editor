# 🤖 Implementierungsplan: Unified AI Chat

> **Ziel:** Alle 4 isolierten KI-Chat-Schnittstellen in einen einzigen, seitenübergreifenden Chat zusammenführen, der über einen globalen Toggle-Button geöffnet wird und von jeder Seite aus alle Funktionen steuern kann.

---

## 📋 Inhaltsverzeichnis

1. [Ist-Zustand Analyse](#1-ist-zustand-analyse)
2. [Ziel-Architektur](#2-ziel-architektur)
3. [Phase 1 — Unified Backend Router](#phase-1--unified-backend-router)
4. [Phase 2 — Unified Chat Database](#phase-2--unified-chat-database)
5. [Phase 3 — Unified AI Agent (Multi-Domain)](#phase-3--unified-ai-agent-multi-domain)
6. [Phase 4 — Frontend: Globaler Chat-Widget](#phase-4--frontend-globaler-chat-widget)
7. [Phase 5 — Cross-Page Context & Navigation](#phase-5--cross-page-context--navigation)
8. [Phase 6 — Luma-Szenen-Integration](#phase-6--luma-szenen-integration)
9. [Phase 7 — Migration & Deprecation](#phase-7--migration--deprecation)
10. [Risiken & Mitigationen](#risiken--mitigationen)
11. [Dateiplan (neue/geänderte Dateien)](#dateiplan)
12. [Meilensteine & Zeitplan](#meilensteine--zeitplan)

---

## 1. Ist-Zustand Analyse

### 4 separate KI-Schnittstellen

| # | Schnittstelle | Dateien | KI-Provider | Chat-Persistenz | Streaming | Seite |
|---|---|---|---|---|---|---|
| 1 | **Karaoke AI Chat** | `src/ai/chat.py`, `src/ai/routes.py`, `src/ai/database.py` | OpenAI / Anthropic / Mistral / Google via PydanticAI v2 | SQLite (`.chat_history.sqlite`) | ✅ NDJSON | `index.html` |
| 2 | **Editor AI Chat** | `src/video/ai_tools.py` | OpenAI / Anthropic / Mistral / Google (direkte Calls) | Frontend-only (letzte 20 Msgs) | ✅ NDJSON | `editor.html` |
| 3 | **Transkription** | `src/transcription/openai_whisper.py`, `src/transcription/voxtral.py` | OpenAI Whisper / Mistral Voxtral | ❌ (Batch-Job) | ❌ Sync | `index.html` |
| 4 | **Luma Generation + Szenen-Prompts** | `src/video/generation/luma.py`, `src/video/generation/scenes.py`, `src/video/generation/routes.py` | Luma AI + Chat-KI für Prompt-Generierung | ❌ (Job-basiert) | ❌ (SSE für Status) | `editor.html` |

### Probleme des Ist-Zustands

- **Duplizierter KI-Call-Code:** `_call_ai()` in `ai_tools.py` und PydanticAI Agent in `chat.py` — 2 getrennte Implementierungen desselben Multi-Provider-Logik
- **Inkonsistente Chat-Persistenz:** Karaoke-Chat nutzt SQLite, Editor-Chat nur Frontend-Memory (max 20 Messages)
- **Kein seitenübergreifender Kontext:** Wechsel zwischen Index und Editor verliert Chat-Kontext
- **Kein geteiltes System-Prompt:** Jeder Chat hat eigene, isolierte System-Prompts und Tool-Definitionen
- **Duplizierte Reasoning-Detection:** `is_reasoning_model()` existiert in 2 Dateien identisch
- **Kein einheitliches Tool-Registry:** Karaoke nutzt PydanticAI-Tools, Editor nutzt Action-Blocks

---

## 2. Ziel-Architektur

```
┌─────────────────────────────────────────────────────────────────────┐
│                     FRONTEND (alle Seiten)                         │
│                                                                     │
│  ┌─────────────┐    global eingebunden via base template            │
│  │ 💬 Toggle   │    Position: fixed bottom-right                    │
│  │   Button    │    Zustand: localStorage (offen/zu/minimiert)      │
│  └──────┬──────┘                                                    │
│         │                                                           │
│  ┌──────▼──────────────────────────────────────────────────────┐    │
│  │          Unified Chat Widget (chat-widget.js)               │    │
│  │                                                              │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │    │
│  │  │ 🎤 Lyrics│  │ 🎬 Editor│  │ 🎨 Luma  │  │ ⚙️ System│    │    │
│  │  │   Mode   │  │   Mode   │  │ Gen Mode │  │   Mode   │    │    │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │    │
│  │                                                              │    │
│  │  Context-Leiste: Seite | Job-ID | Projekt-ID | Status       │    │
│  │  Chat-Verlauf (scrollbar, Markdown-Rendering)               │    │
│  │  Input + Shortcuts + Command-Palette                         │    │
│  └──────────────────────────────────┬───────────────────────────┘    │
│                                     │                               │
└─────────────────────────────────────┼───────────────────────────────┘
                                      │ POST /api/chat/unified
                                      │ NDJSON Streaming
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     BACKEND (FastAPI)                               │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              src/ai/unified_router.py                        │   │
│  │              (einziger Chat-Endpunkt)                        │   │
│  │                                                              │   │
│  │  POST /api/chat/unified     →  Nachricht senden (Stream)    │   │
│  │  GET  /api/chat/unified     →  Chat-Verlauf laden           │   │
│  │  DELETE /api/chat/unified   →  Chat löschen                 │   │
│  │  GET  /api/chat/health      →  KI-Status prüfen             │   │
│  │  GET  /api/chat/context     →  Verfügbare Kontexte          │   │
│  └──────────────────────────────────┬───────────────────────────┘   │
│                                     │                               │
│  ┌──────────────────────────────────▼───────────────────────────┐   │
│  │              src/ai/unified_agent.py                         │   │
│  │              (PydanticAI v2 Multi-Domain Agent)              │   │
│  │                                                              │   │
│  │  Domain-Router:                                              │   │
│  │  ├── lyrics.*    → Karaoke-Tools (11 Stück, behalten)       │   │
│  │  ├── editor.*    → Editor-Tools (Timeline, Clips, Effekte)  │   │
│  │  ├── generate.*  → Luma-Tools (Video/Bild/Szenen)           │   │
│  │  ├── navigate.*  → Cross-Page Navigation                    │   │
│  │  └── system.*    → Transkription starten, Status, Config    │   │
│  └──────────────────────────────────┬───────────────────────────┘   │
│                                     │                               │
│  ┌──────────────────────────────────▼───────────────────────────┐   │
│  │              src/ai/unified_db.py                            │   │
│  │              (Einheitliche Chat-Persistenz)                  │   │
│  │                                                              │   │
│  │  SQLite: data/chat/unified_{session_id}.sqlite              │   │
│  │  Tabellen: messages, context_switches, tool_results          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │   Bestehende Module (werden zu internen Services):          │   │
│  │                                                              │   │
│  │   src/ai/chat.py          → LyricsService (Tools only)      │   │
│  │   src/video/ai_tools.py   → EditorService (Tools only)      │   │
│  │   src/video/generation/*  → GenerationService (unverändert)  │   │
│  │   src/transcription/*     → TranscriptionService (unverändert)│  │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1 — Unified Backend Router

> **Ziel:** Einen einzigen `/api/chat/unified` Endpunkt schaffen, der alle Domänen bedient.

### Neue Datei: `src/ai/unified_router.py`

```python
"""Unified AI Chat Router — single endpoint for all domains."""

# POST /api/chat/unified
# Request-Body:
{
    "message": "Korrigiere die Lyrics in Zeile 5",
    "session_id": "abc123",          # Persistent session
    "context": {
        "page": "editor",            # "index" | "editor"
        "job_id": "xyz789",          # Karaoke-Job (optional)
        "project_id": "proj456",     # Editor-Projekt (optional)
        "domain_hint": "lyrics"      # "lyrics" | "editor" | "generate" | "auto"
    }
}

# Response: NDJSON Stream (wie bisher)
{"role": "user", "content": "...", "timestamp": "..."}
{"role": "model", "content": "...", "timestamp": "...", "domain": "lyrics"}
{"role": "system", "content": "__SEGMENTS_UPDATED__"}
{"role": "system", "content": "__NAVIGATE__", "target": "/editor?pid=proj456"}
```

### Aufgaben

- [ ] `src/ai/unified_router.py` erstellen
- [ ] Request-Schema: `UnifiedChatRequest(message, session_id, context)`
- [ ] Response-Schema: NDJSON mit `domain`-Tag pro Nachricht
- [ ] Domain-Auto-Detection: Analysiere Nachricht → route zu richtigem Domain
- [ ] Kontext-Switching: Wenn User über Lyrics spricht aber auf Editor-Seite ist → trotzdem Lyrics-Tools nutzen
- [ ] Streaming-Response wie bisheriges `src/ai/routes.py`
- [ ] Health-Endpunkt: `GET /api/chat/health` (KI-Verfügbarkeit aller Domains)
- [ ] Context-Endpunkt: `GET /api/chat/context` (verfügbare Jobs, Projekte, Status)
- [ ] In `main.py` einbinden: `app.include_router(unified_router)`

### Domain-Auto-Detection Logik

```python
DOMAIN_KEYWORDS = {
    "lyrics": ["lyrics", "text", "segment", "zeile", "korrigier", "interpunktion",
               "übersetze", "struktur", "verse", "hook", "bridge", "confidence",
               "wort", "untertitel", "srt", "ass", "karaoke", "bpm", "speaker"],
    "editor": ["clip", "track", "spur", "ebene", "effekt", "fade", "schnitt",
               "timeline", "render", "video", "audio", "brightness", "contrast",
               "zoom", "overlay", "split", "trim"],
    "generate": ["generier", "erstelle bild", "erstelle video", "luma", "ray-2",
                  "photon", "szene", "prompt", "dream machine", "ki-video",
                  "ki-bild", "aspect ratio"],
    "system": ["transkrib", "whisper", "voxtral", "backend", "status",
               "config", "einstellung"]
}
```

---

## Phase 2 — Unified Chat Database

> **Ziel:** Einheitliche Chat-Persistenz mit Domain-Tagging und Kontext-Switches.

### Neue Datei: `src/ai/unified_db.py`

### Datenbankschema

```sql
-- Zentrale Chat-Historie pro Session
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    domain TEXT NOT NULL DEFAULT 'auto',       -- lyrics|editor|generate|system
    context_job_id TEXT DEFAULT '',
    context_project_id TEXT DEFAULT '',
    context_page TEXT DEFAULT '',
    message_list TEXT NOT NULL                  -- PydanticAI ModelMessagesTypeAdapter JSON
);

-- Kontext-Wechsel Protokoll (für Audit/Debug)
CREATE TABLE IF NOT EXISTS context_switches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    from_domain TEXT,
    to_domain TEXT,
    from_page TEXT,
    to_page TEXT,
    trigger TEXT DEFAULT 'user'                -- user|auto|navigate
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_domain ON messages(session_id, domain);
CREATE INDEX IF NOT EXISTS idx_ctx_session ON context_switches(session_id);
```

### Aufgaben

- [ ] `src/ai/unified_db.py` erstellen (erweitert Muster von `src/ai/database.py`)
- [ ] `UnifiedDatabase` Klasse mit Session-Support
- [ ] `add_messages(session_id, domain, context, messages_json)`
- [ ] `get_messages(session_id, domain_filter=None, limit=100)` — optional nur eine Domain
- [ ] `get_full_history(session_id)` — alles für Kontext-Übergabe
- [ ] `log_context_switch(session_id, from_domain, to_domain, trigger)`
- [ ] `clear_session(session_id)` und `clear_domain(session_id, domain)`
- [ ] Migration: Import bestehender `.chat_history.sqlite` Dateien (optional)
- [ ] Speicherort: `data/chat/unified.sqlite` (eine DB für alles, Session-ID als Key)
- [ ] LRU-Begrenzung: Alte Sessions auto-purgen (z.B. > 7 Tage)

---

## Phase 3 — Unified AI Agent (Multi-Domain)

> **Ziel:** Einen PydanticAI v2 Agent mit allen Tools aus allen Domänen, der kontextabhängig die richtigen Tools verwendet.

### Neue Datei: `src/ai/unified_agent.py`

### System-Prompt (Unified)

```python
UNIFIED_SYSTEM_PROMPT = """Du bist der zentrale KI-Assistent des Karaoke Sub Tool Video Editors.
Du kannst seitenübergreifend arbeiten und hast Zugriff auf alle Funktionsbereiche:

📝 LYRICS-DOMAIN (Karaoke):
- Transkriptions-Segmente bearbeiten (Text, Zeiten, Speaker-Labels)
- Lyrics korrigieren, übersetzen, Interpunktion, Struktur erkennen
- BPM-Grid-Snap, Dictionary, Confidence-Analyse
- Aktiver Job: {job_id} | Sprache: {language} | Segmente: {segment_count}

🎬 EDITOR-DOMAIN (Video):
- Timeline-Manipulation: Clips, Tracks, Effekte
- Projekt-Einstellungen: Auflösung, FPS, CRF
- Render starten, Undo/Redo
- Aktives Projekt: {project_id} | Tracks: {track_count}

🎨 GENERATE-DOMAIN (Luma Dream Machine):
- KI-Videos generieren (ray-2, ray-flash-2)
- KI-Bilder generieren (photon-1, photon-flash-1)
- Auto-Szenen aus Lyrics erstellen
- Status laufender Generierungen prüfen

🧭 NAVIGATION:
- Zwischen Seiten wechseln (Index ↔ Editor)
- Kontext-Informationen anzeigen (Jobs, Projekte, Status)
- Transkription starten/Status prüfen

REGELN:
- Erkenne automatisch welche Domain angesprochen wird
- Bei Unsicherheit frage nach
- Du kannst domainübergreifend arbeiten: z.B. "Korrigiere die Lyrics und füge sie als Untertitel ins Video ein"
- Antworte immer auf Deutsch
- Bei Aktionen: beschreibe kurz was du tust, dann führe aus
"""
```

### Tool-Registry (alle Domains vereint)

```python
# ── Lyrics-Tools (übernommen aus src/ai/chat.py) ──
@agent.tool
async def get_all_segments(ctx: RunContext[UnifiedDeps]) -> str: ...

@agent.tool
async def update_segment_text(ctx: RunContext[UnifiedDeps], index: int, new_text: str) -> str: ...

@agent.tool
async def update_multiple_segments(ctx: RunContext[UnifiedDeps], changes: list[dict]) -> str: ...

# ... (alle 11 Lyrics-Tools)

# ── Editor-Tools (NEU als PydanticAI-Tools, ersetzt Action-Blocks) ──
@agent.tool
async def editor_add_clip(ctx: RunContext[UnifiedDeps], track_id: str, asset_id: str, start: float, duration: float) -> str: ...

@agent.tool
async def editor_remove_clip(ctx: RunContext[UnifiedDeps], clip_id: str) -> str: ...

@agent.tool
async def editor_add_track(ctx: RunContext[UnifiedDeps], track_type: str, name: str = "") -> str: ...

@agent.tool
async def editor_add_effect(ctx: RunContext[UnifiedDeps], clip_id: str, effect_type: str, params: dict) -> str: ...

@agent.tool
async def editor_render(ctx: RunContext[UnifiedDeps]) -> str: ...

@agent.tool
async def editor_undo(ctx: RunContext[UnifiedDeps]) -> str: ...

@agent.tool
async def editor_redo(ctx: RunContext[UnifiedDeps]) -> str: ...

# ... (alle Editor-Aktionen als native PydanticAI-Tools)

# ── Generate-Tools ──
@agent.tool
async def generate_video(ctx: RunContext[UnifiedDeps], prompt: str, model: str = "ray-2",
                          aspect_ratio: str = "16:9", duration: str = "5s") -> str: ...

@agent.tool
async def generate_image(ctx: RunContext[UnifiedDeps], prompt: str, model: str = "photon-1",
                          aspect_ratio: str = "16:9") -> str: ...

@agent.tool
async def generate_auto_scenes(ctx: RunContext[UnifiedDeps], gen_type: str = "video") -> str: ...

@agent.tool
async def get_generation_status(ctx: RunContext[UnifiedDeps], gen_id: str = "") -> str: ...

# ── Navigation-Tools ──
@agent.tool
async def navigate_to_editor(ctx: RunContext[UnifiedDeps], project_id: str = "") -> str: ...

@agent.tool
async def navigate_to_index(ctx: RunContext[UnifiedDeps]) -> str: ...

@agent.tool
async def get_available_jobs(ctx: RunContext[UnifiedDeps]) -> str: ...

@agent.tool
async def get_available_projects(ctx: RunContext[UnifiedDeps]) -> str: ...

@agent.tool
async def start_transcription(ctx: RunContext[UnifiedDeps], ...) -> str: ...

@agent.tool
async def get_transcription_status(ctx: RunContext[UnifiedDeps], job_id: str) -> str: ...
```

### Unified Dependencies

```python
@dataclass
class UnifiedDeps:
    """Dependencies für den Unified Agent — alle Domänen."""
    session_id: str
    current_page: str                    # "index" | "editor"

    # Lyrics-Domain
    job_id: str | None = None
    segments: list[dict] | None = None
    segments_path: Path | None = None
    language: str = ""
    metadata: dict | None = None

    # Editor-Domain
    project_id: str | None = None

    # State
    domain_hint: str = "auto"            # User-Override oder Auto-Detection
    segments_modified: bool = False
    editor_modified: bool = False
    navigation_target: str | None = None # Für __NAVIGATE__ Events
```

### Aufgaben

- [ ] `src/ai/unified_agent.py` erstellen
- [ ] `UnifiedDeps` Dataclass mit allen Domain-Kontexten
- [ ] PydanticAI v2 Agent mit `deps_type=UnifiedDeps`
- [ ] **Lyrics-Tools portieren:** Alle 11 Tools aus `src/ai/chat.py` → Unified Agent
- [ ] **Editor-Tools konvertieren:** `ACTION_ALLOWLIST` Items → native PydanticAI-Tools (kein Action-Block-Parsing mehr)
- [ ] **Generate-Tools:** Wrapper um `submit_generation()` und `generate_auto_scenes()`
- [ ] **Navigation-Tools:** Frontend-Events emittieren (`__NAVIGATE__`, `__CONTEXT_SWITCH__`)
- [ ] **System-Tools:** Transkription starten, Status abfragen
- [ ] Dynamischer System-Prompt: Template mit aktuellem Kontext füllen
- [ ] Tool-Filtering: Nur relevante Tools pro Domain laden (Performance)
- [ ] Reasoning-Auto-Detection übernehmen (bereits in `src/ai/chat.py`)

### Tool-Filtering Strategie

```python
def get_tools_for_context(deps: UnifiedDeps) -> list[Tool]:
    """Lade nur die Tools die zum aktuellen Kontext passen."""
    tools = NAVIGATION_TOOLS + SYSTEM_TOOLS  # immer verfügbar

    if deps.job_id:
        tools += LYRICS_TOOLS
    if deps.project_id:
        tools += EDITOR_TOOLS + GENERATE_TOOLS
    if deps.domain_hint == "lyrics":
        tools += LYRICS_TOOLS
    elif deps.domain_hint == "editor":
        tools += EDITOR_TOOLS + GENERATE_TOOLS

    return list(set(tools))  # deduplizieren
```

---

## Phase 4 — Frontend: Globaler Chat-Widget

> **Ziel:** Ein einziges Chat-Widget das auf allen Seiten verfügbar ist und über einen Toggle-Button geöffnet wird.

### Neue Dateien

```
src/
├── static/
│   ├── js/
│   │   └── unified-chat.js          # Chat-Widget Logik
│   └── css/
│       └── unified-chat.css          # Chat-Widget Styles
└── templates/
    └── partials/
        └── chat-widget.html          # Inkludierbar via Jinja2 {% include %}
```

### Alternativ (Inline in Base-Template):

```
src/templates/
└── partials/
    └── chat-widget.html          # Inkludierbar via Jinja2 {% include %}
```

### HTML-Struktur des Chat-Widgets

```html
<!-- Globaler Toggle-Button (fixed position) -->
<button id="chatToggle" class="chat-toggle" onclick="toggleUnifiedChat()">
    💬
    <span id="chatBadge" class="chat-badge" style="display:none">●</span>
</button>

<!-- Chat-Panel (slide-in von rechts) -->
<div id="unifiedChat" class="unified-chat" style="display:none">
    <!-- Header -->
    <div class="chat-header">
        <div class="chat-tabs">
            <button class="chat-tab active" data-domain="auto">🤖 Auto</button>
            <button class="chat-tab" data-domain="lyrics">🎤 Lyrics</button>
            <button class="chat-tab" data-domain="editor">🎬 Editor</button>
            <button class="chat-tab" data-domain="generate">🎨 Generate</button>
        </div>
        <div class="chat-context">
            <span id="chatPage">📄 index</span>
            <span id="chatJob">🎤 —</span>
            <span id="chatProject">🎬 —</span>
        </div>
        <button onclick="minimizeChat()">─</button>
        <button onclick="closeChat()">✕</button>
    </div>

    <!-- Messages -->
    <div id="chatMessages" class="chat-messages"></div>

    <!-- Input -->
    <div class="chat-input-area">
        <div class="chat-shortcuts">
            <button onclick="sendCommand('correct')">✏️ Korrigieren</button>
            <button onclick="sendCommand('structure')">🏷️ Struktur</button>
            <button onclick="sendCommand('scenes')">🎬 Szenen</button>
            <button onclick="sendCommand('render')">🎬 Render</button>
        </div>
        <div class="chat-input-row">
            <textarea id="chatInput" placeholder="Nachricht eingeben..."
                      onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendUnified()}">
            </textarea>
            <button onclick="sendUnified()">➤</button>
        </div>
    </div>
</div>
```

### JavaScript-Kern (`unified-chat.js`)

```javascript
// ── Globaler State ──
const UNIFIED_CHAT = {
    sessionId: localStorage.getItem('chatSessionId') || crypto.randomUUID(),
    open: false,
    minimized: false,
    domain: 'auto',
    context: {
        page: document.body.dataset.page || 'index',  // gesetzt pro Template
        jobId: null,
        projectId: null,
    },
    history: [],
};

// ── Session persistieren ──
localStorage.setItem('chatSessionId', UNIFIED_CHAT.sessionId);

// ── Nachricht senden (Streaming) ──
async function sendUnified() {
    const input = document.getElementById('chatInput');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';

    addMessage(msg, 'user');

    const body = {
        message: msg,
        session_id: UNIFIED_CHAT.sessionId,
        context: {
            page: UNIFIED_CHAT.context.page,
            job_id: UNIFIED_CHAT.context.jobId,
            project_id: UNIFIED_CHAT.context.projectId,
            domain_hint: UNIFIED_CHAT.domain,
        }
    };

    const resp = await fetch('/api/chat/unified', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
            if (!line.trim()) continue;
            const data = JSON.parse(line);
            handleStreamEvent(data);
        }
    }
}

// ── Stream-Events verarbeiten ──
function handleStreamEvent(data) {
    if (data.role === 'model') {
        updateOrAddModelMessage(data.content, data.domain);
    }
    else if (data.role === 'system') {
        if (data.content === '__SEGMENTS_UPDATED__') {
            // Segments im Hintergrund neu laden (Index-Seite)
            if (typeof reloadSegments === 'function') reloadSegments();
        }
        else if (data.content === '__TIMELINE_UPDATED__') {
            // Timeline im Editor neu laden
            if (typeof reloadTimeline === 'function') reloadTimeline();
        }
        else if (data.content.startsWith('__NAVIGATE__')) {
            // Seiten-Navigation
            const target = data.target;
            window.location.href = target;
        }
        else if (data.content === '__GEN_STARTED__') {
            // Luma-Generierung gestartet
            if (typeof refreshGenerations === 'function') refreshGenerations();
        }
    }
}

// ── Kontext-Updates von der jeweiligen Seite ──
function updateChatContext(updates) {
    Object.assign(UNIFIED_CHAT.context, updates);
    renderContextBar();
}

// Aufgerufen von index.html wenn Job geladen wird:
// updateChatContext({ jobId: '...', page: 'index' });

// Aufgerufen von editor.html wenn Projekt geladen wird:
// updateChatContext({ projectId: '...', page: 'editor' });
```

### Aufgaben

- [ ] `src/static/js/unified-chat.js` erstellen
- [ ] `src/static/css/unified-chat.css` erstellen
- [ ] Chat-Widget HTML als Jinja2-Partial: `src/templates/partials/chat-widget.html`
- [ ] **In `index.html` einbinden:** `{% include 'partials/chat-widget.html' %}` + `<body data-page="index">`
- [ ] **In `editor.html` einbinden:** `{% include 'partials/chat-widget.html' %}` + `<body data-page="editor">`
- [ ] Toggle-Button: Fixed position bottom-right, Glassmorphism-Design passend zum Theme
- [ ] Chat-Panel: Slide-in von rechts, resizable, minimierbar
- [ ] Domain-Tabs: Auto / Lyrics / Editor / Generate
- [ ] Context-Bar: Zeigt aktuelle Seite, Job-ID, Projekt-ID
- [ ] Shortcut-Buttons: Kontextabhängig (Lyrics-Shortcuts auf Index, Editor-Shortcuts im Editor)
- [ ] NDJSON-Streaming-Reader
- [ ] `__SEGMENTS_UPDATED__` Event → ruft `reloadSegments()` auf Index-Seite auf
- [ ] `__TIMELINE_UPDATED__` Event → ruft `reloadTimeline()` auf Editor-Seite auf
- [ ] `__NAVIGATE__` Event → `window.location.href` Navigation
- [ ] `__GEN_STARTED__` / `__GEN_COMPLETED__` → Luma-Status-Updates
- [ ] Markdown-Rendering für AI-Antworten (lightweight, z.B. marked.js oder eigener Parser)
- [ ] Theme-Support: Dark / Neon / Light (CSS-Variablen von `:root`)
- [ ] Keyboard-Shortcut: `Ctrl+Shift+K` → Toggle Chat
- [ ] LocalStorage: Chat-State persistieren (offen/zu, Domain, Session-ID)
- [ ] Mobile-responsive: Vollbild auf kleinen Screens

---

## Phase 5 — Cross-Page Context & Navigation

> **Ziel:** Der Chat kann Aktionen auf anderen Seiten auslösen und nahtlos zwischen Kontexten wechseln.

### Szenarien

| User sagt | Seite | Aktion |
|---|---|---|
| "Korrigiere Zeile 5" | Editor | → Lyrics-Tools nutzen (Job-ID aus verknüpftem Projekt) |
| "Füge die Lyrics als Untertitel ein" | Index | → Editor öffnen + SRT importieren |
| "Generiere 5 Szenen aus den Lyrics" | Index | → Szenen generieren + Editor öffnen |
| "Render das Video" | Index | → Zum Editor navigieren + Render starten |
| "Zeig mir die Timeline" | Index | → `__NAVIGATE__` zum Editor |
| "Starte eine Transkription" | Editor | → Job-API aufrufen, Status streamen |

### Navigation-Tool Implementierung

```python
@agent.tool
async def navigate_to_editor(ctx: RunContext[UnifiedDeps], project_id: str = "") -> str:
    """Navigiert zum Video Editor. Optional mit Projekt-ID."""
    target = "/editor"
    if project_id:
        target += f"?pid={project_id}"
    elif ctx.deps.project_id:
        target += f"?pid={ctx.deps.project_id}"
    ctx.deps.navigation_target = target
    return f"Navigiere zum Editor: {target}"
```

### Cross-Domain Workflows

```python
@agent.tool
async def import_lyrics_to_editor(ctx: RunContext[UnifiedDeps]) -> str:
    """Importiert die aktuelle Lyrics-SRT als Untertitel ins Editor-Projekt."""
    if not ctx.deps.job_id:
        return "Kein aktiver Lyrics-Job. Bitte erst eine Transkription starten."
    if not ctx.deps.project_id:
        return "Kein aktives Editor-Projekt. Soll ich eins erstellen?"

    # SRT-Pfad aus Job holen
    srt_path = OUTPUT_DIR / ctx.deps.job_id / f"{stem}.srt"
    if not srt_path.exists():
        return "SRT-Datei nicht gefunden."

    # Als Asset importieren
    from src/video.editor import add_asset
    asset = add_asset(ctx.deps.project_id, srt_path.name, srt_path)
    return f"SRT importiert als Asset {asset.id} ins Projekt {ctx.deps.project_id}."

@agent.tool
async def lyrics_from_editor_project(ctx: RunContext[UnifiedDeps]) -> str:
    """Extrahiert Lyrics aus dem Editor-Projekt für Bearbeitung."""
    if not ctx.deps.project_id:
        return "Kein aktives Editor-Projekt."
    from src/video/generation.scenes import extract_lyrics_from_project
    lyrics = extract_lyrics_from_project(ctx.deps.project_id)
    if not lyrics:
        return "Keine Lyrics/Untertitel im Projekt gefunden."
    return f"Lyrics aus Projekt extrahiert:\n\n{lyrics[:2000]}"
```

### Aufgaben

- [ ] Navigation-Tools implementieren (`navigate_to_editor`, `navigate_to_index`)
- [ ] Cross-Domain-Workflows implementieren (`import_lyrics_to_editor`, `lyrics_from_editor_project`)
- [ ] Kontext-Verknüpfung: Job-ID ↔ Projekt-ID Mapping (wenn Editor ein Karaoke-Projekt hat)
- [ ] `__NAVIGATE__` Event mit URL-Parametern (Job-ID, Projekt-ID weitergeben)
- [ ] Frontend: Chat-State über Navigation hinweg erhalten (Session-ID in localStorage)
- [ ] Frontend: Nach Navigation automatisch Chat wieder öffnen und Kontext aktualisieren

---

## Phase 6 — Luma-Szenen-Integration

> **Ziel:** Luma-Generierung nahtlos in den Unified Chat integrieren.

### Aufgaben

- [ ] `generate_video` Tool: Wrapper um `submit_generation()` mit Streaming-Status-Updates
- [ ] `generate_image` Tool: Analog für Bilder
- [ ] `generate_auto_scenes` Tool: Analysiert Lyrics → 5 Szenen-Prompts → optional direkt generieren
- [ ] `get_generation_status` Tool: Aktuellen Status aller/einzelner Generierungen
- [ ] SSE-Events von `generation/manager.py` in den Chat-Stream einbetten
- [ ] Frontend: Szenen-Vorschläge als interaktive Karten im Chat anzeigen
- [ ] "Generiere alle 5 Szenen" Batch-Befehl
- [ ] Workflow: "Analysiere den Song und erstelle ein Musikvideo" → Lyrics → Szenen → Generate → Import

---

## Phase 7 — Migration & Deprecation

> **Ziel:** Bestehende Chat-Endpunkte deprecaten und alten Code aufräumen.

### Migrationspfad

| Alt | Neu | Aktion |
|---|---|---|
| `POST /api/ai/chat/{job_id}` | `POST /api/chat/unified` | Deprecation-Header, Redirect nach 2 Releases |
| `POST /api/editor/projects/{pid}/ai-chat` | `POST /api/chat/unified` | Deprecation-Header, Redirect nach 2 Releases |
| `src/ai/chat.py` (Agent) | `src/ai/unified_agent.py` | Tools extrahieren, alter Agent bleibt als Fallback |
| `src/video/ai_tools.py` (Action-Blocks) | Native PydanticAI-Tools | Action-Block-Parser entfernen |
| `src/ai/database.py` (per-Job SQLite) | `src/ai/unified_db.py` (Session-basiert) | Migration-Script für bestehende Histories |
| `sendAI()` in `editor.html` | `unified-chat.js` | Alten Chat-UI Code entfernen |
| AI-Chat-Section in `index.html` | `unified-chat.js` | Alten Chat-UI Code entfernen |
| `src/ai/routes.py` | Deprecated markiert | |  

### Aufgaben

- [ ] Deprecation-Hinweise in alten Endpunkten (`X-Deprecated: true` Header)
- [ ] Proxy-Routes: Alte URLs → Unified-Endpunkt umleiten
- [ ] Migration-Script: `scripts/migrate_chat_history.py` — alte SQLite-DBs → Unified-Format
- [ ] Feature-Flag: `UNIFIED_CHAT_ENABLED=true/false` in `.env` (Rollback-Möglichkeit)
- [ ] Alten Chat-UI-Code in `editor.html` entfernen (Zeilen ~2356–2500)
- [ ] Alten Chat-UI-Code in `index.html` entfernen
- [ ] `src/ai/routes.py` als Deprecated markieren (nicht sofort löschen)
- [ ] `src/video/ai_tools.py` Refactoring: `_call_ai()`, `_parse_actions()`, `_execute_action()` → Services
- [ ] Tests aktualisieren

---

## Risiken & Mitigationen

| Risiko | Impact | Mitigation |
|---|---|---|
| **Zu viele Tools → Token-Explosion** | System-Prompt wird zu lang, langsame/teure Responses | Tool-Filtering: Nur Domain-relevante Tools laden |
| **Domain-Fehlklassifikation** | Falsche Tools werden aufgerufen | Domain-Hint Tab im UI + Keyword-Detection + User-Feedback |
| **Bestehende Chat-Histories verloren** | User verliert Kontext | Migration-Script + Parallelbetrieb (alt + neu) |
| **Editor-Action-Block → PydanticAI-Tool Migration** | Bestehende Editor-Chat-Logik bricht | Inkrementell migrieren, Rule-Based Parser behalten |
| **Performance: Single Agent mit 30+ Tools** | Langsame Tool-Selection | Dynamic Tool Loading, Caching, Tool-Gruppen |
| **Cross-Page Navigation UX** | User verliert Chat-Kontext bei Seitenwechsel | LocalStorage Session-ID, Chat auto-reopen nach Navigation |
| **Luma-Generierung blockiert Chat** | Long-running Operations blockieren Stream | Async Background-Tasks + SSE Status-Updates |
| **Mobile UX** | Chat-Widget zu groß/klein | Responsive Design, Vollbild-Modus auf Mobile |

---

## Dateiplan

### Neue Dateien

```
src/
├── ai/
│   ├── unified_router.py          # Einziger Chat-Endpunkt
│   ├── unified_agent.py           # PydanticAI v2 Multi-Domain Agent
│   ├── unified_db.py              # Unified Chat-Persistenz
│   └── tools/                     # Tool-Module (aufgesplittet)
│       ├── __init__.py
│       ├── lyrics_tools.py        # 11 Lyrics-Tools (extrahiert aus chat.py)
│       ├── editor_tools.py        # Editor-Tools (konvertiert aus ai_tools.py)
│       ├── generate_tools.py      # Luma-Generation-Tools
│       ├── navigation_tools.py    # Cross-Page Navigation
│       └── system_tools.py        # Transkription, Status, Config
├── static/
│   ├── js/
│   │   └── unified-chat.js        # Chat-Widget JavaScript
│   └── css/
│       └── unified-chat.css        # Chat-Widget Styles
├── templates/
│   └── partials/
│       └── chat-widget.html        # Inkludierbares Chat-Widget
scripts/
└── migrate_chat_history.py         # Migration alter Chat-DBs
```

### Geänderte Dateien

```
src/
├── ai/
│   ├── chat.py                    # → Lyrics-Tools extrahieren, Agent-Code deprecaten
│   ├── routes.py                  # → Deprecation-Header hinzufügen
│   └── database.py                # → Bleibt als Fallback, Deprecated
├── video/
│   ├── ai_tools.py                # → _call_ai() extrahieren, Action-Tools → PydanticAI
│   └── generation/
│       ├── scenes.py              # → generate_auto_scenes() als Tool wrappen
│       └── routes.py              # → Auto-Szenen Endpunkt beibehalten
├── templates/
│   ├── index.html                 # → Chat-Widget einbinden, alten Chat-Code entfernen
│   └── editor.html                # → Chat-Widget einbinden, alten Chat-Code entfernen
main.py                            # → unified_router einbinden
.env.example                       # → UNIFIED_CHAT_ENABLED hinzufügen
```

---

## Meilensteine & Zeitplan

| Phase | Beschreibung | Aufwand | Abhängigkeiten |
|---|---|---|---|
| **Phase 1** | Unified Backend Router | 1–2 Tage | Keine |
| **Phase 2** | Unified Chat Database | 1 Tag | Phase 1 |
| **Phase 3** | Unified AI Agent | 3–4 Tage | Phase 1 + 2 |
| **Phase 4** | Frontend Chat-Widget | 2–3 Tage | Phase 1 |
| **Phase 5** | Cross-Page Context | 1–2 Tage | Phase 3 + 4 |
| **Phase 6** | Luma-Integration | 1 Tag | Phase 3 |
| **Phase 7** | Migration & Cleanup | 1–2 Tage | Alle Phasen |
| **Testing** | Integration-Tests, E2E | 2 Tage | Alle Phasen |
| | **Gesamt** | **~12–16 Tage** | |

### Empfohlene Reihenfolge

```
Phase 1 (Router) ──┬──→ Phase 2 (DB) ──→ Phase 3 (Agent) ──┬──→ Phase 5 (Cross-Page)
                   │                                         │
                   └──→ Phase 4 (Frontend) ──────────────────┘──→ Phase 6 (Luma)
                                                                      │
                                                                      ▼
                                                              Phase 7 (Migration)
```

---

## Offene Entscheidungen

| Frage | Optionen | Empfehlung |
|---|---|---|
| **Chat-Widget Technologie** | Vanilla JS / Lit / Preact / Web Component | **Vanilla JS** (konsistent mit bestehendem Code) |
| **Tool-Splitting Strategie** | Alle Tools in einem Agent / Dynamisch laden | **Dynamisch laden** (Performance) |
| **Session-Management** | LocalStorage / Cookie / Server-Side | **LocalStorage** (Session-ID) + Server-DB |
| **Alte Chat-Endpunkte** | Sofort entfernen / Deprecation-Periode | **Deprecation-Periode** (2 Releases) |
| **Chat-History Migration** | Automatisch / Manuell / Nicht migrieren | **Automatisch** (Migration-Script) |
| **Rule-Based Parser (Editor)** | Beibehalten als Fallback / Entfernen | **Beibehalten** als Shortcut-Layer vor AI |

---

*Erstellt: 2026-02-22 | Projekt: Scalino1984/video-editor*