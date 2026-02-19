"""Cache and resume mechanism for processing pipeline."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


CACHE_DIR_NAME = ".karaoke_cache"


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()[:16]


def _file_mtime_id(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime:.6f}_{stat.st_size}"


def get_file_id(path: Path, method: str = "hash") -> str:
    if method == "hash":
        return _file_hash(path)
    return _file_mtime_id(path)


def get_cache_dir(input_path: Path) -> Path:
    if input_path.is_dir():
        cache_dir = input_path / CACHE_DIR_NAME
    else:
        cache_dir = input_path.parent / CACHE_DIR_NAME
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def cache_key(input_path: Path, stage: str, method: str = "hash") -> str:
    fid = get_file_id(input_path, method)
    return f"{input_path.stem}_{fid}_{stage}"


def load_cached(input_path: Path, stage: str, method: str = "hash") -> dict | None:
    cache_dir = get_cache_dir(input_path)
    key = cache_key(input_path, stage, method)
    cache_file = cache_dir / f"{key}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)
    return None


def save_cache(input_path: Path, stage: str, data: dict | list, method: str = "hash") -> Path:
    cache_dir = get_cache_dir(input_path)
    key = cache_key(input_path, stage, method)
    cache_file = cache_dir / f"{key}.json"
    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return cache_file


def output_exists(output_path: Path, input_path: Path, method: str = "hash") -> bool:
    if not output_path.exists():
        return False
    cache_dir = get_cache_dir(input_path)
    marker = cache_dir / f"{input_path.stem}_done_{get_file_id(input_path, method)}"
    return marker.exists()


def mark_done(output_path: Path, input_path: Path, method: str = "hash") -> None:
    cache_dir = get_cache_dir(input_path)
    marker = cache_dir / f"{input_path.stem}_done_{get_file_id(input_path, method)}"
    marker.write_text(str(output_path))
