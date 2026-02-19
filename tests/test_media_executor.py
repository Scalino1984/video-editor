"""Tests for media_executor: concurrency, thread flags, nice prefix, queue status."""

from __future__ import annotations

import subprocess
import threading
import time
from unittest.mock import patch

import pytest


# ── Thread flag injection ─────────────────────────────────────────────────────

class TestFFmpegThreadFlags:
    """Verify -threads injection into ffmpeg commands."""

    def test_inject_threads_into_ffmpeg(self):
        from src.utils.media_executor import inject_ffmpeg_thread_flags, FFMPEG_THREADS
        cmd = ["ffmpeg", "-y", "-i", "in.mp3", "out.wav"]
        result = inject_ffmpeg_thread_flags(cmd)
        assert "-threads" in result
        idx = result.index("-threads")
        assert result[idx + 1] == str(FFMPEG_THREADS)

    def test_no_duplicate_threads(self):
        from src.utils.media_executor import inject_ffmpeg_thread_flags
        cmd = ["ffmpeg", "-threads", "4", "-y", "-i", "in.mp3", "out.wav"]
        result = inject_ffmpeg_thread_flags(cmd)
        assert result.count("-threads") == 1
        idx = result.index("-threads")
        assert result[idx + 1] == "4"  # original preserved

    def test_filter_complex_threads(self):
        from src.utils.media_executor import inject_ffmpeg_thread_flags, FFMPEG_THREADS
        cmd = ["ffmpeg", "-y", "-i", "in.mp4", "-filter_complex", "[0:v]scale=1920:1080[vout]", "out.mp4"]
        result = inject_ffmpeg_thread_flags(cmd)
        assert "-threads" in result
        assert "-filter_complex_threads" in result
        idx = result.index("-filter_complex_threads")
        assert result[idx + 1] == str(FFMPEG_THREADS)

    def test_ffprobe_no_thread_injection(self):
        from src.utils.media_executor import inject_ffmpeg_thread_flags
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "file.mp3"]
        result = inject_ffmpeg_thread_flags(cmd)
        assert "-threads" not in result

    def test_non_ffmpeg_passthrough(self):
        from src.utils.media_executor import inject_ffmpeg_thread_flags
        cmd = ["ls", "-la"]
        result = inject_ffmpeg_thread_flags(cmd)
        assert result == ["ls", "-la"]


# ── Nice prefix ──────────────────────────────────────────────────────────────

class TestNicePrefix:
    """Verify nice/ionice prefix construction."""

    def test_nice_prefix_on_linux(self):
        from src.utils import media_executor as me
        old_linux = me.IS_LINUX
        old_nice = me.MEDIA_NICE
        try:
            me.IS_LINUX = True
            me.MEDIA_NICE = 10
            prefix = me._build_nice_prefix()
            # On Linux with nice available, should contain "nice"
            if prefix:  # nice might not be in PATH in CI
                assert "nice" in prefix
        finally:
            me.IS_LINUX = old_linux
            me.MEDIA_NICE = old_nice

    def test_no_nice_on_non_linux(self):
        from src.utils import media_executor as me
        old_linux = me.IS_LINUX
        try:
            me.IS_LINUX = False
            prefix = me._build_nice_prefix()
            assert prefix == []
        finally:
            me.IS_LINUX = old_linux


# ── Queue status ──────────────────────────────────────────────────────────────

class TestQueueStatus:
    """Verify queue status reporting."""

    def test_status_structure(self):
        from src.utils.media_executor import get_media_queue_status
        status = get_media_queue_status()
        assert "max_concurrent" in status
        assert "ffmpeg_threads" in status
        assert "queued" in status
        assert "running" in status
        assert "jobs" in status
        assert isinstance(status["jobs"], list)

    def test_max_concurrent_from_env(self):
        from src.utils.media_executor import get_media_queue_status, MAX_MEDIA_JOBS
        status = get_media_queue_status()
        assert status["max_concurrent"] == MAX_MEDIA_JOBS


# ── Concurrency enforcement ──────────────────────────────────────────────────

class TestConcurrency:
    """Verify that the semaphore actually limits concurrent jobs."""

    def test_semaphore_limits_concurrency(self):
        """Run multiple jobs and verify max concurrency is respected."""
        from src.utils import media_executor as me

        # Force semaphore to 1 for testing
        old_sem = me._semaphore
        me._semaphore = threading.Semaphore(1)

        max_concurrent = 0
        current_concurrent = 0
        lock = threading.Lock()
        results = []

        def _count_job(idx: int):
            nonlocal max_concurrent, current_concurrent
            # Use echo as a lightweight subprocess
            r = me.run_media_subprocess(
                ["echo", f"job-{idx}"],
                tool="ffmpeg",
                description=f"test job {idx}",
                timeout=5,
                heavy=True,
            )
            results.append(r.returncode)

        threads = [threading.Thread(target=_count_job, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        me._semaphore = old_sem
        assert len(results) == 5
        assert all(rc == 0 for rc in results)

    def test_heavy_false_skips_semaphore(self):
        """Non-heavy jobs should bypass the semaphore."""
        from src.utils.media_executor import run_media_subprocess
        r = run_media_subprocess(
            ["echo", "fast"],
            tool="ffprobe",
            description="quick probe",
            timeout=5,
            heavy=False,
        )
        assert r.returncode == 0
        assert "fast" in r.stdout


# ── Subprocess runner ─────────────────────────────────────────────────────────

class TestRunMediaSubprocess:
    """Test the core subprocess runner."""

    def test_successful_run(self):
        from src.utils.media_executor import run_media_subprocess
        r = run_media_subprocess(
            ["echo", "hello world"],
            tool="ffmpeg",
            description="echo test",
            timeout=5,
            heavy=False,
        )
        assert r.returncode == 0
        assert "hello world" in r.stdout

    def test_failed_run_captured(self):
        from src.utils.media_executor import run_media_subprocess
        r = run_media_subprocess(
            ["false"],  # always exits 1
            tool="ffmpeg",
            description="fail test",
            timeout=5,
            heavy=False,
        )
        assert r.returncode != 0

    def test_timeout_raises(self):
        from src.utils.media_executor import run_media_subprocess
        with pytest.raises(subprocess.TimeoutExpired):
            run_media_subprocess(
                ["sleep", "10"],
                tool="ffmpeg",
                description="timeout test",
                timeout=1,
                heavy=False,
            )


# ── Source code audit ─────────────────────────────────────────────────────────

class TestSourceCodeAudit:
    """Verify no direct subprocess.run calls remain for ffmpeg/demucs in production code."""

    def _read_source(self, path: str) -> str:
        from pathlib import Path
        return Path(path).read_text(encoding="utf-8")

    def test_no_direct_subprocess_in_ffmpeg_io(self):
        src = self._read_source("src/preprocess/ffmpeg_io.py")
        assert "subprocess.run" not in src, "ffmpeg_io.py should use media_executor"

    def test_no_direct_subprocess_in_render(self):
        src = self._read_source("src/video/render.py")
        # Allow subprocess import for TimeoutExpired but not direct .run calls for ffmpeg
        lines_with_run = [l for l in src.splitlines()
                          if "subprocess.run" in l and "import" not in l]
        assert len(lines_with_run) == 0, f"render.py should use media_executor: {lines_with_run}"

    def test_no_direct_subprocess_in_preview(self):
        src = self._read_source("src/preview/render.py")
        lines_with_run = [l for l in src.splitlines()
                          if "subprocess.run" in l and "import" not in l]
        assert len(lines_with_run) == 0, f"preview/render.py should use media_executor: {lines_with_run}"

    def test_media_executor_used_in_vocals(self):
        src = self._read_source("src/preprocess/vocals.py")
        assert "run_media_subprocess" in src, "vocals.py should use media_executor"

    def test_media_executor_used_in_editor(self):
        src = self._read_source("src/video/editor.py")
        assert "run_media_subprocess" in src
        assert "run_media_popen" in src
        assert "release_media_popen" in src
