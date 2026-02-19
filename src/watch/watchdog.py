"""Watch mode: monitor directory for new/changed audio files and auto-process."""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path
from threading import Timer
from typing import Callable

from src.preprocess.ffmpeg_io import is_supported_audio
from src.utils.logging import info, warn, error, success


class DebouncedHandler:
    """Debounce file events to avoid processing half-written files."""

    def __init__(self, callback: Callable[[Path], None], delay: float = 3.0):
        self.callback = callback
        self.delay = delay
        self._timers: dict[str, Timer] = {}

    def on_event(self, path: Path) -> None:
        key = str(path)
        if key in self._timers:
            self._timers[key].cancel()
        t = Timer(self.delay, self._fire, args=[path])
        t.start()
        self._timers[key] = t

    def _fire(self, path: Path) -> None:
        key = str(path)
        self._timers.pop(key, None)
        self.callback(path)

    def cancel_all(self) -> None:
        for t in self._timers.values():
            t.cancel()
        self._timers.clear()


def watch_directory(
    input_dir: Path,
    output_dir: Path,
    process_callback: Callable[[Path, Path], None],
    recursive: bool = False,
    debounce_sec: float = 3.0,
) -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    except ImportError:
        error("watchdog not installed. Install: pip install watchdog")
        return

    handler = DebouncedHandler(
        callback=lambda p: _safe_process(p, output_dir, process_callback),
        delay=debounce_sec,
    )

    class AudioHandler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory:
                path = Path(event.src_path)
                if is_supported_audio(path):
                    info(f"New file detected: {path.name}")
                    handler.on_event(path)

        def on_modified(self, event):
            if not event.is_directory:
                path = Path(event.src_path)
                if is_supported_audio(path):
                    info(f"Modified file detected: {path.name}")
                    handler.on_event(path)

    observer = Observer()
    observer.schedule(AudioHandler(), str(input_dir), recursive=recursive)
    observer.start()

    info(f"Watching: {input_dir} {'(recursive)' if recursive else ''}")
    info("Press Ctrl+C to stop")

    running = True

    def stop_handler(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    try:
        while running:
            time.sleep(1)
    finally:
        info("Stopping watch mode...")
        handler.cancel_all()
        observer.stop()
        observer.join()
        success("Watch mode stopped cleanly")


def _safe_process(path: Path, output_dir: Path, callback: Callable[[Path, Path], None]) -> None:
    try:
        callback(path, output_dir)
        success(f"Processed: {path.name}")
    except Exception as e:
        error(f"Error processing {path.name}: {e}")
