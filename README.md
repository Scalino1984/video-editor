# Karaoke Sub Tool v3.0 — Handbuch

## Übersicht

Professioneller Karaoke-Untertitel-Generator mit FastAPI WebUI, 4 Transcription-Backends, Live-Audio-Player, Waveform-Visualisierung und umfangreichem Segment-Editor.

## Features

### Transcription Backends

| Backend | Beschreibung | Word-Timestamps | Anforderung |
|---------|-------------|-----------------|-------------|
| **Voxtral** (Mistral) | Cloud API, gut für Deutsch | ✓ | `MISTRAL_API_KEY` |
| **OpenAI Whisper** | Cloud API | ✓ | `OPENAI_API_KEY` |
| **Local Whisper** | Lokal via faster-whisper | ✓ | `pip install faster-whisper` |
| **WhisperX** | Forced Phoneme Alignment | ✓✓✓ (beste!) | `pip install whisperx torch` |

WhisperX liefert die präzisesten Word-Level-Timestamps durch wav2vec2-basiertes Forced Alignment. Ideal für Karaoke.

### Export-Formate

- **SRT** — Standard-Untertitel
- **ASS** — Advanced SubStation Alpha mit Karaoke-Tags (`\k`, `\kf`, `\ko`)
- **WebVTT** — Web Video Text Tracks
- **LRC** — Lyrics-Format (Enhanced mit Word-Tags)
- **TXT** — Plain Text
- **ZIP** — Alle Outputs als Download

### Audio Player & Karaoke Preview

- Integrierter Audio-Player mit Waveform-Visualisierung
- **Live Karaoke Display** — Mitlesendes Lyrics-Highlight bei Wiedergabe
- **Playback Speed** — 0.5x bis 2x
- **Loop Segment** — Einzelnes Segment in Schleife abspielen
- **Minimap** — Übersichtsleiste aller Segmente mit Farbcodierung

### Segment Editor

- **Inline Timing** — Start/End-Zeiten direkt editierbar
- **Split/Merge** — Segmente teilen und zusammenführen
- **Time Shift** — Alle Segmente global verschieben (±ms)
- **Search & Replace** — Text suchen/ersetzen über alle Segmente
- **Speaker Labels** — Speaker-Tags zuweisen/bearbeiten
- **Pin/Bookmark** — Segmente für Review markieren
- **Confidence Filter** — Nach Confidence filtern (All / Low / Pinned / Overlap)
- **CPS Warnung** — Echtzeit-CPS pro Segment (>22 = Warnung)
- **Gap/Overlap Detektor** — Timing-Probleme erkennen und auto-fixen
- **Custom Dictionary** — Wörter-Korrekturliste (falsch → richtig)

### Undo/Redo

Bis zu 50 Schritte rückgängig machen. Funktioniert für alle Segment-Operationen.

### Keyboard Shortcuts

| Taste | Aktion |
|-------|--------|
| `Space` | Play/Pause |
| `←` / `→` | ±2 Sekunden |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+F` | Suche fokussieren |

### Batch Processing

Mehrere Dateien gleichzeitig hochladen und transkribieren.

### SSE Live Progress

Echtzeit-Fortschritt via Server-Sent Events — kein Polling nötig.

### Project Export/Import

Kompletten Projektzustand als JSON exportieren/importieren für Backup und Sharing.

## API Endpoints

### Core
- `GET /api/health` — Server-Status und Backend-Verfügbarkeit
- `GET /api/presets` — ASS Theme Presets
- `GET /api/events` — SSE Live-Stream

### Upload & Files
- `POST /api/upload` — Datei hochladen
- `GET /api/files` — Hochgeladene Dateien listen
- `DELETE /api/files/{name}` — Datei löschen
- `GET /api/files/{name}/probe` — Audio-Metadaten (Dauer, Codec, Bitrate)

### Transcription
- `POST /api/transcribe?filename=` — Job starten
- `POST /api/transcribe/batch?filenames=` — Batch-Transkription
- `POST /api/transcribe/upload` — Upload + Transkription in einem Schritt

### Jobs
- `GET /api/jobs` — Alle Jobs listen
- `GET /api/jobs/{id}` — Job-Status
- `DELETE /api/jobs/{id}` — Job löschen

### Downloads
- `GET /api/jobs/{id}/download/{file}` — Einzeldatei
- `GET /api/jobs/{id}/download-zip` — Alle als ZIP
- `GET /api/jobs/{id}/content/{file}` — Text-Content (für Clipboard)

### Segment Operations
- `GET /api/jobs/{id}/segments` — Segmente laden
- `PUT /api/jobs/{id}/segments` — Segment editieren (Text, Timing, Speaker, Pin)
- `POST /api/jobs/{id}/segments/split` — Segment teilen
- `POST /api/jobs/{id}/segments/merge` — Segmente zusammenführen
- `POST /api/jobs/{id}/segments/reorder` — Reihenfolge ändern
- `POST /api/jobs/{id}/segments/time-shift` — Global verschieben
- `POST /api/jobs/{id}/segments/search-replace` — Suchen/Ersetzen
- `POST /api/jobs/{id}/segments/toggle-pin` — Segment pinnen

### Analysis
- `GET /api/jobs/{id}/stats` — Statistiken (CPS, Wörter, Gaps, Overlaps)
- `GET /api/jobs/{id}/gaps-overlaps` — Gap/Overlap-Liste
- `POST /api/jobs/{id}/fix-gaps?strategy=` — Auto-Fix (extend/shrink/split)
- `GET /api/jobs/{id}/waveform` — Waveform-Daten
- `GET /api/jobs/{id}/report` — Confidence Report

### Tools
- `POST /api/jobs/{id}/undo` / `redo` — Undo/Redo
- `POST /api/jobs/{id}/regenerate-ass` — Formate neu generieren
- `POST /api/jobs/{id}/apply-dictionary` — Dictionary anwenden
- `POST /api/jobs/{id}/translate` — Übersetzen (Placeholder)
- `GET /api/jobs/{id}/speakers` — Speaker-Liste
- `POST /api/jobs/{id}/speakers/assign` — Speaker zuweisen

### Dictionary
- `GET /api/dictionary` — Custom Dictionary laden
- `PUT /api/dictionary` — Dictionary speichern

### Project
- `GET /api/jobs/{id}/project-export` — Projekt als JSON
- `POST /api/jobs/{id}/project-import` — Projekt importieren

## Config (config.yaml)

```yaml
transcription:
  backend: voxtral     # voxtral | openai_whisper | local_whisper | whisperx
  language: auto       # de | en | auto | fr | es | ja | ko | zh
whisperx:
  model_size: large-v3 # tiny | base | small | medium | large-v3
  compute_type: float16
  batch_size: 16
refinement:
  cps: 18.0            # max characters per second
  max_chars_per_line: 42
  max_lines: 2
karaoke:
  mode: kf             # k | kf | ko
```

## CLI (Legacy)

```bash
python -m src.cli transcribe audio.mp3 --backend whisperx --language de
python -m src.cli batch ./music/ --backend voxtral --output ./subs/
python -m src.cli watch ./incoming/ --backend local_whisper
```

## AI Chat (PydanticAI v2)

Integrierter KI-Assistent der direkt auf Segmente zugreifen und sie bearbeiten kann.

### Konfiguration (.env)

```bash
# Model format: provider:model-name
AI_MODEL=openai:gpt-4o                         # Standard-Modell
AI_REASONING_MODEL=openai:o3-mini               # Reasoning (optional)
# oder:
AI_MODEL=anthropic:claude-sonnet-4-20250514
AI_REASONING_MODEL=anthropic:claude-opus-4-20250514

# API Key (passend zum Provider)
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
```

### AI-Befehle

| Befehl | Funktion | Model |
|--------|----------|-------|
| 🔧 Korrigieren | Transkriptionsfehler via Reimschema/Kontext fixen | Reasoning |
| ✏️ Interpunktion | Satzzeichen setzen ohne Wortlaut zu ändern | Standard |
| 🏗️ Struktur | Verse/Hook/Bridge/Outro erkennen → Speaker-Labels | Reasoning |
| 🌍 Translate | Lyrics übersetzen mit Reim-/Silbenerhaltung | Reasoning |
| ✨ Generate | Fehlende Lyrics basierend auf Kontext generieren | Standard |

### API Endpoints

- `GET /api/ai/health` — AI-Konfiguration prüfen
- `GET /api/ai/chat/{job_id}` — Chat-Verlauf laden
- `POST /api/ai/chat/{job_id}` — Nachricht senden (Streaming)
- `DELETE /api/ai/chat/{job_id}` — Chat-Verlauf löschen

### Agent Tools

Der AI-Agent hat folgende Tools zur Verfügung:
- `get_all_segments` — Alle Segmente lesen
- `get_segment(index)` — Einzelnes Segment lesen
- `get_low_confidence_segments(threshold)` — Schwache Segmente finden
- `get_song_metadata` — Metadaten lesen
- `update_segment_text(index, text)` — Einzelnes Segment ändern
- `update_multiple_segments(changes)` — Bulk-Änderungen
- `set_speaker_labels(labels)` — Speaker-Labels setzen
- `add_to_dictionary(entries)` — Dictionary-Einträge hinzufügen

## BPM Detection (Essentia)

BPM-Erkennung nutzt primär **Essentia** (RhythmExtractor2013, genauer für elektronische Musik und Rap), mit **librosa** als Fallback.

```bash
pip install essentia    # Empfohlen
pip install librosa     # Fallback
```

## Starten

```bash
cd karaoke-sub-tool
pip install -r requirements.txt
python main.py                    # http://localhost:8000
python main.py --host 0.0.0.0    # LAN-Zugriff
python main.py --reload           # Dev-Modus
```
