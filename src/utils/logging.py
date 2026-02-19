"""Logging setup with rich console output."""

from __future__ import annotations

import logging
import sys
from enum import Enum
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


class Verbosity(str, Enum):
    SILENT = "silent"
    NORMAL = "normal"
    VERBOSE = "verbose"


_current_verbosity = Verbosity.NORMAL


def setup_logging(verbosity: Verbosity = Verbosity.NORMAL) -> None:
    global _current_verbosity
    _current_verbosity = verbosity

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


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def info(msg: str, **kwargs: Any) -> None:
    if _current_verbosity != Verbosity.SILENT:
        console.print(f"[info]ℹ {msg}[/info]", **kwargs)


def success(msg: str, **kwargs: Any) -> None:
    if _current_verbosity != Verbosity.SILENT:
        console.print(f"[success]✓ {msg}[/success]", **kwargs)


def warn(msg: str, **kwargs: Any) -> None:
    if _current_verbosity != Verbosity.SILENT:
        console.print(f"[warning]⚠ {msg}[/warning]", **kwargs)


def error(msg: str, **kwargs: Any) -> None:
    err_console.print(f"[error]✗ {msg}[/error]", **kwargs)


def debug(msg: str, **kwargs: Any) -> None:
    if _current_verbosity == Verbosity.VERBOSE:
        console.print(f"[dim]  {msg}[/dim]", **kwargs)


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
