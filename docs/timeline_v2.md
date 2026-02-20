# Timeline v2 — Schema & Architektur

## Überblick

Timeline v2 erweitert das bestehende Editor-Backend um ein **Track/Layer-System** mit beliebig vielen Spuren.
Die v2-Datenstruktur ist abwärtskompatibel — bestehende v1-Projekte werden beim Laden automatisch konvertiert.

## Schema

### Project (erweitert)

```json
{
  "id": "abc123",
  "name": "Mein Projekt",
  "timeline_version": 2,
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "tracks": [ ... ],
  "clips": [ ... ],
  "assets": { ... },
  "preset": "youtube",
  "crf": 20,
  ...
}
```

### Track

Jede Spur (Track/Ebene) hat folgende Felder:

| Feld      | Typ    | Default | Beschreibung |
|-----------|--------|---------|--------------|
| `id`      | str    | uuid    | Eindeutige ID |
| `type`    | str    | —       | `video`, `audio`, oder `subtitle` |
| `name`    | str    | auto    | Anzeigename (z.B. "V1", "A2") |
| `index`   | int    | auto    | Sortierindex |
| `enabled` | bool   | true    | Spur aktiv? |
| `locked`  | bool   | false   | Spur gesperrt? |
| `mute`    | bool   | false   | Nur Audio: stummgeschaltet |
| `solo`    | bool   | false   | Nur Audio: solo |
| `opacity` | float  | 1.0     | Nur Video: Track-Level Transparenz |
| `gain_db` | float  | 0.0     | Nur Audio: Track-Level Lautstärke |

### Default-Tracks

Neue Projekte werden mit 3 Standard-Tracks erstellt:
- `V1` (video, index=0)
- `A1` (audio, index=1)
- `S1` (subtitle, index=2)

## v1 → v2 Upgrade-on-Read

### Erkennung
- Fehlendes `timeline_version` → v1
- `timeline_version == 2` → v2 (keine Konvertierung)

### Konvertierung (`legacy_project_to_v2`)
Die Funktion `legacy_project_to_v2(project_dict)` wird automatisch angewendet:

1. Setzt `timeline_version = 2`
2. Erstellt Tracks basierend auf vorhandenen Clip-Track-Typen:
   - Clips mit `track: "video"` oder `track: "overlay"` → Video-Track
   - Clips mit `track: "audio"` → Audio-Track
   - Clips mit `track: "subtitle"` → Subtitle-Track
3. Video + Audio Tracks werden immer erstellt (auch ohne Clips)

### API-Verhalten
- `GET /api/editor/projects/{pid}` liefert immer v2-Format
- `PUT /api/editor/projects/{pid}` akzeptiert v1 und v2
- `Project.from_dict()` erstellt automatisch Default-Tracks wenn keine vorhanden

## RenderPlan (Überblick)

Der Renderer (`build_render_cmd` in `src/video/editor.py`) arbeitet intern mit der v2-Struktur:

1. **Normalisierung**: Tracks nach (type, index) sortiert, Items nach (start, z_index)
2. **Komposition**:
   - Video: Base-Canvas → Clip-Overlays → Subtitle Burn-in
   - Audio: Clips → Volume/Speed → Delay → amix
3. **Ausführung**: Via `src/utils/media_executor.py` (kein `shell=True`)
4. **Progress**: NDJSON-Streaming mit Phase + Percent

## Dateien

| Datei | Verantwortlichkeit |
|-------|-------------------|
| `src/video/editor.py` | Track/Project Datenmodell, CRUD, Undo/Redo, Render |
| `src/video/editor_routes.py` | REST API Endpoints |
| `src/video/ai_tools.py` | AI Chat + Rule-Based Parser |
| `src/video/render.py` | FFmpeg Render Helpers |
