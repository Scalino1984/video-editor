# Timeline Layers — Ebenen hinzufügen (+) & entfernen (-)

## Überblick

Das Track/Layer-System ermöglicht beliebig viele Video-, Audio- und Subtitle-Spuren
in der Timeline. Spuren können dynamisch hinzugefügt und entfernt werden — über die
REST API oder per Chat-Befehl.

## API Endpoints

### Track hinzufügen (+)

```http
POST /api/editor/projects/{pid}/tracks
Content-Type: application/json

{"type": "video", "name": "V2", "index": 3}
```

**Parameter:**
- `type` (required): `video`, `audio`, oder `subtitle`
- `name` (optional): Anzeigename; wird automatisch generiert wenn leer (z.B. "V2", "A3")
- `index` (optional): Sortierposition; wird automatisch am Ende eingefügt

**Response:**
```json
{
  "id": "abc123def4",
  "type": "video",
  "name": "V2",
  "index": 3,
  "enabled": true,
  "locked": false,
  "mute": false,
  "solo": false,
  "opacity": 1.0,
  "gain_db": 0.0
}
```

### Track entfernen (-)

```http
DELETE /api/editor/projects/{pid}/tracks/{track_id}?force=false&migrate_to_track_id=xyz
```

**Parameter:**
- `force` (optional, default: false): Erzwingt Löschung auch bei vorhandenen Clips
- `migrate_to_track_id` (optional): Verschiebt Clips auf eine andere Spur gleichen Typs

**Response:**
```json
{"removed": "abc123def4"}
```

### Track aktualisieren

```http
PUT /api/editor/projects/{pid}/tracks/{track_id}
Content-Type: application/json

{"name": "Hauptvideo", "locked": true, "mute": false}
```

**Erlaubte Felder:** `name`, `index`, `enabled`, `locked`, `mute`, `solo`, `opacity`, `gain_db`

### Tracks umsortieren

```http
POST /api/editor/projects/{pid}/tracks/reorder
Content-Type: application/json

{"track_ids": ["id3", "id1", "id2"]}
```

## Regeln beim Entfernen

| Situation | Verhalten |
|-----------|-----------|
| Spur ist leer | Kann immer entfernt werden |
| Spur enthält Clips, ist aber nicht die letzte ihres Typs | Kann entfernt werden (Clips bleiben auf anderem Track gleichen Typs) |
| Spur ist letzte ihres Typs + hat Clips + `force=false` | **Wird abgelehnt** (HTTP 400) |
| Spur ist letzte ihres Typs + hat Clips + `force=true` | Clips werden gelöscht (mit Undo!) |
| `migrate_to_track_id` gesetzt | Clips werden auf Ziel-Track verschoben (muss gleicher Typ sein) |

### Undo/Redo

Alle Track-Operationen unterstützen Undo/Redo:
- `POST /api/editor/projects/{pid}/undo` macht die letzte Änderung rückgängig
- `POST /api/editor/projects/{pid}/redo` stellt sie wieder her
- Auch Chat-getriggerte Änderungen sind undoable

## Chat-Befehle

Tracks können auch per Chat gesteuert werden:

| Befehl | Aktion |
|--------|--------|
| `+ video` | Neue Video-Spur hinzufügen |
| `+ audio` | Neue Audio-Spur hinzufügen |
| `+ subtitle` | Neue Subtitle-Spur hinzufügen |
| `füge eine video-ebene hinzu` | Neue Video-Spur (Deutsch) |
| `neue spur audio` | Neue Audio-Spur (Deutsch) |
| `- ebene 2` | Ebene 2 entfernen (1-basiert) |
| `- subtitle` | Letzte Subtitle-Spur entfernen |
| `entferne spur 3 force` | Spur 3 erzwungen entfernen |

## Frontend-Integration

### Events
- Tracks werden im Project-Objekt unter `tracks[]` zurückgegeben
- Jeder Track hat eine eindeutige `id` für DOM-Elemente
- Track-Änderungen können über `GET /api/editor/projects/{pid}` abgefragt werden

### Vorgeschlagene UI-Elemente
- **+ Button** pro Track-Typ-Bereich: ruft `POST /tracks` mit passendem `type` auf
- **× Button** pro Track-Header: ruft `DELETE /tracks/{id}` auf
- **Drag Handle** pro Track: ruft `POST /tracks/reorder` auf
- **Mute/Solo/Lock Toggle** pro Track: ruft `PUT /tracks/{id}` auf
