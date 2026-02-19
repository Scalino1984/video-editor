"""Logging setup with rich console output and persistent file logging."""

from __future__ import annotations

import logging
import os
import sys
import uuid
from contextvars import ContextVar
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.theme import Theme

custom_theme = Theme(
    {
        "info": "cyan",
        "warning": "yellow bold",
        "error": "red bold",
        "success": "green bold",
        "highlight": "magenta bold",
        "dim": "dim white",
    }
)

console = Console(theme=custom_theme)
err_console = Console(stderr=True, theme=custom_theme)

# ── Correlation IDs (ContextVars for thread-safety) ──────────────────────────

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_job_id_var: ContextVar[str] = ContextVar("job_id", default="")


def set_request_id(rid: str = "") -> str:
    """Set the current request correlation ID. Returns the ID (generates one if empty)."""
    rid = rid or uuid.uuid4().hex[:12]
    _request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id_var.get()


def set_job_id(jid: str) -> None:
    """Set the current job ID for log correlation."""
    _job_id_var.set(jid)


def get_job_id() -> str:
    return _job_id_var.get()


def _ctx_prefix() -> str:
    """Build context prefix string from request_id / job_id."""
    parts = []
    rid = _request_id_var.get()
    jid = _job_id_var.get()
    if rid:
        parts.append(f"req={rid}")
    if jid:
        parts.append(f"job={jid}")
    return f"[{' '.join(parts)}] " if parts else ""


# ── File logging configuration ───────────────────────────────────────────────

LOG_DIR = Path("data/logs")
_file_logger: logging.Logger | None = None
_render_logger: logging.Logger | None = None


class _ContextFormatter(logging.Formatter):
    """Formatter that prepends request_id/job_id to every message."""

    def format(self, record: logging.LogRecord) -> str:
        prefix = _ctx_prefix()
        record.msg = f"{prefix}{record.msg}"
        return super().format(record)


def _setup_file_handler(
    logger: logging.Logger,
    filepath: Path,
    max_bytes: int = 50 * 1024 * 1024,
    backup_count: int = 5,
    level: int = logging.DEBUG,
) -> None:
    """Add a rotating file handler to a logger."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        filepath, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setLevel(level)
    fmt = _ContextFormatter("%(asctime)s %(levelname)-8s %(name)-20s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(fmt)
    logger.addHandler(handler)


class Verbosity(str, Enum):
    SILENT = "silent"
    NORMAL = "normal"
    VERBOSE = "verbose"


_current_verbosity = Verbosity.NORMAL


def setup_logging(verbosity: Verbosity = Verbosity.NORMAL) -> None:
    global _current_verbosity, _file_logger, _render_logger
    _current_verbosity = verbosity

    env_level = os.environ.get("LOG_LEVEL", "").upper()
    level_map = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING,
                 "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}

    if env_level in level_map:
        level = level_map[env_level]
    else:
        level = {
            Verbosity.SILENT: logging.ERROR,
            Verbosity.NORMAL: logging.INFO,
            Verbosity.VERBOSE: logging.DEBUG,
        }[verbosity]

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=err_console, show_path=False, markup=True)],
        force=True,
    )

    # ── Persistent file loggers ──
    # App log — all application messages
    _file_logger = logging.getLogger("karaoke.app")
    _file_logger.setLevel(logging.DEBUG)
    _file_logger.propagate = False
    _setup_file_handler(_file_logger, LOG_DIR / "app.log")

    # Render log — render-specific messages
    _render_logger = logging.getLogger("karaoke.render")
    _render_logger.setLevel(logging.DEBUG)
    _render_logger.propagate = False
    _setup_file_handler(_render_logger, LOG_DIR / "render.log")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_app_logger() -> logging.Logger:
    """Get the persistent app file logger."""
    return _file_logger or logging.getLogger("karaoke.app")


def get_render_logger() -> logging.Logger:
    """Get the persistent render file logger."""
    return _render_logger or logging.getLogger("karaoke.render")


def info(msg: str, **kwargs: Any) -> None:
    if _current_verbosity != Verbosity.SILENT:
        console.print(f"[info]ℹ {msg}[/info]", **kwargs)
    if _file_logger:
        _file_logger.info(msg)


def success(msg: str, **kwargs: Any) -> None:
    if _current_verbosity != Verbosity.SILENT:
        console.print(f"[success]✓ {msg}[/success]", **kwargs)
    if _file_logger:
        _file_logger.info(msg)


def warn(msg: str, **kwargs: Any) -> None:
    if _current_verbosity != Verbosity.SILENT:
        console.print(f"[warning]⚠ {msg}[/warning]", **kwargs)
    if _file_logger:
        _file_logger.warning(msg)


def error(msg: str, **kwargs: Any) -> None:
    err_console.print(f"[error]✗ {msg}[/error]", **kwargs)
    if _file_logger:
        _file_logger.error(msg)


def debug(msg: str, **kwargs: Any) -> None:
    if _current_verbosity == Verbosity.VERBOSE:
        console.print(f"[dim]  {msg}[/dim]", **kwargs)
    if _file_logger:
        _file_logger.debug(msg)


def render_log(msg: str, level: str = "info") -> None:
    """Write to the render-specific log file (always, regardless of verbosity)."""
    rl = _render_logger or logging.getLogger("karaoke.render")
    getattr(rl, level, rl.info)(msg)


def make_progress(**kwargs: Any) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        **kwargs,
    )
