# Karaoke Sub Tool — Vollständige Bestandsaufnahme

**Projektname:** karaoke-sub-tool  
**Version:** 3.2.0  
**Python:** ≥ 3.10  
**Stand:** 2026-02-18  
**Architektur:** FastAPI-Server + CLI (Typer) + WebUI (SPA)  
**Datenbank:** SQLite (Library + AI-Chat-History)  

---

## Inhaltsverzeichnis

1. [Projektübersicht](#1-projektübersicht)
2. [Einstiegspunkte](#2-einstiegspunkte)
3. [API-Schicht](#3-api-schicht)
4. [Transkriptions-Backends](#4-transkriptions-backends)
5. [Preprocessing-Pipeline](#5-preprocessing-pipeline)
6. [Refinement-Pipeline](#6-refinement-pipeline)
7. [Export-Formate](#7-export-formate)
8. [AI-Chat-System](#8-ai-chat-system)
9. [Datenbank / Library](#9-datenbank--library)
10. [Video-Editor](#10-video-editor)
11. [Lyrics-System](#11-lyrics-system)
12. [Utilities](#12-utilities)
13. [Datenfluss-Übersicht](#13-datenfluss-übersicht)

---

## 1. Projektübersicht

Das Karaoke Sub Tool ist ein professioneller Untertitel-Generator für Audio-/Videodateien mit Fokus auf Karaoke-Lyrics. Es bietet:

- **4 Transkriptions-Backends**: Voxtral (Mistral), OpenAI Whisper, Local Whisper (faster-whisper), WhisperX
- **Preprocessing**: VAD, Normalisierung, Vocal Isolation (Demucs)
- **Refinement**: CPS-Optimierung, BPM-Snap, Lyrics-Alignment, Text-Cleanup
- **6 Export-Formate**: SRT, ASS (Karaoke), VTT, LRC, TXT, standalone HTML-Karaoke
- **AI-Chat**: Segment-bewusstes KI-Assistenzsystem (PydanticAI)
- **Video-Editor**: Timeline-basierter Editor mit Multi-Track-Rendering
- **Library**: SQLite-basierte Transkriptions-Verwaltung

---

## 2. Einstiegspunkte

### `main.py` — FastAPI-Server

| Funktion | Beschreibung | Datenfluss |
|----------|-------------|-----------|
| `lifespan(app)` | Async-Context-Manager: Startet Dependency-Checks, AI-Prüfung, DB-Init; gibt beim Shutdown DB frei | Liest `.env`, initialisiert DB, prüft Backends |
| `serve_ui()` | GET `/` → `index.html` | Statische Datei |
| `serve_editor()` | GET `/editor` → `editor.html` | Statische Datei |
| `main()` | CLI-Einstieg: Parst Args (host, port, reload, workers), startet Uvicorn | Startet Server |

**Router-Registrierung:**
- `src.api.routes` → `/api/*` (Transkription, Jobs, Segments)
- `src.ai.routes` → `/api/ai/*` (AI-Chat)
- `src.db.routes` → `/api/library/*`, `/api/render-video` (Library, Video)
- `src.video.editor_routes` → `/api/editor/*` (Video-Editor)

**Statische Mounts:**
- `/data/output` → Ausgabedateien
- `/data/uploads` → Hochgeladene Dateien
- `/data/editor` → Editor-Assets, -Projekte, -Renders

---

### `src/cli.py` — Typer CLI

| Kommando / Funktion | Parameters | Beschreibung | Datenfluss |
|---------------------|-----------|-------------|-----------|
| `_get_backend(name, model, diarize)` | `name: str` | Factory-Funktion: Erzeugt das passende Transkriptions-Backend | Gibt `TranscriptionBackend` zurück |
| `_resolve_inputs(input_path, recursive)` | `input_path: Path` | Findet Audio-Dateien in Datei/Verzeichnis | Nutzt `ffmpeg_io.find_audio_files` |
| `_preprocess_audio(audio_path, cfg, tmp_dir)` | Config-basiert | Full-Preprocessing: Vocal-Isolation → WAV → Normalize → VAD | Schreibt temp WAV; gibt `(processed_audio, time_mapping, steps)` zurück |
| `_process_single_file(audio_path, output_dir, cfg, ...)` | Viele Flags | **Haupt-Pipeline**: Cache → Preprocess → Transkription → Cleanup → Alignment → Segmentierung → BPM-Snap → Review → Confidence → Export | Liest Audio, schreibt SRT/ASS/Report, speichert Cache |
| `transcribe` | CLI-Optionen | Hauptkommando: Batch-Transkription mit voller Pipeline | Iteriert Dateien → `_process_single_file` |
| `refine` | CLI-Optionen | Nachbearbeitung bestehender SRT-Dateien (CPS, Zeilenumbrüche, BPM) | Liest/schreibt SRT |
| `export` / `srt2ass` | CLI-Optionen | SRT→ASS-Konvertierung mit Karaoke-Styling | Liest SRT, schreibt ASS |
| `preview` | CLI-Optionen | Rendert kurzen Video-Preview aus ASS | Liest ASS+Audio, schreibt MP4 |
| `watch` | CLI-Optionen | Überwacht Verzeichnis auf neue Audiodateien, auto-processing | Watchdog → `_process_single_file` |
| `menu` | — | Interaktiver Setup-Wizard mit Rich-Prompts | Ruft `transcribe` über CliRunner auf |
| `init_config` | — | Erstellt `config.yaml` mit Defaults | Schreibt `config.yaml` |

---

## 3. API-Schicht

### `src/api/models.py` — Pydantic-Schemas (352 Zeilen)

| Modell | Typ | Beschreibung |
|--------|-----|-------------|
| `BackendEnum` | Enum | `voxtral`, `openai_whisper`, `local_whisper`, `whisperx` |
| `LanguageEnum` | Enum | `auto`, `de`, `en`, `fr`, `es`, `it`, `pt`, `ja`, `ko`, `zh` |
| `KaraokeModeEnum` | Enum | `k` (Fill), `kf` (Fade), `ko` (Outline Wipe) |
| `PresetEnum` | Enum | 6 ASS-Theme-Presets |
| `ExportFormatEnum` | Enum | `srt`, `ass`, `vtt`, `lrc`, `txt` |
| `LyricsTemplateModeEnum` | Enum | `source_of_truth`, `layout_only_reflow`, `hybrid_mark_differences` |
| `JobStatus` | Enum | 9 Zustände: `pending` → `completed` / `failed` |
| `TranscribeRequest` | BaseModel | 35+ Felder: Backend, Preprocess, Export, Lyrics, WhisperX-Config |
| `RefineRequest` | BaseModel | CPS, Dauer, Zeichen, BPM-Optionen |
| `ExportRequest` | BaseModel | Karaoke-Mode, Preset, Highlight-Color, Formate |
| `SegmentUpdate/Split/Merge/Reorder` | BaseModel | CRUD-Operationen auf Segmenten |
| `TimeShift` | BaseModel | Zeitverschiebung für Segment-Bereiche |
| `SearchReplace` | BaseModel | Suchen/Ersetzen mit Regex-Support |
| `JobInfo` | BaseModel | Job-Status mit Progress, Stage, Result |
| `JobResult` | BaseModel | Ergebnis-Dateien, Segment-Count, Duration |
| `JobStats` | BaseModel | Statistiken: CPS-Verteilung, Gaps, Overlaps, BPM |
| `AudioProbeInfo` | BaseModel | Datei-Metadaten: Duration, Codec, Sample-Rate |

---

### `src/api/routes.py` — API-Endpunkte (1172 Zeilen)

| Endpunkt | Methode | Funktion | Beschreibung | Datenfluss |
|----------|---------|----------|-------------|-----------|
| `/api/health` | GET | `health()` | System-Status mit ffmpeg + Backend-Verfügbarkeit | Ruft `deps_check` |
| `/api/presets` | GET | `list_presets()` | Verfügbare ASS-Theme-Presets | Liest `themes.PRESETS` |
| `/api/events` | GET | `sse_events()` | Server-Sent Events (Echtzeit-Job-Updates) | SSE-Stream mit Heartbeat |
| `/api/upload` | POST | `upload_file()` | Datei-Upload (Audio/SRT/VTT/LRC/TXT) | Schreibt in `data/uploads/`, registriert in Media-DB |
| `/api/files` | GET | `list_uploaded_files()` | Liste aller uploads | Liest Verzeichnis |
| `/api/files/{fn}` | DELETE | `delete_file()` | Datei löschen | Löscht Datei |
| `/api/files/{fn}/probe` | GET | `probe_audio_file()` | Audio-Metadaten | Ruft ffprobe |
| `/api/transcribe` | POST | `start_transcription()` | Startet Transkriptions-Job | Erstellt Job → Background-Task |
| `/api/transcribe/batch` | POST | `batch_transcribe()` | Batch-Transkription mehrerer Dateien | Erstellt mehrere Jobs |
| `/api/transcribe/upload` | POST | `transcribe_with_upload()` | Upload + sofortige Transkription | Upload → Job |
| `/api/refine` | POST | `start_refine()` | SRT-Nachbearbeitung als Job | Background-Task |
| `/api/export` | POST | `start_export()` | Multi-Format-Export als Job | Background-Task |
| `/api/jobs` | GET | `list_jobs()` | Alle Jobs (nach Erstelldatum sortiert) | In-Memory `_jobs` Dict |
| `/api/jobs/{id}` | GET/DELETE | `get_job()` / `delete_job()` | Job-Details / Löschen | In-Memory + Dateisystem |
| `/api/jobs/{id}/download/{fn}` | GET | `download_result()` | Einzeldatei-Download | FileResponse |
| `/api/jobs/{id}/download-zip` | GET | `download_zip()` | Alle Outputs als ZIP | ZIP-Stream |
| `/api/jobs/{id}/content/{fn}` | GET | `get_file_content()` | Dateiinhalt als Text | Liest Datei |
| `/api/jobs/{id}/segments` | GET/PUT | `get_segments()` / `update_segment()` | Segment CRUD | Liest/schreibt `segments.json` |
| `/api/jobs/{id}/segments/split` | POST | `split_segment()` | Segment teilen | Undo-Push → `segments.json` |
| `/api/jobs/{id}/segments/merge` | POST | `merge_segments()` | Segmente zusammenführen | Undo-Push → `segments.json` |
| `/api/jobs/{id}/segments/reorder` | POST | `reorder_segment()` | Segment verschieben | Undo-Push → `segments.json` |
| `/api/jobs/{id}/segments/time-shift` | POST | `time_shift_segments()` | Zeitverschiebung (inkl. Wörter) | Undo-Push → `segments.json` |
| `/api/jobs/{id}/segments/search-replace` | POST | `search_replace_segments()` | Suchen/Ersetzen (Regex möglich) | Undo-Push → `segments.json` |
| `/api/dictionary` | GET/PUT | `get_dictionary()` / `update_dictionary()` | Custom-Wörterbuch | Liest/schreibt `custom_words.txt` |
| `/api/jobs/{id}/apply-dictionary` | POST | `apply_dictionary()` | Wörterbuch auf Segmente anwenden | Undo-Push → `segments.json` |
| `/api/jobs/{id}/gaps-overlaps` | GET | `detect_gaps_overlaps()` | Gap/Overlap-Erkennung | Analysiert Timestamps |
| `/api/jobs/{id}/fix-gaps` | POST | `fix_gaps()` | Auto-Fix: extend/shrink/split | Undo-Push → `segments.json` |
| `/api/jobs/{id}/speakers` | GET | `get_speakers()` | Liste aller Speaker-Labels | Liest aus Segmenten |
| `/api/jobs/{id}/speakers/assign` | POST | `assign_speaker()` | Speaker-Labels setzen | Undo-Push → `segments.json` |
| `/api/jobs/{id}/segments/toggle-pin` | POST | `toggle_pin()` | Segment pinnen/unpinnen | Schreibt `segments.json` |
| `/api/jobs/{id}/translate` | POST | `translate_segments()` | Übersetzung (Placeholder) | Schreibt `segments_<lang>.json` |
| `/api/jobs/{id}/project-export` | GET | `export_project()` | Projekt als JSON exportieren | Liest Job + Segmente + Dictionary |
| `/api/jobs/{id}/project-import` | POST | `import_project()` | Projekt aus JSON importieren | Undo-Push → `segments.json` |
| `/api/jobs/{id}/undo` | POST | `undo_action()` | Undo | Stellt `segments.json` wieder her |
| `/api/jobs/{id}/redo` | POST | `redo_action()` | Redo | Stellt `segments.json` wieder her |
| `/api/jobs/{id}/regenerate-ass` | POST | `regenerate_ass()` | ASS/VTT/LRC/TXT neu generieren | Liest Segmente → Exportiert |
| `/api/jobs/{id}/stats` | GET | `get_job_stats()` | Umfangreiche Statistiken (CPS, Gaps, Confidence) | Berechnet aus `segments.json` |
| `/api/jobs/{id}/waveform` | GET | `get_waveform()` | Waveform-Daten (Peaks) | Liest `waveform.json` |
| `/api/jobs/{id}/report` | GET | `get_report()` | Konfidenz-Report | Liest `*.report.json` |
| `/api/jobs/{id}/rhyme` | GET | `get_rhyme_scheme()` | Reimschema-Analyse | Ruft `rhyme.detect_rhyme_scheme` |
| `/api/jobs/{id}/auto-fix-cps` | POST | `auto_fix_cps_route()` | CPS-Limit Auto-Fix | Undo-Push → Split/Trim |
| `/api/jobs/{id}/karaoke-html` | POST | `export_karaoke_html_route()` | Standalone HTML-Karaoke exportieren | Schreibt HTML |
| `/api/export-presets` | GET | `get_export_presets()` | Export-Presets (YouTube, TikTok, Spotify, Karaoke, Translation) | Statisch |
| `/api/jobs/{id}/export-preset/{name}` | POST | `apply_export_preset()` | Preset anwenden + Multi-Format-Export | CPS-Fix → Export |
| `/api/jobs/{id}/fill-gaps` | POST | `fill_gaps_route()` | Lücken mit `♪` füllen | Undo-Push → `segments.json` |
| `/api/jobs/{id}/redistribute-timing` | POST | `redistribute_timing_route()` | Timing gleichmäßig verteilen | Undo-Push → `segments.json` |
| `/api/jobs/{id}/text-stats` | GET | `get_text_stats()` | Textstatistiken (Vokabular, Flow-Score) | Analyse |
| `/api/jobs/{id}/segments/remove-short` | POST | `remove_short_segments()` | Kurze/leere Segmente entfernen | Undo-Push → Filter |
| `/api/jobs/{id}/segments/normalize-text` | POST | `normalize_text_route()` | Text normalisieren (Case, Punctuation) | Undo-Push → `segments.json` |
| `/api/jobs/{id}/structure` | GET | `get_song_structure()` | Songstruktur erkennen (Verse/Chorus/Bridge) | Analyse |
| `/api/jobs/{id}/export-markers/{fmt}` | POST | `export_markers()` | Video-Editor-Marker (Resolve/Premiere/YouTube/ffmpeg/JSON) | Schreibt Marker-Dateien |
| `/api/jobs/{id}/paste-lyrics` | POST | `paste_lyrics_align()` | Lyrics einfügen + auf Segmente mappen | Undo-Push → `segments.json` |
| `/api/jobs/{id}/duplicates` | GET | `find_duplicates()` | Textwiederholungen finden (Chorus-Erkennung) | SequenceMatcher-Analyse |
| `/api/jobs/{id}/snapshot` | POST | `save_snapshot()` | Segment-Zustand speichern | Kopiert nach `snapshots/` |
| `/api/jobs/{id}/snapshots` | GET | `list_snapshots()` | Gespeicherte Snapshots auflisten | Liest `snapshots/` |
| `/api/jobs/{id}/snapshot/restore/{name}` | POST | `restore_snapshot()` | Snapshot wiederherstellen | Undo-Push → Kopiert zurück |

---

### `src/api/tasks.py` — Job-Manager (701 Zeilen)

| Funktion | Parameter | Beschreibung | Datenfluss |
|----------|-----------|-------------|-----------|
| `create_job(filename)` | `filename: str` | Erstellt Job mit UUID-12-Hex-ID, Status `pending` | In-Memory `_jobs` + SSE-Event |
| `update_job(job_id, **kwargs)` | Beliebige Felder | Aktualisiert Job-Status + SSE-Broadcast | In-Memory + SSE |
| `subscribe_sse()` / `unsubscribe_sse(q)` | — | SSE-Subscriber-Management (asyncio.Queue) | Thread-safe via `call_soon_threadsafe` |
| `_emit_sse(event)` | `event: dict` | Thread-sicheres SSE-Event an alle Subscriber | Fügt Timestamp hinzu |
| `push_undo(job_id)` | `job_id: str` | Speichert `segments.json` auf Undo-Stack (max 50) | Liest Datei → Deque |
| `undo(job_id)` / `redo(job_id)` | `job_id: str` | Undo/Redo mit Stack-Tausch | Liest/schreibt `segments.json` |
| `_safe_stem(name, fallback)` | `name: str` | Sanitized Dateiname (keine Path-Traversal, Sonderzeichen, max 200 Chars) | Reine Transformation |
| `get_artifact_dir(job_output, stem)` | Paths | Erzeugt Unterverzeichnis für Job-Artefakte | Erstellt Verzeichnis |
| `run_transcribe_job(job_id, audio_path, req)` | Async | Startet `_transcribe_sync` im ThreadPool | Delegation |
| `_transcribe_sync(job_id, audio_path, req)` | Sync | **Haupt-Job-Pipeline**: Audio kopieren → Preprocess → Transkription → Lyrics-Align → Refinement → BPM-Snap → AI-Korrektur → Export (SRT/ASS/VTT/LRC/TXT) → Confidence-Report → Preview → Waveform → Library-Save | Liest Audio, schreibt alle Outputs |
| `run_refine_job(job_id, srt_path, req)` | Async | SRT lesen → Clean → Timestamps → Refine → Schreiben | Liest/schreibt SRT + `segments.json` |
| `run_export_job(job_id, srt_path, req)` | Async | SRT lesen → Multi-Format-Export | Liest SRT, schreibt diverse Formate |
| `_ai_correct_lyrics(segments, language, job_id)` | Sync | Mistral AI Lyrics-Korrektur (Reimschema-bewusst) | API-Call → Segmente modifizieren |
| `_generate_waveform_data(audio_path, output_path, num_points)` | Sync | Erzeugt Waveform-Peaks via ffmpeg PCM-Decode + numpy | ffmpeg → numpy → `waveform.json` |
| `_get_backend(name, model, diarize, req)` | Factory | Backend-Instanziierung (Voxtral/OpenAI/Local/WhisperX) | Gibt `TranscriptionBackend` zurück |

---

## 4. Transkriptions-Backends

### `src/transcription/base.py` — Abstraktion

| Klasse/Methode | Beschreibung |
|----------------|-------------|
| `WordInfo(start, end, word, confidence)` | Dataclass: Ein Wort mit Zeitstempel + Konfidenz |
| `TranscriptSegment(start, end, text, words, confidence, ...)` | Dataclass: Ein Untertitel-Segment mit optionalen Wort-Timestamps. Hat `to_dict()` / `from_dict()`, auch `speaker`, `pinned` Felder |
| `TranscriptResult(segments, language, backend, duration, raw_output)` | Dataclass: Vollständiges Transkriptions-Ergebnis |
| `TranscriptionBackend` (ABC) | Interface: `transcribe(audio_path, language, word_timestamps) → TranscriptResult` + `check_available() → (bool, str)` |

### `src/transcription/voxtral.py` — Mistral AI Voxtral

| Funktion | Beschreibung | Besonderheiten |
|----------|-------------|----------------|
| `VoxtralBackend.__init__(api_key, model, diarize)` | Initialisiert Mistral-Client | Default: `voxtral-mini-latest` |
| `check_available()` | Prüft `MISTRAL_API_KEY` + `mistralai` | |
| `_extract_segments(transcription)` | Extrahiert Segmente aus API-Response (generisch für Dict + SDK-Objekt) | Robustes `_safe_get` |
| `transcribe(audio_path, ...)` | Sendet Audio an Mistral API (Base64-encoded) | Gibt `TranscriptResult` zurück |

### `src/transcription/openai_whisper.py` — OpenAI Whisper API

| Funktion | Beschreibung | Besonderheiten |
|----------|-------------|----------------|
| `OpenAIWhisperBackend.__init__(api_key, model)` | `whisper-1` per Default | |
| `check_available()` | Prüft `OPENAI_API_KEY` + `openai` | |
| `transcribe(audio_path, ...)` | Sendet Audio, parsed `verbose_json` mit Wort-Timestamps | |

### `src/transcription/local_whisper.py` — Faster-Whisper (lokal)

| Funktion | Beschreibung | Besonderheiten |
|----------|-------------|----------------|
| `LocalWhisperBackend.__init__(model_size, device, compute_type)` | `large-v3`, Auto-Device | |
| `_get_model()` | Lazy-Loading, Singleton-Pattern | |
| `transcribe(audio_path, ...)` | Lokale Transkription mit VAD-Filter + Beam-Search | Kein API-Key nötig |

### `src/transcription/whisperx_backend.py` — WhisperX (Forced Alignment)

| Funktion | Beschreibung | Besonderheiten |
|----------|-------------|----------------|
| `WhisperXBackend.__init__(model_size, device, compute_type, batch_size, hf_token)` | HuggingFace-Token für Diarization | |
| `_get_model()` / `_get_align_model(language, device)` | Lazy-Loading für Transkriptions- + Alignment-Modell | |
| `transcribe(audio_path, ...)` | 3-Schritte: Transkription → Forced-Alignment (wav2vec2) → opt. Diarization | Präziseste Wort-Timestamps |

---

## 5. Preprocessing-Pipeline

### `src/preprocess/ffmpeg_io.py` — FFmpeg-Integration

| Funktion | Parameter | Beschreibung | I/O |
|----------|-----------|-------------|-----|
| `probe_audio(path)` | `Path` | Audio-Metadaten per ffprobe | Liest Datei → `dict` |
| `get_duration(path)` | `Path` | Dauer in Sekunden | `Path → float` |
| `convert_to_wav(input_path, output_path, sample_rate=16000, mono=True)` | Paths | Konvertiert zu 16kHz Mono WAV | Liest Audio, schreibt WAV |
| `apply_loudnorm(input_path, output_path, target_lufs=-16.0)` | Paths | ffmpeg loudnorm-Filter | Liest/schreibt WAV |
| `is_supported_audio(path)` | `Path` | Prüft Dateiendung | `bool` |
| `find_audio_files(directory, recursive)` | `Path, bool` | Findet Audio-Dateien | `list[Path]` |

**Konstante:** `SUPPORTED_FORMATS` = `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wma`

### `src/preprocess/normalize.py` — Normalisierung

| Funktion | Beschreibung |
|----------|-------------|
| `normalize_audio(input_path, output_path, target_lufs=-16.0)` | Wrapper um `apply_loudnorm` |

### `src/preprocess/vad.py` — Voice Activity Detection

| Funktion | Parameter | Beschreibung | I/O |
|----------|-----------|-------------|-----|
| `SpeechSegment(start_ms, end_ms)` | Dataclass | Ein Sprach-Segment in ms | — |
| `_read_wave(path)` | `Path` | Liest Mono-16bit-WAV als Rohdaten | Liest WAV → `(bytes, sample_rate, sample_width)` |
| `_frame_generator(audio, sample_rate, frame_ms=30)` | `bytes` | Zerlegt Audio in 30ms-Frames | Generator → `(frame, timestamp, duration)` |
| `detect_speech(wav_path, aggressiveness=2, min_speech_ms=300, min_silence_ms=500)` | `Path` | Spracherkennung per webrtcvad | Liest WAV → `list[SpeechSegment]` |
| `create_vad_trimmed(wav_path, segments, output_path, pad_ms=200)` | Paths + Segments | Schneidet Stille heraus | Schreibt getrimmte WAV |
| `_merge_close_segments(segments, gap_ms=400)` | `list` | Verschmilzt nahe Segmente | In-Place |
| `create_time_mapping(segments, pad_ms=200)` | `list[SpeechSegment]` | Erstellt Rücktransformations-Mapping | `list[tuple[int,int,int]]` |
| `remap_timestamps(segments, time_mapping)` | `list[dict], mapping` | **Mappt VAD-Timestamps zurück auf Original-Timeline** | `list[dict] → list[dict]` |

### `src/preprocess/vocals.py` — Vocal Isolation

| Funktion | Beschreibung | I/O |
|----------|-------------|-----|
| `isolate_vocals(input_path, output_dir, model="htdemucs", device="cpu")` | Source-Separation via Demucs | Liest Audio, schreibt `vocals.wav` → `Path|None` |

---

## 6. Refinement-Pipeline

### `src/refine/text_cleanup.py` — Text-Bereinigung

| Funktion | Beschreibung |
|----------|-------------|
| `normalize_whitespace(text)` | Mehrfach-Whitespace → einzelnes Leerzeichen |
| `normalize_quotes(text)` | Typographische → ASCII-Quotes |
| `normalize_punctuation(text)` | `...`→`…`, `--`→`—`, Leerzeichen vor Satzzeichen entfernen |
| `capitalize_sentences(text)` | Großbuchstabe am Satzanfang |
| `apply_dictionary(text, dictionary)` | Wörter ersetzen per `custom_words.txt` (case-insensitive, Word-Boundary) |
| `load_dictionary(path)` | Lädt `falsch=richtig`-Paare aus Datei → `dict[str,str]` |
| `clean_segment_text(text, dictionary, capitalize)` | Komplett-Pipeline für einen Text |
| `clean_all_segments(segments, dictionary, capitalize)` | Wendet Cleanup auf alle Segmente + Wörter an |

### `src/refine/alignment.py` — Wort-Timestamp-Alignment

| Funktion | Beschreibung |
|----------|-------------|
| `syllable_count_heuristic(word)` | Schätzt Silbenanzahl für Gewichtung |
| `approximate_word_timestamps(segment)` | Verteilt Wort-Timestamps proportional nach Silbengewicht |
| `ensure_word_timestamps(segments, mode="auto")` | Stellt Wort-Timestamps sicher: `auto` = nur fehlende approximieren, `force` = alle |

### `src/refine/segmentation.py` — Segmentierung

| Funktion | Beschreibung |
|----------|-------------|
| `compute_cps(segment)` | Characters-per-Second berechnen |
| `should_split(segment, max_cps, max_duration, max_chars, max_lines)` | Prüft ob Split nötig |
| `find_split_point(segment, max_chars_per_line)` | Bester Splitpunkt (Interpunktion > Leerzeichen > Mitte) |
| `split_segment(segment)` | Segment teilen mit Wort-Timestamp-Zuordnung |
| `merge_short_segments(segments, min_duration, max_chars)` | Kurze Segmente mit vorherigem verschmelzen |
| `ensure_gaps(segments, min_gap_ms=80)` | Mindestabstand 80ms zwischen Segmenten |
| `add_line_breaks(segment, max_chars_per_line, max_lines)` | Zeilenumbrüche einfügen (max 2 Zeilen à 42 Zeichen) |
| `refine_segments(segments, cps, min_duration, max_duration, ...)` | **Haupt-Pipeline**: Split → Merge → Gaps → Line-Breaks |

### `src/refine/beatgrid.py` — BPM-Snap

| Funktion | Beschreibung |
|----------|-------------|
| `detect_bpm(audio_path)` | BPM-Erkennung: Essentia (bevorzugt) → librosa (Fallback) |
| `_detect_bpm_essentia(audio_path)` | Essentia RhythmExtractor2013 |
| `_detect_bpm_librosa(audio_path)` | librosa Beat-Tracking |
| `generate_beat_grid(bpm, duration, time_signature, beat_offset_ms)` | Liste aller Beat-Zeitstempel |
| `snap_to_nearest_beat(time_sec, beats, tolerance_ms, strength)` | Snap mit konfigurierbarer Blend-Stärke |
| `snap_segments_to_grid(segments, bpm, duration, ...)` | Alle Segment+Wort-Grenzen am BPM-Grid ausrichten |

### `src/refine/confidence.py` — Qualitäts-Analyse

| Funktion | Beschreibung | I/O |
|----------|-------------|-----|
| `SegmentReport(index, start, end, text, avg_conf, min_conf, needs_review, ...)` | Dataclass pro Segment | |
| `FileReport(filename, backend, language, total_segments, ...)` | Dataclass pro Datei (inkl. Processing-Flags) | |
| `analyze_confidence(segments, threshold=0.6)` | Analysiert Konfidenz, markiert Review-Segmente | `list[TranscriptSegment] → list[SegmentReport]` |
| `generate_report(file_report, fmt)` | Erzeugt JSON/CSV-String | `FileReport → str` |
| `save_report(file_report, output_path, fmt)` | Schreibt `.report.json/.csv` | Schreibt Datei → `Path` |

### `src/refine/lyrics_align.py` — Lyrics-Alignment

| Funktion | Beschreibung |
|----------|-------------|
| `parse_lyrics_file(lyrics_path)` | Parsed Lyrics-Text, entfernt Section-Marker |
| `_normalize_word(w)` | Normalisiert für Fuzzy-Matching |
| `_tokenize(text)` | Text → normalisierte Token-Liste |
| `align_lyrics_to_segments(segments, lyrics_lines, similarity_threshold=0.4)` | **Greedy-Matching**: Mappt Lyrics auf Transkriptions-Wörter, erzeugt neue Segmente mit Lyrics-Text + ASR-Timing |
| `_find_best_match_start(all_words, start_from, target_tokens, threshold)` | Bester Startpunkt für Line-Matching |
| `_build_line_words(lyrics_line, consumed_words)` | Timing von ASR-Wörtern auf Lyrics-Wörter übertragen |

### `src/refine/rhyme.py` — Reimschema-Erkennung

| Funktion | Beschreibung |
|----------|-------------|
| `_normalize_phonetic(word)` | Grobe phonetische Normalisierung (DE/EN) |
| `_get_rhyme_tail(word, min_chars)` | Reimenden ab letztem betontem Vokal |
| `_rhyme_score(word_a, word_b)` | Reim-Bewertung 0.0–1.0 |
| `RhymePair(line_a, line_b, word_a, word_b, score, rhyme_type)` | Erkanntes Reimpaar |
| `RhymeScheme(total_lines, scheme_labels, scheme_pattern, rhyme_pairs, rhyme_density, ...)` | Vollständige Reimanalyse |
| `detect_rhyme_scheme(lines, threshold=0.6, window=8)` | Erkennt End-/Innen-/Mehrsilbenreime, optimiert für Rap |

### `src/refine/cps_fixer.py` — CPS Auto-Fix

| Funktion | Beschreibung |
|----------|-------------|
| `CPSFixResult(original_count, fixed_count, segments_split, segments_trimmed, ...)` | Statistik |
| `_find_split_point(text)` | Optimaler Trennpunkt (Komma > Konjunktion > Wortgrenze) |
| `_split_segment(seg, max_cps)` | Rekursives Splitting bis CPS eingehalten |
| `auto_fix_cps(segments, max_cps=22.0, min_duration=0.5)` | Batch-Fix aller CPS-Überschreitungen |

### `src/refine/gap_filler.py` — Lücken-Management

| Funktion | Beschreibung |
|----------|-------------|
| `GapFillResult(original_count, final_count, gaps_filled, ...)` | Ergebnis-Statistik |
| `fill_gaps(segments, min_gap=2.0, merge_threshold=0.3, fill_text="♪")` | Große Lücken mit `♪` füllen, Mikro-Lücken mergen |
| `redistribute_timing(segments, total_duration, gap=0.05)` | Timing proportional nach Textlänge neu verteilen |

### `src/refine/text_stats.py` — Textstatistiken

| Funktion | Beschreibung |
|----------|-------------|
| `TextStats(total_words, unique_words, type_token_ratio, hapax_legomena, top_words, top_bigrams, flow_score, ...)` | Vollständige Analyse |
| `analyze_text_stats(lines, top_n=20, stop_words=None)` | Vokabular-Diversität, Wortfrequenz, Silbenverteilung, Flow-Score, Lesezeit |

### `src/refine/structure.py` — Songstruktur-Erkennung

| Funktion | Beschreibung |
|----------|-------------|
| `SongSection(section_type, label, start_line, end_line, start_time, end_time, ...)` | Ein erkannter Abschnitt |
| `SongStructure(sections, total_lines, total_duration, has_chorus, chorus_count, verse_count, structure_pattern)` | Vollständige Struktur |
| `_block_similarity(lines_a, lines_b)` | Textblock-Vergleich per SequenceMatcher |
| `detect_song_structure(segments, min_section_lines=2, chorus_threshold=0.6, gap_threshold=3.0)` | Gap-Analyse + Textwiederholung + Positionsheuristiken → Pattern wie `I-V1-C-V2-C-B-C-O` |

### `src/refine/review_tui.py` — Terminal-Review

| Funktion | Beschreibung |
|----------|-------------|
| `review_segments(segments, beats)` | Interaktive TUI: Navigieren, Editieren, Splitten, Mergen, Nudgen |
| `save_patches(patches, output_path)` | Änderungsprotokoll als JSON speichern |

---

## 7. Export-Formate

### `src/export/srt_writer.py`

| Funktion | Beschreibung |
|----------|-------------|
| `format_srt_time(seconds)` | `float → "HH:MM:SS,mmm"` |
| `write_srt(segments, output_path)` | Segmente → `.srt`-Datei |
| `parse_srt_time(time_str)` | `"HH:MM:SS,mmm" → float` |
| `read_srt(path)` | `.srt`-Datei → `list[TranscriptSegment]` |

### `src/export/ass_writer.py`

| Funktion | Beschreibung |
|----------|-------------|
| `build_script_info(theme, title)` | Erzeugt `[Script Info]`-Block |
| `build_styles_section(theme, include_uncertain)` | Erzeugt `[V4+ Styles]`-Block |
| `build_events_section(events)` | Erzeugt `[Events]`-Block |
| `write_ass(segments, output_path, preset, karaoke_mode, highlight_color, ...)` | Vollständige ASS mit Karaoke + Theme + optionalem Template-Merge |

### `src/export/ass_template.py`

| Funktion | Beschreibung |
|----------|-------------|
| `load_template(path)` | Lädt ASS-Template → Sektionen-Dict |
| `merge_template(template_sections, events_text, styles_text, replace_events_only)` | Merged Events/Styles in bestehendes Template |

### `src/export/vtt_writer.py`

| Funktion | Beschreibung |
|----------|-------------|
| `write_vtt(segments, output_path)` | Segmente → `.vtt`-Datei |
| `read_vtt(path)` | `.vtt`-Datei → `list[TranscriptSegment]` |

### `src/export/lrc_writer.py`

| Funktion | Beschreibung |
|----------|-------------|
| `write_lrc(segments, output_path, title, artist, album)` | Enhanced LRC mit Word-Level-Tags + Metadaten |
| `write_simple_lrc(segments, output_path)` | Einfaches LRC ohne Wort-Timestamps |

### `src/export/txt_writer.py`

| Funktion | Beschreibung |
|----------|-------------|
| `write_txt(segments, output_path, separator)` | Reiner Text ohne Timestamps |
| `write_txt_with_timestamps(segments, output_path)` | Text mit `[MM:SS]`-Zeitstempeln |

### `src/export/karaoke_html.py`

| Funktion | Beschreibung |
|----------|-------------|
| `export_karaoke_html(segments, output_path, title, audio_path, embed_audio, theme, font_size, highlight_color, ...)` | Standalone HTML-Karaoke-Player mit CSS/JS, optionalem Base64-Audio, Themes, Progress-Bar |

### `src/export/karaoke_tags.py`

| Funktion | Beschreibung |
|----------|-------------|
| `word_duration_cs(word)` | Wortdauer in Centisekunden (für ASS `\k`-Tags) |
| `generate_karaoke_line(segment, mode, highlight_color)` | ASS-Karaoke-Tags (`\k`, `\kf`, `\ko`) für ein Segment |
| `generate_karaoke_events(segments, mode, ...)` | Komplette ASS-Dialogue-Events mit Confidence-Styling |
| `format_ass_time(seconds)` | `float → "H:MM:SS.cc"` |

### `src/export/themes.py`

| Klasse/Funktion | Beschreibung |
|----------------|-------------|
| `ASSTheme(name, playresx, playresy, font, fontsize, colors, ...)` | Vollständiges ASS-Style-Preset |
| `ASSTheme.to_ass_style(style_name)` | Erzeugt ASS-Style-Zeile |
| `ASSTheme.to_uncertain_style(style_name)` | Gelber Style für niedrige Konfidenz |
| `get_theme(preset_name)` | Preset-Lookup |
| `apply_safe_area(theme, safe_area)` | Margins anpassen |
| `PRESETS` | 6 Presets: classic, neon, high_contrast, landscape_1080p, portrait_1080x1920, mobile_safe |

### `src/export/video_markers.py`

| Funktion | Beschreibung | Format |
|----------|-------------|--------|
| `export_resolve_markers(segments, output_path, fps)` | DaVinci Resolve EDL | `.edl` |
| `export_premiere_markers(segments, output_path, fps)` | Adobe Premiere CSV | `.csv` |
| `export_youtube_chapters(sections, output_path)` | YouTube-Kapitelmarker | `.chapters.txt` |
| `export_ffmpeg_chapters(sections, output_path)` | FFMPEG Metadata-Chapters | `.ffmeta` |
| `export_json_markers(segments, output_path, include_words)` | Generisches JSON | `.markers.json` |

---

## 8. AI-Chat-System

### `src/ai/chat.py` — PydanticAI Agent (325 Zeilen)

| Klasse/Funktion | Beschreibung |
|----------------|-------------|
| `ChatDeps(job_id, segments, output_dir, metadata)` | Runtime-Dependencies für Agent-Tools |
| `ChatDeps.save_segments()` | Schreibt modifizierte Segmente zurück |
| `ChatDeps.get_lyrics_text()` | Formatiert Segmente mit Index + Timing |
| `get_model_name()` | Liest `AI_MODEL` aus `.env` (Default: `openai:gpt-5.2`) |
| `is_reasoning_model(model)` | Auto-Detect für Reasoning-Modelle (o1, o3, GPT-5, Claude Opus) |
| `has_ai_key()` | Prüft Provider-spezifischen API-Key |
| `SYSTEM_PROMPT` | Deutschsprachiger KI-Audio-Engineer-Prompt |
| `COMMAND_PROMPTS` | 5 Spezial-Prompts: correct, punctuate, structure, translate, generate |
| `create_agent() → Agent[ChatDeps, str]` | Factory: Erstellt PydanticAI-Agent mit Tools |

**Agent-Tools (Read):**
| Tool | Beschreibung |
|------|-------------|
| `get_all_segments` | Alle Segmente mit Index, Zeit, Text, Confidence |
| `get_segment(index)` | Einzelnes Segment (1-basiert) inkl. Wort-Details |
| `get_low_confidence_segments(threshold)` | Segmente mit niedriger Konfidenz |
| `get_song_metadata` | Backend, Sprache, Dauer, Word-Timestamps |

**Agent-Tools (Write):**
| Tool | Beschreibung |
|------|-------------|
| `update_segment_text(index, new_text)` | Text eines Segments ändern |
| `update_multiple_segments(changes)` | Batch-Update: `"NUMMER: neuer Text"` Format |
| `set_speaker_labels(labels)` | Speaker-Labels setzen, auch Bereiche: `"1-4: Verse 1"` |
| `add_to_dictionary(entries)` | Custom Dictionary erweitern |

### `src/ai/routes.py` — Chat-API (218 Zeilen)

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/api/ai/health` | GET | AI-Konfigurationsstatus |
| `/api/ai/chat/{job_id}` | GET | Chat-History laden (NDJSON) |
| `/api/ai/chat/{job_id}` | POST | Nachricht senden, Streaming-Response |
| `/api/ai/chat/{job_id}` | DELETE | Chat-History löschen |

**Streaming:** Newline-delimited JSON mit Rollen `user`, `model`, `system` (`__SEGMENTS_UPDATED__`-Signal)

### `src/ai/database.py` — Chat-History DB (115 Zeilen)

| Klasse/Methode | Beschreibung |
|----------------|-------------|
| `Database(con, _loop, _executor)` | SQLite-Wrapper mit async via ThreadPoolExecutor |
| `Database.connect(file)` | Erstellt DB + `messages`-Tabelle |
| `add_messages(messages)` | Speichert ModelMessage-Bytes |
| `get_messages()` | Lädt vollständige Konversation als `list[ModelMessage]` |
| `clear()` | Löscht alle Nachrichten |
| `get_db(job_id, output_dir)` | Global Cache: Pro Job eine DB unter `.chat_history.sqlite` |

---

## 9. Datenbank / Library

### `src/db/library.py` — SQLite Library (439 Zeilen)

**Schema:** Zwei Tabellen: `transcriptions` (18 Spalten) + `media` (13 Spalten), indiziert auf `created_at`, `source_hash`, `deleted`, `filename`, `job_id`.

| Funktion | Beschreibung | Datenfluss |
|----------|-------------|-----------|
| `init_db(db_path)` | Schema erstellen, Connection öffnen | Schreibt `data/library.sqlite` |
| `close_db()` | Connection schließen | |
| `compute_source_hash(filename, backend, language)` | Deduplizierungs-Hash | SHA-256 |
| `save_transcription(source_filename, backend, language, ...)` | Upsert per `source_hash` | Insert/Update DB |
| `list_transcriptions(limit, offset, q)` | Paginated + Suche (Titel/Dateiname/Backend) | `→ (list[TranscriptionRecord], total)` |
| `get_transcription(rec_id)` | Einzelnen Record laden | |
| `delete_transcription(rec_id, hard)` | Soft-/Hard-Delete | |
| `update_transcription(rec_id, **kwargs)` | Felder updaten (Titel, Tags, BPM) | |
| `_classify_file(filename)` | Dateityp bestimmen → `(file_type, mime, taggable, editable)` | |
| `register_media(filename, path, size, ...)` | Media-Upload registrieren (dedupe per Filename+Path) | Insert DB |
| `get_media(media_id)` / `get_media_by_filename(filename)` | Media-Record abrufen | |
| `list_media(file_type, limit)` | Media-Liste filtern | |
| `delete_media(media_id)` | Media-Record löschen | |

### `src/db/routes.py` — Library & Video Routes (492 Zeilen)

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/api/library` | GET | Paginierte Library mit Suche |
| `/api/library/{id}` | GET | Detail mit SRT/ASS-Text |
| `/api/library/{id}` | PATCH | Titel/Tags/BPM updaten |
| `/api/library/{id}` | DELETE | Soft-/Hard-Delete |
| `/api/library/{id}/srt` | GET | SRT als Download |
| `/api/render-video` | POST | Video-Rendering starten (BG + Sub + Audio) |
| `/api/render/{job_id}/download` | GET | Gerendertes Video downloaden |

---

## 10. Video-Editor

### `src/video/editor.py` — Editor-Engine (umfangreiche Logik)

| Klasse | Beschreibung |
|--------|-------------|
| `Asset(id, filename, path, type, duration, width, height, fps, has_audio, thumbnail)` | Media-Asset |
| `Effect(type, params)` | Visueller/Audio-Effekt auf einem Clip |
| `Clip(id, asset_id, track, start, duration, in_point, out_point, volume, speed, loop, effects, z_index, sub_style, sub_position)` | Timeline-Clip |
| `Project(id, name, width, height, fps, duration, assets, clips, preset, crf, sub_*)` | Vollständiger Projektzustand mit Untertitel-Styling |

| Funktion | Beschreibung |
|----------|-------------|
| `create_project(name, width, height, fps)` | Neues leeres Projekt |
| `get_project(pid)` / `list_projects()` | Projekt-Zugriff |
| `save_project(pid)` / `load_project(path)` | JSON-Persistierung |
| `_push_undo(pid)` | Undo-Stack (max 30) |
| `undo(pid)` / `redo(pid)` | Zustandswiederherstellung |
| `add_asset(pid, filename, file_path)` | Asset hinzufügen + Probing + Thumbnail |
| `add_clip(pid, asset_id, track, start, duration)` | Clip zur Timeline (auto-positioniert wenn start=-1) |
| `remove_clip(pid, clip_id)` | Clip entfernen |
| `update_clip(pid, clip_id, **kwargs)` | Clip-Eigenschaften updaten |
| `split_clip(pid, clip_id, at_time)` | Clip an Zeitposition teilen |
| `add_effect(pid, clip_id, effect_type, params)` / `remove_effect(...)` | Effekt-Management |
| `generate_styled_ass(sub_path, project, output_path)` | ASS mit konfigurierbarer Position/Styling |
| `build_render_cmd(pid, output_path)` | ffmpeg-Filtergraph: Canvas → Overlays → Subtitles → Audio-Mix |
| `render_project(pid)` | Vollständiger Render als MP4 |
| `render_loop_video(source_path, output_path, ...)` | Schnelles Loop-Rendering |
| `get_timeline_summary(pid)` | Menschenlesbare Timeline-Zusammenfassung für AI |

### `src/video/editor_routes.py` — Editor-API

Vollständige REST-API mit 20+ Endpunkten für Projekte, Assets, Clips, Effekte, Render, Import, AI-Chat.

### `src/video/ai_tools.py` — Editor-AI

| Funktion | Beschreibung |
|----------|-------------|
| `run_editor_chat(pid, message, history)` | AI-Chat mit Editor-Tool-Ausführung (parst ` ```action`-Blöcke) |
| `_execute_action(pid, action)` | Führt Editor-Aktionen aus (add_clip, update_clip, split, etc.) |
| `_call_ai(model_name, messages)` | Multi-Provider AI-Call (OpenAI/Anthropic/Mistral/Google) |

### `src/video/render.py` — Video-Rendering

| Funktion | Beschreibung |
|----------|-------------|
| `ProbeResult(width, height, duration, fps, has_audio, codec, is_image)` | Media-Analyse-Ergebnis |
| `probe_media(path)` | ffprobe-Analyse (Bilder, Video, Audio) |
| `srt_to_ass(srt_path, output_path, position, font_size)` | SRT→ASS-Konvertierung |
| `RenderOptions(preset, position, crf, x264_preset, ...)` | Render-Konfiguration |
| `render_video(subtitle_path, background_path, output_path, audio_path, options, progress_callback)` | Vollständiges Video mit Hintergrund + Untertitel + Audio |
| `RENDER_PRESETS` | 4 Presets: youtube, mobile, draft, custom |

---

## 11. Lyrics-System

### `src/lyrics/template.py` — Lyrics-Parsing

| Klasse/Funktion | Beschreibung |
|----------------|-------------|
| `LyricsMode` Enum | `line_per_event`, `merge_by_empty_lines` |
| `TemplateMode` Enum | `source_of_truth`, `layout_only`, `hybrid` |
| `MatchMode` Enum | `strict`, `lenient` |
| `LyricsLine(index, text, is_empty, is_section, section_label, lrc_time)` | Geparste Lyrics-Zeile |
| `ParsedLyrics(lines, target_lines, sections, total_lines, source_file, format, has_timestamps)` | Parse-Ergebnis |
| `parse_lyrics(lyrics_path, preserve_empty_lines, strip_section_markers)` | `.txt`/`.lrc` → strukturierte Zeilen mit Sektionserkennung |
| `group_by_stanzas(parsed)` | In Strophen gruppieren (durch Leerzeilen getrennt) |
| `get_lrc_timings(parsed)` | `(Zeit, Text)`-Paare aus LRC |

### `src/lyrics/reports.py` — Alignment-Reports

| Klasse/Funktion | Beschreibung |
|----------------|-------------|
| `LineAlignment(line_index, lyrics_text, asr_text, match_score, timing_source, ...)` | Pro-Zeile Alignment-Ergebnis |
| `AlignmentReport(total_lines, matched_lines, avg_match_score, ...)` | Vollständiger Qualitätsbericht |
| `compute_match_score(lyrics_text, asr_text)` | SequenceMatcher-Ähnlichkeit |
| `find_diff_words(lyrics_text, asr_text)` | Unterschiedliche Wörter finden |
| `generate_alignment_report(lyrics_lines, aligned_segments, original_segments)` | Qualitätsbericht mit doppeltem Matching (Zeit + Sequenz) |
| `save_alignment_report(report, output_path)` | `.alignment_report.json` |
| `save_diff_report(report, output_path)` | `.diff_report.json` (nur Unterschiede) |

---

## 12. Utilities

### `src/utils/config.py` — Konfiguration

| Klasse | Beschreibung |
|--------|-------------|
| `AppConfig` | Haupt-Config mit Sub-Configs: Preprocess, Transcription, WhisperX, Refinement, BeatGrid, Karaoke, Theme, Preview, Cache, Confidence |
| `load_config(path)` | YAML laden (sucht `config.yaml`, `config.yml`, `karaoke.yaml`) |
| `merge_cli_overrides(cfg, overrides)` | CLI-Args via Dot-Notation überschreiben |
| `DEFAULT_CONFIG_YAML` | Kommentiertes Default-YAML |

### `src/utils/cache.py` — Pipeline-Cache

| Funktion | Beschreibung |
|----------|-------------|
| `get_file_id(path, method)` | SHA-256-Hash oder Mtime-basierte ID |
| `cache_key(input_path, stage, method)` | Cache-Schlüssel aus Datei + Pipeline-Stage |
| `load_cached(input_path, stage, method)` | JSON-Cache laden |
| `save_cache(input_path, stage, data, method)` | JSON-Cache speichern unter `.karaoke_cache/` |
| `output_exists(output_path, input_path, method)` | Prüft Done-Marker |
| `mark_done(output_path, input_path, method)` | Setzt Done-Marker |

### `src/utils/deps_check.py` — Dependency-Prüfung

| Funktion | Beschreibung |
|----------|-------------|
| `DepStatus(name, available, version, hint)` | Status einer Abhängigkeit |
| `check_ffmpeg()` / `check_ffprobe()` | ffmpeg/ffprobe verfügbar? |
| `check_demucs()` | Demucs importierbar? |
| `check_openai_key()` / `check_mistral_key()` | API-Keys vorhanden? |
| `check_webrtcvad()` / `check_whisperx()` / `check_faster_whisper()` | ML-Bibliotheken |
| `check_all(backend, vocal_isolation)` | Alle relevanten Dependencies prüfen |
| `check_all_backends()` | Quick-Check: welche Backends verfügbar? |
| `print_dep_status(deps, strict)` | Farbige Rich-Statusanzeige |

### `src/utils/logging.py` — Logging

| Funktion | Beschreibung |
|----------|-------------|
| `Verbosity` Enum | `SILENT`, `NORMAL`, `VERBOSE` |
| `setup_logging(verbosity)` | Rich-Handler konfigurieren |
| `info(msg)` / `success(msg)` / `warn(msg)` / `error(msg)` / `debug(msg)` | Farbige Log-Funktionen |
| `make_progress(**kwargs)` | Rich-Fortschrittsanzeige mit Spinner |
| `console` / `err_console` | Rich-Konsolen mit Custom-Theme |

### `src/media/tags.py` — Media-Tag-Management

| Funktion | Beschreibung |
|----------|-------------|
| `MediaTags(tags, format, editable, supported_fields, has_cover, raw)` | Container für gelesene Tags |
| `is_taggable(path)` | Prüft ob Format Tags unterstützt |
| `read_tags(path)` | Tags lesen per mutagen / ffprobe-Fallback |
| `write_tags(path, new_tags, copy_on_write)` | Tags schreiben (ID3/MP4/Vorbis) mit Copy-on-Write |

### `src/preview/render.py` — Preview-Rendering

| Funktion | Beschreibung |
|----------|-------------|
| `parse_time_str(time_str)` | `"15s"`, `"1m30s"`, `"60"` → Sekunden |
| `render_preview(ass_path, audio_path, duration, start, resolution, background, bg_image)` | Kurzer MP4-Preview mit eingebrannten ASS-Subs |

### `src/watch/watchdog.py` — File-Watcher

| Funktion | Beschreibung |
|----------|-------------|
| `DebouncedHandler` | Entprellt Dateisystem-Events (verhindert halb-geschriebene Dateien) |
| `watch_directory(input_dir, output_dir, process_callback, recursive, debounce_sec)` | Überwacht Verzeichnis auf neue Audio-Dateien, auto-processing |

---

## 13. Datenfluss-Übersicht

```
Audio-Datei
    │
    ├─► [Upload] data/uploads/
    │       │
    ├─► [Preprocess]
    │       ├── Vocal Isolation (Demucs) ──► vocals.wav
    │       ├── Convert to WAV (16kHz mono) ──► _work.wav
    │       ├── Normalize (LUFS) ──► _norm.wav
    │       └── VAD (webrtcvad) ──► _vad.wav + time_mapping
    │
    ├─► [Transkription]
    │       ├── Voxtral (Mistral API)
    │       ├── OpenAI Whisper (API)
    │       ├── Local Whisper (faster-whisper)
    │       └── WhisperX (Forced Alignment)
    │       └──► TranscriptResult (segments + words)
    │
    ├─► [VAD Remap] time_mapping → Original-Timestamps
    │
    ├─► [Cache] .karaoke_cache/ (JSON)
    │
    ├─► [Refinement]
    │       ├── Text Cleanup (Whitespace, Quotes, Dictionary)
    │       ├── Word-Timestamp Alignment (Silbengewichtung)
    │       ├── Segmentation (Split/Merge/Gaps/Line-Breaks)
    │       ├── Lyrics Alignment (Template-System)
    │       ├── BPM Snap (Essentia/librosa)
    │       └── AI Lyrics Correction (Mistral)
    │       └──► list[TranscriptSegment] (refined)
    │
    ├─► [Export]
    │       ├── SRT ──► .srt
    │       ├── ASS (Karaoke) ──► .ass
    │       ├── VTT ──► .vtt
    │       ├── LRC (Enhanced) ──► .lrc
    │       ├── TXT ──► .txt
    │       ├── Karaoke HTML ──► .html
    │       └── Video Markers ──► .edl / .csv / .chapters.txt / .ffmeta / .markers.json
    │
    ├─► [Confidence Report] ──► .report.json
    ├─► [Waveform] ──► waveform.json
    ├─► [segments.json] ──► CRUD via API
    ├─► [Preview] ──► .preview.mp4
    ├─► [Library DB] ──► data/library.sqlite
    └─► [AI Chat] ──► .chat_history.sqlite
```

### Dateispeicherung pro Job

```
data/output/{job_id}/
    ├── {stem}.srt           # SRT-Untertitel
    ├── {stem}.ass           # ASS-Karaoke
    ├── {stem}.vtt           # WebVTT (optional)
    ├── {stem}.lrc           # LRC (optional)
    ├── {stem}.txt           # Plain Text (optional)
    ├── {stem}.report.json   # Konfidenz-Report
    ├── {stem}_karaoke.html  # Standalone HTML (optional)
    ├── segments.json        # Bearbeitbare Segmente
    ├── waveform.json        # Waveform-Peaks
    ├── {original_audio}     # Kopie für Playback
    ├── .chat_history.sqlite # AI-Chat-History
    ├── snapshots/           # Segment-Snapshots
    │   └── snap_*.json
    ├── lyrics_original.*    # Original-Lyrics (wenn vorhanden)
    ├── lyrics_parsed.json   # Geparste Lyrics
    ├── *.alignment_report.json
    └── *.diff_report.json
```

---

*Erstellt am 2026-02-18 — Automatische Bestandsaufnahme des Karaoke Sub Tool v3.2*
