# Copilot Instructions — Karaoke Sub Tool

## Projekt-Identität

**Name:** Karaoke Sub Tool (karaoke-sub-tool)  
**Version:** 3.2.0  
**Sprache:** Python ≥ 3.10 (Ziel: 3.12)  
**Framework:** FastAPI (Server) + Typer (CLI) + PydanticAI v2 (AI-Chat)  
**DB:** SQLite (Library + Chat-History, kein ORM)  
**UI:** SPA in `src/templates/index.html` + `editor.html`  
**Linter:** Ruff (line-length=120, target py312)  
**Tests:** pytest mit `asyncio_mode = "auto"`  
**Sprache der Benutzeroberfläche & Prompts:** Deutsch  
**Sprache des Codes & Kommentare:** Englisch  

---

## Architektur-Überblick

```
main.py                      ← FastAPI-App + Uvicorn-Einstieg
src/
  cli.py                     ← Typer CLI (transcribe, refine, export, preview, watch, menu)
  api/
    models.py                ← Pydantic v2 Schemas (Request/Response)
    routes.py                ← REST-API (60+ Endpunkte unter /api/*)
    tasks.py                 ← Background-Job-Manager (ThreadPoolExecutor, SSE, Undo/Redo)
  transcription/
    base.py                  ← ABC + Daten-Klassen (WordInfo, TranscriptSegment, TranscriptResult)
    voxtral.py               ← Mistral AI Voxtral Backend
    openai_whisper.py         ← OpenAI Whisper API Backend
    local_whisper.py          ← faster-whisper (lokal) Backend
    whisperx_backend.py       ← WhisperX mit Forced Alignment
  preprocess/
    ffmpeg_io.py             ← FFmpeg-Wrapper (convert, probe, duration)
    normalize.py             ← Lautstärke-Normalisierung (LUFS)
    vad.py                   ← Voice Activity Detection (webrtcvad)
    vocals.py                ← Vocal Isolation (Demucs)
  refine/
    text_cleanup.py          ← Text-Bereinigung (Whitespace, Quotes, Dictionary)
    alignment.py             ← Wort-Timestamp-Approximation (Silbengewichtung)
    segmentation.py          ← Split/Merge/Gaps/Line-Breaks
    beatgrid.py              ← BPM-Erkennung + Beat-Snap (Essentia/librosa)
    confidence.py            ← Qualitäts-Report (SegmentReport, FileReport)
    lyrics_align.py          ← Greedy Lyrics→ASR Alignment
    cps_fixer.py             ← CPS Auto-Fix (Split/Trim)
    gap_filler.py            ← Lücken-Management (♪-Fill, Redistribute)
    rhyme.py                 ← Reimschema-Erkennung (DE/EN, Rap-optimiert)
    structure.py             ← Song-Struktur (Verse/Chorus/Bridge/Hook)
    text_stats.py            ← Textstatistik (TTR, Hapax, Flow-Score)
    review_tui.py            ← Terminal-Review mit Rich
  export/
    srt_writer.py            ← SRT lesen/schreiben
    ass_writer.py            ← ASS mit Karaoke-Tags + Themes
    ass_template.py          ← ASS-Template laden/mergen
    vtt_writer.py            ← WebVTT lesen/schreiben
    lrc_writer.py            ← Enhanced LRC mit Word-Level-Tags
    txt_writer.py            ← Plain Text Export
    karaoke_html.py          ← Standalone HTML-Karaoke-Player
    karaoke_tags.py          ← ASS \k/\kf/\ko Tag-Generator
    themes.py                ← 6 ASS-Presets (ASSTheme Dataclass)
    video_markers.py         ← Resolve EDL, Premiere CSV, YouTube Chapters, ffmeta
  ai/
    chat.py                  ← PydanticAI v2 Agent (5 Commands, 8 Tools)
    routes.py                ← Streaming-Chat-API (NDJSON)
    database.py              ← Chat-History SQLite (ModelMessage-Speicher)
  db/
    library.py               ← Transcriptions + Media Registry (SQLite CRUD)
    routes.py                ← Library REST-API + Video-Render-Endpunkte
  video/
    editor.py                ← Timeline-Editor (Project/Asset/Clip/Effect)
    editor_routes.py         ← Editor REST-API (20+ Endpunkte)
    render.py                ← ffmpeg Video-Rendering (Presets, Filtergraph)
    ai_tools.py              ← Editor-AI mit Action-Parsing
  lyrics/
    template.py              ← Lyrics-Parser (.txt/.lrc, Sektionserkennung)
    reports.py               ← Alignment-Report (Match-Score, Diff)
  media/
    tags.py                  ← Media-Tag R/W (mutagen: ID3/MP4/Vorbis)
  preview/
    render.py                ← Preview-Clip-Rendering (ffmpeg)
  watch/
    watchdog.py              ← File-Watcher mit Debounce
  utils/
    config.py                ← AppConfig (Pydantic) + YAML-Loader
    cache.py                 ← Pipeline-Cache (.karaoke_cache/)
    deps_check.py            ← Dependency-Prüfung (ffmpeg, API-Keys, libs)
    logging.py               ← Rich-Logging (Verbosity, farbige Ausgabe)
  static/
    index.html               ← WebUI SPA
    editor.html              ← Video-Editor SPA
data/
  uploads/                   ← Hochgeladene Audio-/Textdateien
  output/{job_id}/           ← Job-Artefakte (SRT, ASS, segments.json, ...)
  editor/                    ← Editor Assets, Projekte, Renders
  library.sqlite             ← Library-Datenbank
```

---

## Kern-Datentypen

### `TranscriptSegment` (src/transcription/base.py)
Die **zentrale Datenstruktur** — fließt durch die gesamte Pipeline:

```python
@dataclass
class TranscriptSegment:
    start: float              # Startzeit in Sekunden
    end: float                # Endzeit in Sekunden
    text: str                 # Untertitel-Text
    words: list[WordInfo]     # Wort-Level-Timestamps (optional)
    confidence: float = 1.0   # 0.0–1.0
    has_word_timestamps: bool = False

@dataclass
class WordInfo:
    start: float
    end: float
    word: str
    confidence: float = 1.0
```

- Serialisierung: `to_dict()` / `from_dict(d)` — überall verwendet
- Persistiert als `segments.json` pro Job (JSON-Array von Dicts)
- Zusätzliche Runtime-Felder in segments.json: `speaker`, `pinned`

### `AppConfig` (src/utils/config.py)
Pydantic BaseModel mit Sub-Configs:
`PreprocessConfig`, `TranscriptionConfig`, `WhisperXConfig`, `RefinementConfig`, `BeatGridConfig`, `KaraokeConfig`, `ThemeConfig`, `PreviewConfig`, `CacheConfig`, `ConfidenceConfig`

Geladen aus `config.yaml` via `load_config()`, CLI-Overrides via `merge_cli_overrides(cfg, {"dotted.key": value})`.

### `JobInfo` / `JobResult` (src/api/models.py)
In-Memory Job-Tracking mit 9 Status-Werten: `pending` → `preprocessing` → `transcribing` → `refining` → `exporting` → `rendering_preview` → `completed` / `failed`.

---

## Pipeline-Fluss (Transkriptions-Job)

```
Audio → Vocal Isolation? → WAV 16kHz → Normalize? → VAD? → Transkription
  → VAD Remap → Cache → Text Cleanup → Word Timestamps → Segmentation
  → Lyrics Alignment? → BPM Snap? → AI Correction? → Export (SRT/ASS/VTT/LRC/TXT)
  → Confidence Report → Preview? → Waveform → segments.json → Library DB
```

Implementiert in `src/api/tasks.py::_transcribe_sync()` (Server) und `src/cli.py::_process_single_file()` (CLI).

---

## Coding-Konventionen

### Python-Style
- **`from __future__ import annotations`** — in jeder Datei verwenden
- **Type-Hints** — überall, `X | None` statt `Optional[X]`
- **Dataclasses** für Daten-Container (base.py, confidence.py, rhyme.py, etc.)
- **Pydantic BaseModel** nur für API-Schemas und Config
- **Docstrings** — Module und öffentliche Funktionen, einzeilig wenn möglich
- **Ruff** — 120 Zeichen Zeilenlänge, keine F-String-Backslash-Escapes
- **Imports** — `from __future__` → stdlib → third-party → local (`src.*`)

### Namenskonventionen
- **Dateien**: `snake_case.py`
- **Klassen**: `PascalCase` (TranscriptSegment, ASSTheme, VoxtralBackend)
- **Funktionen**: `snake_case` (write_srt, detect_bpm, snap_segments_to_grid)
- **Private Funktionen**: `_prefix` (_safe_stem, _emit_sse, _transcribe_sync)
- **Konstanten**: `UPPER_SNAKE` (SUPPORTED_FORMATS, RENDER_PRESETS, MAX_UNDO)
- **Enums**: PascalCase-Klasse, lowercase-Values (BackendEnum.voxtral)

### Error-Handling
- **Non-critical Fehler**: `warn()` + weitermachen (Waveform, Library-Save, Media-Registry)
- **Critical Fehler**: `error()` + Exception / `raise HTTPException`
- **Jobs**: try/except mit `update_job(status=JobStatus.failed, error=str(e))`
- **Backends**: `check_available() → (bool, msg)` vor Nutzung

### Logging
Immer von `src.utils.logging` importieren, NIE stdlib `logging` direkt:
```python
from src.utils.logging import info, success, warn, error, debug
```

### API-Routen
- Prefix `/api/` für alle API-Endpunkte
- `BackgroundTasks` für langläufige Jobs
- `tasks.push_undo(job_id)` vor jeder Segment-Mutation
- `_save_segs(p, data, job_id)` synchronisiert automatisch `.srt`
- SSE via `_emit_sse()` für Echtzeit-Updates

---

## Datei-Speicherung

### Pro Job: `data/output/{job_id}/`
```
{stem}.srt                   # SRT-Untertitel
{stem}.ass                   # ASS-Karaoke
{stem}.vtt / .lrc / .txt     # Weitere Formate (optional)
{stem}.report.json           # Konfidenz-Report
{stem}_karaoke.html          # Standalone HTML (optional)
segments.json                # Bearbeitbare Segmente (CRUD-Quelle)
waveform.json                # Waveform-Peaks für UI
{original_audio_copy}        # Kopie für Playback
.chat_history.sqlite         # AI-Chat pro Job
snapshots/snap_*.json        # Segment-Snapshots
```

### Wichtig
- `segments.json` ist die **Single Source of Truth** für Segment-Editing
- SRT wird bei jeder Segment-Änderung automatisch synchronisiert (`_sync_srt`)
- ASS wird nur explizit regeneriert (Karaoke-Tags müssen neu berechnet werden)
- Undo-Stack: max 50 Schritte, speichert komplettes `segments.json` als String

---

## Backends & Dependencies

| Backend | Paket | API-Key Env-Var | Besonderheiten |
|---------|-------|-----------------|----------------|
| Voxtral | `mistralai` | `MISTRAL_API_KEY` | Default-Backend, Diarization |
| OpenAI Whisper | `openai` | `OPENAI_API_KEY` | `whisper-1` Modell |
| Local Whisper | `faster-whisper` | — | Kein API-Key, GPU optional |
| WhisperX | `whisperx` + `torch` | `HF_TOKEN` (Diarization) | Forced Alignment, präziseste Word-Timestamps |

### Optionale Dependencies
- **Demucs** (`demucs`): Vocal Isolation
- **Essentia** (`essentia`): BPM-Erkennung (bevorzugt vor librosa)
- **librosa**: BPM-Fallback
- **webrtcvad**: Voice Activity Detection
- **PydanticAI** (`pydantic-ai`): AI-Chat-System
- **mutagen**: Media-Tag-Lesen/Schreiben

---

## AI-Chat-System

### Konfiguration (.env)
```
AI_MODEL=openai:gpt-5.2           # oder anthropic:claude-*, mistral:*, google:*
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=...
# MISTRAL_API_KEY=... (auch für Voxtral-Backend)
```

### Agent-Architektur (src/ai/chat.py)
- PydanticAI v2 Agent mit `ChatDeps` (job_id, segments, output_dir, metadata)
- 5 Commands: `correct`, `punctuate`, `structure`, `translate`, `generate`
- 4 Read-Tools: `get_all_segments`, `get_segment`, `get_low_confidence_segments`, `get_song_metadata`
- 4 Write-Tools: `update_segment_text`, `update_multiple_segments`, `set_speaker_labels`, `add_to_dictionary`
- Reasoning-Auto-Detection für o1/o3/GPT-5/Claude Opus Modelle
- Chat-History in SQLite pro Job (`.chat_history.sqlite`)

### Editor-AI (src/video/ai_tools.py)
- Eigener System-Prompt mit `\`\`\`action`-Block-Parsing
- Multi-Provider via `_call_ai()` (OpenAI, Anthropic, Mistral, Google)
- Direkte Editor-Aktionen: add_clip, remove_clip, update_clip, split, effects, render

---

## Häufige Patterns

### Neues Export-Format hinzufügen
1. Datei in `src/export/{format}_writer.py` erstellen
2. `write_{format}(segments: list[TranscriptSegment], output_path: Path)` implementieren
3. Enum-Wert in `ExportFormatEnum` (models.py) hinzufügen
4. In `_transcribe_sync()` (tasks.py) und `_export_sync()` einbauen
5. In `regenerate_ass` Route (routes.py) einbauen

### Neues Transkriptions-Backend hinzufügen
1. Datei in `src/transcription/{name}.py` erstellen
2. `TranscriptionBackend` ABC implementieren (`transcribe()`, `check_available()`)
3. In `_get_backend()` Factory (tasks.py + cli.py) registrieren
4. `BackendEnum` in models.py erweitern
5. `check_{name}` in deps_check.py hinzufügen

### Neue Refinement-Stufe hinzufügen
1. Datei in `src/refine/{name}.py` erstellen
2. Funktion: `list[TranscriptSegment] → list[TranscriptSegment]`
3. In `_transcribe_sync()` Pipeline einbauen (nach Segmentation, vor Export)
4. Optional: API-Route in routes.py für On-Demand-Aufruf

### Segment-Mutation via API
```python
tasks.push_undo(job_id)           # IMMER vor Mutation
p, data = _load_segs(job_id)      # segments.json laden
# ... data modifizieren ...
_save_segs(p, data, job_id)       # speichern + SRT-Sync
```

---

## Testing

```bash
pytest tests/                     # Alle Tests
pytest tests/test_core.py -v      # Core-Tests (Serialisierung, Writer, Refinement)
pytest tests/test_library.py      # Library-DB-Tests
pytest tests/test_v31.py          # Feature-Tests v3.1
```

Tests nutzen `tmp_path` Fixture für Datei-I/O. Keine Mocks für TranscriptSegment — direkt instanziieren.

---

## Server starten

```bash
# Direkt
python main.py --host 127.0.0.1 --port 8000

# Via Script
./server.sh start
./server.sh status
./server.sh log

# CLI
python -m src.cli transcribe --input audio.mp3 --backend voxtral --ass
python -m src.cli refine --input subs/ --cps 18
python -m src.cli export --input subs/ --karaoke-mode kf --preset neon
```

---

## Wichtige Regeln

1. **`segments.json` ist die Single Source of Truth** — alle Segment-Edits gehen darüber
2. **Undo vor jeder Mutation** — `push_undo(job_id)` in jeder Route die Segmente ändert
3. **SSE für Echtzeit-Updates** — `_emit_sse()` für Job-Progress und Completion
4. **Thread-Safety** — `_emit_sse()` nutzt `call_soon_threadsafe`, Jobs laufen im ThreadPoolExecutor
5. **Lazy Imports** — Backends und schwere Libs nur bei Bedarf importieren (in Funktionen, nicht auf Modul-Level)
6. **Keine harten Abhängigkeiten** — optionale Features graceful degraden (try/except ImportError)
7. **Dateiname-Sanitization** — `_safe_stem()` für alle user-generierten Dateinamen
8. **UTF-8 überall** — `encoding="utf-8"` bei allen Datei-Operationen explizit angeben
9. **Karaoke-Tags brauchen Word-Timestamps** — `ensure_word_timestamps()` vor ASS-Export aufrufen
10. **Config via Dot-Notation** — `merge_cli_overrides(cfg, {"transcription.backend": "whisperx"})`

---

## Internes Entwicklungsverzeichnis: `.intern/`

Das Verzeichnis `.intern/` (in `.gitignore`, wird **nicht** mit GitHub synchronisiert) dient als zentraler Ablageort für alle internen Entwicklungsdokumente:

```
.intern/
  BESTANDSAUFNAHME.md                ← Vollständige Code-Inventur (PFLICHTDOKUMENT)
  worklog/
    YYYY-MM.md                       ← Monatliches Arbeitsprotokoll (Journal)
  changes/
    YYYYMMDD-<kurztitel>.md           ← Change-Reports (Refactor/Security/Arch/Breaking)
  archive/
    worklog/
      YYYY-MM.md                     ← Archivierte/komprimierte ältere Worklogs
```

### Regeln für `.intern/`

1. **Alle Entwicklungsdokumente** (Analysen, Audits, Planungen, Protokolle, Notizen) werden **ausschließlich in `.intern/`** gespeichert — **niemals** im Repository-Root oder anderen Verzeichnissen
2. **Keine internen Dokumente im Repo** — nur `README.md`, `HANDBUCH.md`, `API.md` und Code-Dateien werden committed
3. **Keine sensiblen Secrets** in Protokollen (Tokens, Passwörter, Private Keys) — wenn relevant: `[REDACTED]`

---

### Arbeitsschritte protokollieren (Pflichtverhalten)

1. **Zu Beginn jeder Bearbeitung**:
   - Ziel (1–2 Sätze)
   - Annahmen (nur wenn nötig, als `[ASSUMPTION]`)
   - Plan (max. 5 Schritte)

2. **Nach JEDEM einzelnen Schritt** (auch Teilschritte) muss das Worklog aktualisiert werden:
   - Pfad: `.intern/worklog/YYYY-MM.md` (monatliches Sammellog)
   - Zusätzlich bei größeren Änderungen (Refactor/Security/Arch/Breaking Change): `.intern/changes/YYYYMMDD-<kurztitel>.md`

3. **Protokolleinträge müssen reproduzierbar sein**:
   - Konkrete Dateien/Module nennen
   - Commands/Tests zur Verifikation angeben (oder „nicht ausgeführt" begründen)
   - Risiken/Side-Effects dokumentieren

4. **Workflow-Änderungen nur nach Bestätigung**:
   Eine „Workflow-Änderung" betrifft Prozesse, Regeln, Dateistrukturen oder Konventionen (Protokoll-Pfade, Log-Format, Konsolidierungsregeln, Verifikationsanforderungen, Trigger).
   → Vor Umsetzung als **„VORSCHLAG – BESTÄTIGUNG ERFORDERLICH"** formulieren mit: Was ändert sich, warum, Auswirkungen, Migration. Erst nach expliziter Bestätigung anwenden.

---

### Worklog-Format (monatlich)

Füge am Anfang der Datei einen Datum-Header hinzu, wenn nicht vorhanden.

**Eintrag-Format** (immer so schreiben):
```markdown
### YYYY-MM-DD HH:MM

- **Kontext:** Ticket/Issue/PR/Branch (wenn unbekannt: "n/a")
- **Ziel:** …
- **Schritt:** <kurze Bezeichnung des gerade erledigten Schritts>
- **Status:** IN_ARBEIT | ERLEDIGT | VERWORFEN
- **Änderungen:**
  - `<pfad>` — <Änderung> (<Grund>)
- **Risiken/Side-Effects:** …
- **Verifikation:**
  - `<command/test>` → ✅/❌/— + Kurzinfo
```

---

### Change-Report-Format (bei größeren Änderungen)

Datei: `.intern/changes/YYYYMMDD-<kurztitel>.md`

```markdown
# <Titel>
- **Datum/Zeit:** YYYY-MM-DD HH:MM (Europe/Berlin)
- **Kontext:** …
- **Motivation:** …
- **Umsetzung:** (Stichpunkte, betroffene Dateien)
- **Sicherheits-/Compliance-Aspekte:** (falls relevant)
- **Rollback-Plan:** (kurz)
- **Verifikation:** (Commands/Tests + Ergebnis)
```

---

### Pflege- und Aufräumregeln

Diese Regeln sind verpflichtend und bei JEDEM Log-Update anzuwenden:

1. **Keine TODO-/Checklisten im Worklog** — Worklog ist ein Journal, keine Aufgabenliste. Nur der gerade bearbeitete Schritt wird protokolliert.

2. **Erledigte Schritte komprimieren** — Einträge mit Status `ERLEDIGT` oder `VERWORFEN` am selben Tag auf 1–3 Bullets reduzieren (Dateien + Kernaussage). Redundante Zwischenstände entfernen — nur letzter gültiger Stand bleibt.

3. **Tagesabschluss-Konsolidierung** — Mehrere Updates zum gleichen Ziel am selben Tag zu einem konsolidierten Eintrag zusammenfassen. Vorherige Zwischenstände vollständig löschen.

4. **Größenlimit & Rotation** — Wenn `.intern/worklog/YYYY-MM.md` > ~300 Zeilen: zuerst konsolidieren (Punkt 2–3). Falls weiterhin zu groß: ältere erledigte Einträge nach `.intern/archive/worklog/YYYY-MM.md` verschieben. Im aktuellen Worklog bleibt nur der laufende Monat in kompakter Form.

5. **Nur Relevantes behalten** — Einträge ohne echte Änderung entfernen oder in „Analyse" innerhalb des finalen Eintrags konsolidieren. Keine Duplikate von Befehlen/Outputs.

---

### Ausgabeformat im Chat

Wenn Protokolle erzeugt/aktualisiert werden, immer angeben:
- Liste der neu/aktualisierten Protokolldateien
- Den vollständigen Inhalt der Dateien im Markdown-Block

---

### DOM-Registry — Pflege & Konsistenzprüfung

Die Datei `.intern/dom-registry.json` ist die **kanonische Referenz** für alle Frontend-IDs, CSS-Klassen, Selektoren und Funktionsnamen:

- **Vor jeder Änderung an HTML/JS/CSS**: `.intern/dom-registry.json` lesen und alle betroffenen IDs/Selektoren/Funktionsnamen prüfen
- **Nach jeder Änderung an HTML/JS/CSS**: `.intern/dom-registry.json` aktualisieren — neue/umbenannte/entfernte IDs, Selektoren und Funktionsnamen eintragen
- **Konsistenzcheck durchführen**: Bei jeder Änderung HTML ↔ JS ↔ CSS gegenseitig abgleichen (getElementById-Strings müssen im HTML existieren, Inline-Handler-Ziele müssen als Funktionen definiert sein)
- **Dynamische Selektoren unter `dynamic_or_unknown`** dokumentieren — nie raten, ob ein Selektor statisch funktioniert
- **Issues-Sektion pflegen**: Neue Inkonsistenzen sofort unter `issues` eintragen, behobene entfernen

---

### BESTANDSAUFNAHME.md — Pflege & Protokoll

Die Datei `.intern/BESTANDSAUFNAHME.md` ist die **verbindliche Referenz** für den aktuellen Stand des Codes:

- **Vor jeder größeren Änderung**: Bestandsaufnahme lesen, um den aktuellen Stand zu kennen
- **Nach jeder strukturellen Änderung** (neue Dateien, neue Module, geänderte APIs, neue Endpunkte, geänderte Datentypen): Bestandsaufnahme **aktualisieren**
- **Änderungsprotokoll führen**: Am Ende der Bestandsaufnahme ein `## Änderungsprotokoll` pflegen mit Datum, Beschreibung der Änderung und betroffenen Modulen
- **Format beibehalten**: Bestehende Struktur (Module → Dateien → Funktionen/Klassen → Abhängigkeiten) nicht ändern, nur ergänzen/aktualisieren
- **An die Bestandsaufnahme halten**: Die dort dokumentierte Architektur und die beschriebenen Patterns sind verbindlich — Abweichungen nur nach bewusster Entscheidung und Aktualisierung
