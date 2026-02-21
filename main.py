"""Karaoke Sub Tool — FastAPI server with integrated WebUI.

Start with:
    python main.py
    python main.py --host 0.0.0.0 --port 8000
    python main.py --reload
"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

load_dotenv()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign a unique request_id to every incoming request for log correlation."""

    async def dispatch(self, request: Request, call_next):
        from src.utils.logging import set_request_id
        rid = request.headers.get("x-request-id", "")
        rid = set_request_id(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Startup
    from src.utils.deps_check import check_all, print_dep_status, check_all_backends
    from src.utils.logging import setup_logging, Verbosity, info, success

    setup_logging(Verbosity.NORMAL)
    info("Karaoke Sub Tool v3.2 starting...")

    deps = check_all()
    print_dep_status(deps)

    # Configure media executor (ffmpeg thread limits, nice, concurrency) from config.yaml
    try:
        from src.utils.config import load_config
        from src.utils.media_executor import configure_media_executor
        cfg = load_config()
        configure_media_executor(
            ffmpeg_threads=cfg.rendering.ffmpeg_threads,
            x264_threads=cfg.rendering.x264_threads,
            nice=cfg.rendering.nice,
            max_concurrent=cfg.rendering.max_concurrent,
        )
    except Exception as e:
        info(f"Media executor config: using defaults ({e})")

    backends = check_all_backends()
    available = [k for k, v in backends.items() if v]
    info(f"Available backends: {', '.join(available) or 'none'}")

    # AI check
    try:
        from src.ai.chat import get_model_name, has_ai_key, is_reasoning_model
        if has_ai_key():
            m = get_model_name()
            info(f"AI Chat: {m}" + (" (reasoning)" if is_reasoning_model(m) else ""))
        else:
            info("AI Chat: not configured (set AI_MODEL + API key in .env)")
    except ImportError:
        info("AI Chat: pydantic-ai not installed")

    # Library DB
    try:
        from src.db.library import init_db
        init_db()
    except Exception as e:
        info(f"Library DB: {e}")

    success("Server ready — WebUI: http://localhost:8000")

    yield  # app runs here

    # Shutdown
    try:
        from src.db.library import close_db
        close_db()
    except Exception:
        pass
    try:
        from src.ai.database import close_all as close_chat_dbs
        close_chat_dbs()
    except Exception:
        pass
    try:
        from src.api.tasks import unload_backend
        unload_backend()
    except Exception:
        pass


app = FastAPI(
    title="Karaoke Sub Tool",
    description="Professional karaoke subtitle generator from audio files",
    version="3.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIdMiddleware)

# ── API Routes ────────────────────────────────────────────────────────────────

from src.api.routes import router as api_router  # noqa: E402
from src.ai.routes import router as ai_router  # noqa: E402
from src.db.routes import router as lib_router  # noqa: E402
from src.video.editor_routes import router as editor_router  # noqa: E402
from src.video.overlay_routes import router as overlay_router  # noqa: E402
app.include_router(api_router)
app.include_router(ai_router)
app.include_router(lib_router)
app.include_router(editor_router)
app.include_router(overlay_router)

# ── Static / WebUI ────────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "src" / "static"
TEMPLATES_DIR = Path(__file__).parent / "src" / "templates"
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
(DATA_DIR / "uploads").mkdir(exist_ok=True)
(DATA_DIR / "output").mkdir(exist_ok=True)


@app.get("/", include_in_schema=False)
async def serve_ui():
    return FileResponse(TEMPLATES_DIR / "index.html")


@app.get("/editor", include_in_schema=False)
async def serve_editor():
    return FileResponse(TEMPLATES_DIR / "editor.html")


@app.get("/files", include_in_schema=False)
async def serve_fileexplorer():
    return FileResponse(TEMPLATES_DIR / "fileexplorer.html")


# serve static assets (CSS, JS, favicons, images)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static_files")

# serve output files (for audio playback, preview, downloads)
app.mount("/data/output", StaticFiles(directory=str(DATA_DIR / "output")), name="output_files")
app.mount("/data/uploads", StaticFiles(directory=str(DATA_DIR / "uploads")), name="upload_files")

# Editor data directories
EDITOR_DATA = DATA_DIR / "editor"
EDITOR_DATA.mkdir(exist_ok=True)
(EDITOR_DATA / "assets").mkdir(exist_ok=True)
(EDITOR_DATA / "projects").mkdir(exist_ok=True)
(EDITOR_DATA / "renders").mkdir(exist_ok=True)
(EDITOR_DATA / "overlays").mkdir(exist_ok=True)
app.mount("/data/editor", StaticFiles(directory=str(EDITOR_DATA)), name="editor_files")


# ── CLI Entry Point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Karaoke Sub Tool Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    parser.add_argument("--workers", type=int, default=1, help="Number of workers")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level="info",
    )


if __name__ == "__main__":
    main()
