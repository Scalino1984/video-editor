# Karaoke Sub Tool – API-Dokumentation

Basis-URL: `http://localhost:8000`

---

## Inhaltsverzeichnis

- [Transkription](#transkription)
  - [Upload + Transkription in einem Schritt](#1-upload--transkription-in-einem-schritt)
  - [Getrennt: Upload, dann Transkription](#2-getrennt-upload-dann-transkription)
  - [Batch-Transkription](#3-batch-transkription)
- [Jobs verwalten](#jobs-verwalten)
  - [Alle Jobs auflisten](#alle-jobs-auflisten)
  - [Job-Status abfragen](#job-status-abfragen)
  - [Job löschen](#job-löschen)
- [Ergebnisse herunterladen](#ergebnisse-herunterladen)
  - [Einzelne Datei](#einzelne-datei-herunterladen)
  - [Alle Dateien als ZIP](#alle-dateien-als-zip)
  - [Dateiinhalt anzeigen](#dateiinhalt-anzeigen)
- [Segmente bearbeiten](#segmente-bearbeiten)
  - [Segmente anzeigen](#segmente-anzeigen)
  - [Segment bearbeiten](#segment-bearbeiten)
  - [Segment teilen](#segment-teilen)
  - [Segmente zusammenführen](#segmente-zusammenführen)
  - [Segment verschieben](#segment-verschieben)
  - [Zeitverschiebung](#zeitverschiebung)
  - [Suchen & Ersetzen](#suchen--ersetzen)
  - [Segment anheften](#segment-anheften)
- [Wörterbuch](#wörterbuch)
- [Speaker-Zuweisung](#speaker-zuweisung)
- [Lücken & Überlappungen](#lücken--überlappungen)
- [Export & Refine](#export--refine)
- [Übersetzung](#übersetzung)
- [Undo / Redo](#undo--redo)
- [Sonstiges](#sonstiges)
- [Parameterreferenz](#parameterreferenz)

---

## Transkription

### 1. Upload + Transkription in einem Schritt

**`POST /api/transcribe/upload`** – Einfachster Weg: Datei hochladen und sofort transkribieren.

```bash
# Minimal – alle Defaults (backend=voxtral, language=auto, karaoke_mode=kf, preset=classic)
curl -X POST http://localhost:8000/api/transcribe/upload \
  -F "file=@meinsong.mp3"

# Deutsche Sprache, WhisperX-Backend
curl -X POST "http://localhost:8000/api/transcribe/upload?backend=whisperx&language=de" \
  -F "file=@meinsong.mp3"

# Mit allen verfügbaren Query-Parametern
curl -X POST "http://localhost:8000/api/transcribe/upload?backend=voxtral&language=de&generate_ass=true&karaoke_mode=kf&preset=neon" \
  -F "file=@meinsong.mp3"
```

**Query-Parameter:**

| Parameter      | Typ     | Default   | Beschreibung               |
|----------------|---------|-----------|----------------------------|
| `backend`      | string  | `voxtral` | Transkriptions-Backend     |
| `language`     | string  | `auto`    | Sprache der Audiodatei     |
| `generate_ass` | boolean | `true`    | ASS-Untertitel generieren  |
| `karaoke_mode` | string  | `kf`      | Karaoke-Modus              |
| `preset`       | string  | `classic` | Visuelles Preset           |

**Antwort:** `JobInfo`-Objekt mit `job_id` zum Nachverfolgen.

---

### 2. Getrennt: Upload, dann Transkription

#### Schritt 1: Datei hochladen

**`POST /api/upload`**

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@meinsong.mp3"
```

#### Schritt 2: Transkription starten

**`POST /api/transcribe?filename=<dateiname>`**

```bash
# Mit Defaults
curl -X POST "http://localhost:8000/api/transcribe?filename=meinsong.mp3" \
  -H "Content-Type: application/json" \
  -d '{}'

# Mit angepassten Parametern
curl -X POST "http://localhost:8000/api/transcribe?filename=meinsong.mp3" \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "whisperx",
    "language": "de",
    "vad": true,
    "vad_aggressiveness": 2,
    "normalize": true,
    "target_lufs": -16.0,
    "vocal_isolation": false,
    "word_timestamps": "auto",
    "generate_ass": true,
    "generate_vtt": true,
    "generate_txt": true,
    "karaoke_mode": "kf",
    "preset": "classic",
    "max_chars_per_line": 42,
    "max_lines": 2,
    "min_duration": 1.0,
    "max_duration": 6.0,
    "cps": 18.0
  }'

# Preview-Video mit generieren
curl -X POST "http://localhost:8000/api/transcribe?filename=meinsong.mp3" \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "voxtral",
    "language": "de",
    "generate_preview": true,
    "preview_duration": "15s",
    "preview_start": "0s",
    "preview_resolution": "1920x1080"
  }'
```

---

### 3. Batch-Transkription

**`POST /api/transcribe/batch`** – Mehrere bereits hochgeladene Dateien auf einmal transkribieren.

```bash
curl -X POST "http://localhost:8000/api/transcribe/batch?filenames=song1.mp3&filenames=song2.mp3&filenames=song3.mp3" \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "voxtral",
    "language": "de",
    "karaoke_mode": "kf",
    "preset": "classic"
  }'
```

---

## Jobs verwalten

### Alle Jobs auflisten

**`GET /api/jobs`**

```bash
curl http://localhost:8000/api/jobs
```

### Job-Status abfragen

**`GET /api/jobs/{job_id}`**

```bash
curl http://localhost:8000/api/jobs/abc123

# Kompakt mit jq
curl -s http://localhost:8000/api/jobs/abc123 | jq '{status, progress, stage}'
```

**Mögliche Status-Werte:** `pending` → `queued` → `preprocessing` → `transcribing` → `refining` → `exporting` → `rendering_preview` → `completed` / `failed`

### Job löschen

**`DELETE /api/jobs/{job_id}`**

```bash
curl -X DELETE http://localhost:8000/api/jobs/abc123
```

---

## Ergebnisse herunterladen

### Einzelne Datei herunterladen

**`GET /api/jobs/{job_id}/download/{filename}`**

```bash
curl -O http://localhost:8000/api/jobs/abc123/download/meinsong.ass
curl -O http://localhost:8000/api/jobs/abc123/download/meinsong.srt
```

### Alle Dateien als ZIP

**`GET /api/jobs/{job_id}/download-zip`**

```bash
curl -o ergebnis.zip http://localhost:8000/api/jobs/abc123/download-zip
```

### Dateiinhalt anzeigen

**`GET /api/jobs/{job_id}/content/{filename}`**

```bash
curl http://localhost:8000/api/jobs/abc123/content/meinsong.ass
```

---

## Segmente bearbeiten

### Segmente anzeigen

**`GET /api/jobs/{job_id}/segments`**

```bash
curl http://localhost:8000/api/jobs/abc123/segments
```

### Segment bearbeiten

**`PUT /api/jobs/{job_id}/segments`**

```bash
curl -X PUT http://localhost:8000/api/jobs/abc123/segments \
  -H "Content-Type: application/json" \
  -d '{
    "index": 0,
    "text": "Korrigierter Text",
    "start": 1.5,
    "end": 4.2
  }'
```

### Segment teilen

**`POST /api/jobs/{job_id}/segments/split`**

```bash
curl -X POST http://localhost:8000/api/jobs/abc123/segments/split \
  -H "Content-Type: application/json" \
  -d '{"index": 3, "split_at": 2.5}'
```

### Segmente zusammenführen

**`POST /api/jobs/{job_id}/segments/merge`**

```bash
curl -X POST http://localhost:8000/api/jobs/abc123/segments/merge \
  -H "Content-Type: application/json" \
  -d '{"indices": [2, 3]}'
```

### Segment verschieben

**`POST /api/jobs/{job_id}/segments/reorder`**

```bash
curl -X POST http://localhost:8000/api/jobs/abc123/segments/reorder \
  -H "Content-Type: application/json" \
  -d '{"from_index": 5, "to_index": 2}'
```

### Zeitverschiebung

**`POST /api/jobs/{job_id}/segments/time-shift`**

```bash
curl -X POST http://localhost:8000/api/jobs/abc123/segments/time-shift \
  -H "Content-Type: application/json" \
  -d '{"indices": [0, 1, 2], "shift_ms": 500}'
```

### Suchen & Ersetzen

**`POST /api/jobs/{job_id}/segments/search-replace`**

```bash
curl -X POST http://localhost:8000/api/jobs/abc123/segments/search-replace \
  -H "Content-Type: application/json" \
  -d '{"search": "Fehler", "replace": "Korrektur"}'
```

### Segment anheften

**`POST /api/jobs/{job_id}/segments/toggle-pin?index=<n>`**

```bash
curl -X POST "http://localhost:8000/api/jobs/abc123/segments/toggle-pin?index=5"
```

---

## Wörterbuch

### Wörterbuch anzeigen

**`GET /api/dictionary`**

```bash
curl http://localhost:8000/api/dictionary
```

### Wörterbuch aktualisieren

**`PUT /api/dictionary`**

```bash
curl -X PUT http://localhost:8000/api/dictionary \
  -H "Content-Type: application/json" \
  -d '{"entries": {"falsch": "richtig", "wort1": "wort2"}}'
```

### Wörterbuch auf Job anwenden

**`POST /api/jobs/{job_id}/apply-dictionary`**

```bash
curl -X POST http://localhost:8000/api/jobs/abc123/apply-dictionary
```

---

## Speaker-Zuweisung

### Speaker eines Jobs anzeigen

**`GET /api/jobs/{job_id}/speakers`**

```bash
curl http://localhost:8000/api/jobs/abc123/speakers
```

### Speaker zuweisen

**`POST /api/jobs/{job_id}/speakers/assign?indices=0&indices=1&speaker=<name>`**

```bash
curl -X POST "http://localhost:8000/api/jobs/abc123/speakers/assign?indices=0&indices=1&indices=2&speaker=Sänger1"
```

---

## Lücken & Überlappungen

### Erkennen

**`GET /api/jobs/{job_id}/gaps-overlaps`**

```bash
# Mit Defaults
curl http://localhost:8000/api/jobs/abc123/gaps-overlaps

# Mit Schwellenwerten
curl "http://localhost:8000/api/jobs/abc123/gaps-overlaps?min_gap_ms=200&min_overlap_ms=50"
```

### Lücken automatisch beheben

**`POST /api/jobs/{job_id}/fix-gaps`**

```bash
# Default-Strategie: extend
curl -X POST http://localhost:8000/api/jobs/abc123/fix-gaps

# Andere Strategie
curl -X POST "http://localhost:8000/api/jobs/abc123/fix-gaps?strategy=extend"
```

---

## Export & Refine

### Refine (Nachbearbeitung)

**`POST /api/refine?filename=<dateiname>`**

```bash
curl -X POST "http://localhost:8000/api/refine?filename=meinsong.mp3" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Export

**`POST /api/export?filename=<dateiname>`**

```bash
curl -X POST "http://localhost:8000/api/export?filename=meinsong.mp3" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### ASS neu generieren

**`POST /api/jobs/{job_id}/regenerate-ass`**

```bash
curl -X POST http://localhost:8000/api/jobs/abc123/regenerate-ass
```

---

## Übersetzung

**`POST /api/jobs/{job_id}/translate`**

```bash
curl -X POST http://localhost:8000/api/jobs/abc123/translate \
  -H "Content-Type: application/json" \
  -d '{"target_language": "en"}'
```

---

## Undo / Redo

```bash
# Letzte Aktion rückgängig machen
curl -X POST http://localhost:8000/api/jobs/abc123/undo

# Rückgängig gemachte Aktion wiederherstellen
curl -X POST http://localhost:8000/api/jobs/abc123/redo
```

---

## Sonstiges

### Presets auflisten

**`GET /api/presets`**

```bash
curl http://localhost:8000/api/presets
```

### Hochgeladene Dateien auflisten

**`GET /api/files`**

```bash
curl http://localhost:8000/api/files
```

### Datei löschen

**`DELETE /api/files/{filename}`**

```bash
curl -X DELETE http://localhost:8000/api/files/meinsong.mp3
```

### Audio-Datei analysieren (Probe)

**`GET /api/files/{filename}/probe`**

```bash
curl http://localhost:8000/api/files/meinsong.mp3/probe
```

### Job-Statistiken

**`GET /api/jobs/{job_id}/stats`**

```bash
curl http://localhost:8000/api/jobs/abc123/stats
```

### Waveform-Daten

**`GET /api/jobs/{job_id}/waveform`**

```bash
curl http://localhost:8000/api/jobs/abc123/waveform
```

### Report

**`GET /api/jobs/{job_id}/report`**

```bash
curl http://localhost:8000/api/jobs/abc123/report
```

### Projekt exportieren / importieren

```bash
# Projekt exportieren
curl http://localhost:8000/api/jobs/abc123/project-export -o projekt.json

# Projekt importieren
curl -X POST http://localhost:8000/api/jobs/abc123/project-import \
  -H "Content-Type: application/json" \
  -d @projekt.json
```

### Server-Events (SSE)

**`GET /api/events`** – Server-Sent Events für Live-Updates.

```bash
curl -N http://localhost:8000/api/events
```

### Health-Check

**`GET /api/health`**

```bash
curl http://localhost:8000/api/health
```

---

## Parameterreferenz

### Backends

| Wert             | Beschreibung                          |
|------------------|---------------------------------------|
| `voxtral`        | Voxtral (Default)                     |
| `openai_whisper` | OpenAI Whisper API                    |
| `local_whisper`  | Lokales Whisper                       |
| `whisperx`       | WhisperX (mit Alignment)              |

### Sprachen

| Wert   | Sprache      |
|--------|--------------|
| `auto` | Automatisch  |
| `de`   | Deutsch      |
| `en`   | Englisch     |
| `fr`   | Französisch  |
| `es`   | Spanisch     |
| `it`   | Italienisch  |
| `pt`   | Portugiesisch|
| `ja`   | Japanisch    |
| `ko`   | Koreanisch   |
| `zh`   | Chinesisch   |

### Karaoke-Modi

| Wert | Beschreibung       |
|------|--------------------|
| `k`  | Einfaches Karaoke  |
| `kf` | Karaoke Fill       |
| `ko` | Karaoke Outline    |

### Presets

| Wert                  | Beschreibung              |
|-----------------------|---------------------------|
| `classic`             | Klassisch (Default)       |
| `neon`                | Neon-Stil                 |
| `high_contrast`       | Hoher Kontrast            |
| `landscape_1080p`     | Querformat 1080p          |
| `portrait_1080x1920`  | Hochformat 1080×1920      |
| `mobile_safe`         | Mobilgeräte-optimiert     |

### Transkriptions-Parameter (JSON-Body)

| Parameter              | Typ     | Default      | Beschreibung                            |
|------------------------|---------|--------------|-----------------------------------------|
| `backend`              | string  | `voxtral`    | Transkriptions-Backend                  |
| `language`             | string  | `auto`       | Sprache                                 |
| `vad`                  | boolean | `true`       | Voice Activity Detection                |
| `vad_aggressiveness`   | integer | `2`          | VAD-Aggressivität (0–3)                 |
| `normalize`            | boolean | `true`       | Audio normalisieren                     |
| `target_lufs`          | number  | `-16.0`      | Ziel-Lautstärke in LUFS                 |
| `vocal_isolation`      | boolean | `false`      | Gesang isolieren                        |
| `vocal_device`         | string  | `cpu`        | Gerät für Vocal-Isolation               |
| `word_timestamps`      | string  | `auto`       | Wort-Zeitstempel                        |
| `generate_ass`         | boolean | `true`       | ASS-Datei generieren                    |
| `generate_vtt`         | boolean | `false`      | VTT-Datei generieren                    |
| `generate_lrc`         | boolean | `false`      | LRC-Datei generieren                    |
| `generate_txt`         | boolean | `false`      | TXT-Datei generieren                    |
| `karaoke_mode`         | string  | `kf`         | Karaoke-Modus (`k`, `kf`, `ko`)        |
| `preset`               | string  | `classic`    | Visuelles Preset                        |
| `highlight_color`      | string  | `&H0000FFFF` | Hervorhebungsfarbe (ASS-Format)         |
| `safe_area`            | string  | `""`         | Sicherer Bereich                        |
| `snap_to_beat`         | boolean | `false`      | An Beat ausrichten                      |
| `bpm`                  | string  | `null`       | BPM (optional)                          |
| `cps`                  | number  | `18.0`       | Zeichen pro Sekunde                     |
| `min_duration`         | number  | `1.0`        | Minimale Segmentdauer (Sek.)            |
| `max_duration`         | number  | `6.0`        | Maximale Segmentdauer (Sek.)            |
| `max_chars_per_line`   | integer | `42`         | Max. Zeichen pro Zeile                  |
| `max_lines`            | integer | `2`          | Max. Zeilen pro Segment                 |
| `generate_preview`     | boolean | `false`      | Preview-Video generieren                |
| `preview_duration`     | string  | `15s`        | Preview-Dauer                           |
| `preview_start`        | string  | `0s`         | Preview-Startzeit                       |
| `preview_resolution`   | string  | `1920x1080`  | Preview-Auflösung                       |
| `whisperx_model_size`  | string  | `large-v3`   | WhisperX-Modellgröße                    |
| `whisperx_compute_type`| string  | `float16`    | WhisperX Compute-Typ                    |
| `whisperx_batch_size`  | integer | `16`         | WhisperX Batch-Größe                    |

### Job-Status-Werte

`pending` → `queued` → `preprocessing` → `transcribing` → `refining` → `exporting` → `rendering_preview` → `completed` / `failed`
