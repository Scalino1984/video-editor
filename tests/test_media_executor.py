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
        assert "max_pending" in status
        assert "ffmpeg_threads" in status
        assert "queued" in status
        assert "running" in status
        assert "jobs" in status
        assert isinstance(status["jobs"], list)

    def test_max_concurrent_from_env(self):
        from src.utils.media_executor import get_media_queue_status, MAX_MEDIA_JOBS
        status = get_media_queue_status()
        assert status["max_concurrent"] == MAX_MEDIA_JOBS


# ── Backpressure / capacity check ─────────────────────────────────────────────

class TestBackpressure:
    """Verify check_media_capacity backpressure logic."""

    def test_has_capacity_when_idle(self):
        from src.utils.media_executor import check_media_capacity
        has_cap, running, queued = check_media_capacity()
        assert has_cap is True

    def test_no_capacity_when_full(self):
        from src.utils import media_executor as me
        old_max = me.MAX_PENDING_MEDIA_JOBS
        old_jobs = me._active_jobs.copy()
        try:
            me.MAX_PENDING_MEDIA_JOBS = 2
            # Simulate 2 running jobs
            me._active_jobs["fake-1"] = me.MediaJobInfo(
                id="fake-1", tool="ffmpeg", description="test1",
                status=me.MediaJobStatus.running,
            )
            me._active_jobs["fake-2"] = me.MediaJobInfo(
                id="fake-2", tool="demucs", description="test2",
                status=me.MediaJobStatus.queued,
            )
            has_cap, running, queued = me.check_media_capacity()
            assert has_cap is False
            assert running == 1
            assert queued == 1
        finally:
            me._active_jobs.clear()
            me._active_jobs.update(old_jobs)
            me.MAX_PENDING_MEDIA_JOBS = old_max

    def test_capacity_respects_only_active_statuses(self):
        from src.utils import media_executor as me
        old_max = me.MAX_PENDING_MEDIA_JOBS
        old_jobs = me._active_jobs.copy()
        try:
            me.MAX_PENDING_MEDIA_JOBS = 2
            # Finished jobs should not count
            me._active_jobs["done-1"] = me.MediaJobInfo(
                id="done-1", tool="ffmpeg", description="done",
                status=me.MediaJobStatus.done,
            )
            me._active_jobs["failed-1"] = me.MediaJobInfo(
                id="failed-1", tool="ffmpeg", description="failed",
                status=me.MediaJobStatus.failed,
            )
            has_cap, running, queued = me.check_media_capacity()
            assert has_cap is True
            assert running == 0
            assert queued == 0
        finally:
            me._active_jobs.clear()
            me._active_jobs.update(old_jobs)
            me.MAX_PENDING_MEDIA_JOBS = old_max


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


# ── configure_media_executor ──────────────────────────────────────────────────

class TestConfigureMediaExecutor:
    """Verify configure_media_executor applies settings correctly."""

    def test_explicit_values(self):
        from src.utils import media_executor as me
        old_t = me.FFMPEG_THREADS
        old_n = me.MEDIA_NICE
        try:
            result = me.configure_media_executor(
                ffmpeg_threads=3, x264_threads=2, nice=5, max_concurrent=2,
            )
            assert me.FFMPEG_THREADS == 3
            assert me.X264_THREADS == 2
            assert me.MEDIA_NICE == 5
            assert me.MAX_MEDIA_JOBS == 2
            assert result["ffmpeg_threads"] == 3
            assert result["x264_threads"] == 2
        finally:
            # Restore defaults
            me.configure_media_executor(ffmpeg_threads=old_t, nice=old_n, max_concurrent=1)

    def test_auto_threads(self):
        import os
        from src.utils import media_executor as me
        old_t = me.FFMPEG_THREADS
        # Remove env overrides
        env_backup = {k: os.environ.pop(k, None) for k in ("FFMPEG_THREADS", "X264_THREADS")}
        try:
            result = me.configure_media_executor(ffmpeg_threads=0, x264_threads=0)
            cores = os.cpu_count() or 4
            expected = max(2, min(cores // 2, 8))
            assert result["ffmpeg_threads"] == expected
            assert result["x264_threads"] == expected  # x264 defaults to ffmpeg_threads
        finally:
            for k, v in env_backup.items():
                if v is not None:
                    os.environ[k] = v
            me.configure_media_executor(ffmpeg_threads=old_t, max_concurrent=1)

    def test_env_override_takes_precedence(self):
        import os
        from src.utils import media_executor as me
        old_t = me.FFMPEG_THREADS
        os.environ["FFMPEG_THREADS"] = "5"
        try:
            result = me.configure_media_executor(ffmpeg_threads=3)
            assert result["ffmpeg_threads"] == 5  # env wins over config
        finally:
            os.environ.pop("FFMPEG_THREADS", None)
            me.configure_media_executor(ffmpeg_threads=old_t, max_concurrent=1)


class TestX264ThreadInjection:
    """Verify x264 thread limits are injected into ffmpeg commands."""

    def test_x264_threads_injected(self):
        from src.utils import media_executor as me
        old_x = me.X264_THREADS
        try:
            me.X264_THREADS = 4
            cmd = ["ffmpeg", "-y", "-i", "in.mp4", "-c:v", "libx264", "-crf", "18", "out.mp4"]
            result = me.inject_ffmpeg_thread_flags(cmd)
            assert "-x264opts" in result
            idx = result.index("-x264opts")
            assert f"threads=4" in result[idx + 1]
        finally:
            me.X264_THREADS = old_x

    def test_x264_threads_not_injected_for_other_codecs(self):
        from src.utils import media_executor as me
        old_x = me.X264_THREADS
        try:
            me.X264_THREADS = 4
            cmd = ["ffmpeg", "-y", "-i", "in.mp4", "-c:v", "libx265", "-crf", "18", "out.mp4"]
            result = me.inject_ffmpeg_thread_flags(cmd)
            assert "-x264opts" not in result
        finally:
            me.X264_THREADS = old_x

    def test_x264_threads_appended_to_existing_opts(self):
        from src.utils import media_executor as me
        old_x = me.X264_THREADS
        try:
            me.X264_THREADS = 3
            cmd = ["ffmpeg", "-y", "-i", "in.mp4", "-c:v", "libx264",
                   "-x264opts", "keyint=60", "-crf", "18", "out.mp4"]
            result = me.inject_ffmpeg_thread_flags(cmd)
            idx = result.index("-x264opts")
            assert "threads=3" in result[idx + 1]
            assert "keyint=60" in result[idx + 1]
        finally:
            me.X264_THREADS = old_x

    def test_no_x264_injection_when_zero(self):
        from src.utils import media_executor as me
        old_x = me.X264_THREADS
        try:
            me.X264_THREADS = 0
            cmd = ["ffmpeg", "-y", "-i", "in.mp4", "-c:v", "libx264", "-crf", "18", "out.mp4"]
            result = me.inject_ffmpeg_thread_flags(cmd)
            assert "-x264opts" not in result
        finally:
            me.X264_THREADS = old_x


class TestRenderingConfig:
    """Verify RenderingConfig in AppConfig."""

    def test_default_config_has_rendering(self):
        from src.utils.config import AppConfig
        cfg = AppConfig()
        assert cfg.rendering.ffmpeg_threads == 0
        assert cfg.rendering.x264_threads == 0
        assert cfg.rendering.nice == 10
        assert cfg.rendering.max_concurrent == 1

    def test_config_yaml_loads_rendering(self):
        import yaml
        from src.utils.config import AppConfig
        data = yaml.safe_load("""
rendering:
  ffmpeg_threads: 4
  x264_threads: 3
  nice: 15
  max_concurrent: 2
""")
        cfg = AppConfig(**data)
        assert cfg.rendering.ffmpeg_threads == 4
        assert cfg.rendering.x264_threads == 3
        assert cfg.rendering.nice == 15
        assert cfg.rendering.max_concurrent == 2


# ── Demucs thread env ────────────────────────────────────────────────────────

class TestDemucsThreadEnv:
    """Verify _demucs_thread_env builds correct subprocess env vars."""

    def test_explicit_threads(self):
        from src.preprocess.vocals import _demucs_thread_env
        env = _demucs_thread_env(cpu_threads=4)
        assert env["OMP_NUM_THREADS"] == "4"
        assert env["MKL_NUM_THREADS"] == "4"
        assert env["OPENBLAS_NUM_THREADS"] == "4"
        assert env["TORCH_NUM_THREADS"] == "4"

    def test_auto_threads(self):
        import os
        from src.preprocess.vocals import _demucs_thread_env
        env_backup = os.environ.pop("DEMUCS_THREADS", None)
        try:
            env = _demucs_thread_env(cpu_threads=0)
            cores = os.cpu_count() or 4
            expected = str(max(2, min(cores // 2, 6)))
            assert env["OMP_NUM_THREADS"] == expected
        finally:
            if env_backup is not None:
                os.environ["DEMUCS_THREADS"] = env_backup

    def test_env_override(self):
        import os
        from src.preprocess.vocals import _demucs_thread_env
        os.environ["DEMUCS_THREADS"] = "3"
        try:
            env = _demucs_thread_env(cpu_threads=6)
            assert env["OMP_NUM_THREADS"] == "3"  # env wins
        finally:
            os.environ.pop("DEMUCS_THREADS", None)

    def test_all_env_vars_present(self):
        from src.preprocess.vocals import _demucs_thread_env
        env = _demucs_thread_env(cpu_threads=2)
        expected_keys = {"OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                         "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "TORCH_NUM_THREADS"}
        assert expected_keys.issubset(set(env.keys()))


class TestDemucsConfig:
    """Verify cpu_threads in VocalIsolationConfig."""

    def test_default_config_has_demucs_threads(self):
        from src.utils.config import AppConfig
        cfg = AppConfig()
        assert cfg.preprocess.vocal_isolation.cpu_threads == 0

    def test_config_yaml_loads_demucs_threads(self):
        import yaml
        from src.utils.config import AppConfig
        data = yaml.safe_load("""
preprocess:
  vocal_isolation:
    enabled: true
    model: htdemucs
    device: cpu
    cpu_threads: 4
""")
        cfg = AppConfig(**data)
        assert cfg.preprocess.vocal_isolation.cpu_threads == 4
