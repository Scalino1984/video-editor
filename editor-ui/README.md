# Video Editor v4 — React Frontend

Eigenständiges React-Frontend für den Video Editor. Läuft auf Port **3001**, kommuniziert mit dem FastAPI-Backend auf Port **8000**.

## Starten

```bash
# 1. Backend starten (im Hauptverzeichnis)
cd .. && uvicorn main:app --reload --port 8000

# 2. Frontend starten (Development mit Hot Reload)
cd editor-ui && npm run dev
# → http://localhost:3001
```

## Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `npm run dev` | Dev-Server mit HMR auf Port 3001, API-Proxy zu :8000 |
| `npm run build` | Production Build nach `dist/` |
| `npm run preview` | Production Build lokal testen auf Port 3001 |
| `npm run serve` | Build + statischen Server starten |

## Konfiguration

| Variable | Standard | Beschreibung |
|----------|----------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | Backend URL (nur für Production Build) |

Im Dev-Modus wird `/api/*` und `/data/*` automatisch per Vite-Proxy an `localhost:8000` weitergeleitet.

## Architektur

```
src/
├── api/editor.ts              # 18 API-Endpunkte (fetch-Wrapper)
├── stores/useEditorStore.ts   # Zustand State Management
├── hooks/
│   ├── usePlayback.ts         # RAF-Loop, Video/Audio Sync, A/B-Loop
│   └── useKeyboardShortcuts.ts # Space, Ctrl+Z/Y/S, Alt+A/B/C, Del
├── types.ts                   # TypeScript Interfaces
├── utils/format.ts            # Time-Format, ASS↔Hex, SRT/ASS Parser
├── components/
│   ├── Header/                # Projekt-Name, Themes, Undo/Redo, Render
│   ├── Sidebar/               # Assets, Jobs-Import, Templates
│   ├── Preview/               # Video-Player, Subtitle-Overlay, Transport
│   ├── Timeline/              # Canvas-Ruler, Track-Lanes, Drag/Resize
│   ├── Properties/            # Clip, Effekte, Projekt-Settings, AI-Chat
│   └── Modals/                # Neues Projekt, Projekt öffnen
└── App.tsx                    # Layout, Welcome, Toasts
```

## Keyboard Shortcuts

| Taste | Aktion |
|-------|--------|
| `Space` | Play / Pause |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Ctrl+S` | Speichern |
| `Delete` | Clip löschen |
| `S` | Split am Playhead |
| `Alt+A` | Loop-Start setzen |
| `Alt+B` | Loop-Ende setzen |
| `Alt+C` | Loop löschen |
| `←` / `→` | ±1 Sekunde |
| `Ctrl+Scroll` | Timeline Zoom |
