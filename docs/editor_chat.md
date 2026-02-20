# Editor Chat — AI-Steuerung im Video-Editor

## Überblick

Der Video-Editor kann per Chat-Nachricht gesteuert werden. Alle Timeline-Operationen
inkl. Track-Management sind über natürliche Sprache (Deutsch/Englisch) ausführbar.

## Architektur

```
Chat-Nachricht → Rule-Based Parser → (Treffer?) → Actions ausführen
                                    ↓ (kein Treffer)
                                    AI Model → ```action Blöcke → Actions ausführen
```

### Rule-Based Parser (deterministisch)

Der Parser erkennt direkte Befehle ohne AI-Aufruf:

| Kommando | Erkannte Muster |
|----------|----------------|
| Track hinzufügen | `+ video`, `füge eine audio spur hinzu`, `neue video ebene`, `add subtitle track` |
| Track entfernen | `- subtitle`, `- ebene 2`, `entferne spur 3`, `- ebene 1 force` |
| Undo | `undo`, `rückgängig`, `zurück` |
| Redo | `redo`, `wiederholen`, `vorwärts` |

### AI-Fallback

Komplexe Anweisungen (z.B. "mache das Video heller und schneide bei 5s") werden
an das konfigurierte AI-Modell weitergeleitet. Die AI antwortet mit `\`\`\`action`-Blöcken.

## Action-Schema

### Action Allowlist

Nur diese Aktionen sind erlaubt (Sicherheit):

**Clips**: `add_clip`, `remove_clip`, `update_clip`, `split_clip`
**Effekte**: `add_effect`, `remove_effect`
**Projekt**: `update_project`
**Tracks**: `add_track`, `remove_track`, `rename_track`, `set_track_props`, `reorder_tracks`
**Editor**: `undo`, `redo`
**Render**: `render`

### Beispiele (Deutsch)

```
Benutzer: "+ video"
→ ✅ add_track: Track V2 (video) hinzugefügt

Benutzer: "füge eine audio spur hinzu"
→ ✅ add_track: Track A2 (audio) hinzugefügt

Benutzer: "- ebene 3"
→ ✅ remove_track: Track entfernt

Benutzer: "undo"
→ ✅ undo: Undo erfolgreich
```

### Action JSON Format

```json
{"action": "add_track", "type": "video|audio|subtitle", "name": "V2"}
{"action": "remove_track", "track_id": "...", "force": false}
{"action": "rename_track", "track_id": "...", "name": "Neuer Name"}
{"action": "set_track_props", "track_id": "...", "enabled": true, "locked": false}
{"action": "reorder_tracks", "track_ids": ["id1", "id2", "id3"]}
```

## Sicherheitsregeln

1. **Strict Allowlist**: Nur Aktionen aus `ACTION_ALLOWLIST` werden ausgeführt
2. **Input Length Limit**: Max 4000 Zeichen pro Nachricht
3. **Keine freien Pfade**: Alle Operationen arbeiten über IDs (Asset-ID, Track-ID, Clip-ID)
4. **Keine Shell-Ausführung**: Kein `shell=True` in Subprozessen
5. **Undo/Redo**: Alle Chat-getriggerten Änderungen sind rückgängig machbar
6. **Audit**: Jede Chat-Aktion wird geloggt (project_id, message, actions)

## API Endpoint

```
POST /api/editor/projects/{pid}/ai-chat
Body: {"message": "...", "history": [...]}
Response: NDJSON stream mit {"text": "..."} Chunks
```

## Konfiguration

Setze in `.env`:
```
AI_MODEL=openai:gpt-4o    # oder anthropic:claude-*, mistral:*, google:*
OPENAI_API_KEY=sk-...
```

Ohne AI-Key funktioniert nur der Rule-Based Parser (Track-Befehle, Undo/Redo).
