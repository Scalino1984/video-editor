"""Vocal isolation and stem separation via Demucs.

Provides two interfaces:
- isolate_vocals() — simple Path→Path for the transcription pipeline
- VocalSeparator  — full-featured class for standalone separation jobs
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from src.utils.logging import info, warn, error, debug


def _demucs_thread_env(cpu_threads: int = 0) -> dict[str, str]:
    """Build env vars to limit torch/OMP/MKL threads in the demucs subprocess.

    Resolution: DEMUCS_THREADS env > cpu_threads arg > auto (half cores, max 6).
    Returns dict of env vars to merge into subprocess env.
    """
    env_t = os.environ.get("DEMUCS_THREADS", "")
    if env_t.isdigit() and int(env_t) > 0:
        threads = int(env_t)
    elif cpu_threads > 0:
        threads = cpu_threads
    else:
        cores = os.cpu_count() or 4
        threads = max(2, min(cores // 2, 6))

    info(f"Demucs CPU thread limit: {threads} (cores={os.cpu_count()})")
    return {
        "OMP_NUM_THREADS": str(threads),
        "MKL_NUM_THREADS": str(threads),
        "OPENBLAS_NUM_THREADS": str(threads),
        "VECLIB_MAXIMUM_THREADS": str(threads),
        "NUMEXPR_NUM_THREADS": str(threads),
        "TORCH_NUM_THREADS": str(threads),
    }


@dataclass(frozen=True)
class SeparationResult:
    """Result of a stem separation run."""
    vocals: str | None = None
    stems: dict[str, str] | None = None


class VocalSeparator:
    """Demucs CLI wrapper with robust binary resolution."""

    VALID_DEVICES = {"auto", "cpu", "cuda"}
    VALID_STEMS = {"vocals", "all"}
    VALID_BITRATES = {64, 96, 128, 160, 192, 224, 256, 320}

    def __init__(self, model: str = "htdemucs", device: str = "auto",
                 verbose: bool = True, cpu_threads: int = 0):
        self.model = model
        self.device = device
        self.verbose = verbose
        self.cpu_threads = cpu_threads
        self._available: bool | None = None
        self._demucs_exec: list[str] | None = None

    def _resolve_demucs_invocation(self) -> list[str] | None:
        """Find demucs executable: PATH → venv/bin → python -m demucs.separate."""
        # 1) PATH
        if shutil.which("demucs"):
            return ["demucs"]

        # 2) venv/bin/demucs next to interpreter
        venv_bin = Path(sys.executable).resolve().parent
        cand = venv_bin / "demucs"
        if cand.exists() and os.access(cand, os.X_OK):
            return [str(cand)]

        # 3) Module fallback
        if (importlib.util.find_spec("demucs") is not None
                and importlib.util.find_spec("demucs.separate") is not None):
            return [sys.executable, "-m", "demucs.separate"]

        return None

    def is_available(self) -> bool:
        """Check if Demucs is installed and callable."""
        if self._available is None:
            self._demucs_exec = self._resolve_demucs_invocation()
            self._available = self._demucs_exec is not None
        return self._available

    def _build_cmd(self, audio_path: Path, output_dir: Path, stems: str,
                   shifts: int, overlap: float, mp3: bool, mp3_bitrate: int) -> list[str]:
        if not self._demucs_exec:
            raise RuntimeError("Demucs invocation not resolved — call is_available() first")

        cmd = [*self._demucs_exec, "-n", self.model, "-o", str(output_dir)]

        if self.device in ("cpu", "cuda"):
            cmd.extend(["-d", self.device])
        elif self.device != "auto":
            raise ValueError(f"device must be auto|cpu|cuda, got {self.device}")

        if stems == "vocals":
            cmd.append("--two-stems=vocals")
        elif stems != "all":
            raise ValueError(f"stems must be vocals|all, got {stems}")

        if shifts > 1:
            cmd.extend(["--shifts", str(shifts)])
        if overlap != 0.25:
            cmd.extend(["--overlap", str(overlap)])
        if mp3:
            cmd.extend(["--mp3", "--mp3-bitrate", str(mp3_bitrate)])

        cmd.append(str(audio_path))
        return cmd

    def _find_output_dir(self, audio_path: Path, output_dir: Path) -> Path:
        return output_dir / self.model / audio_path.stem

    def _find_stem_file(self, base_dir: Path, stem_name: str) -> Path | None:
        for suffix in ("wav", "mp3"):
            direct = base_dir / f"{stem_name}.{suffix}"
            if direct.exists():
                return direct
        # glob fallback
        for suffix in ("wav", "mp3"):
            matches = sorted(base_dir.glob(f"**/{stem_name}.{suffix}"))
            if matches:
                return matches[0]
        return None

    def separate(self, audio_path: str | Path, output_dir: str | Path,
                 stems: str = "vocals", shifts: int = 1, overlap: float = 0.25,
                 mp3: bool = False, mp3_bitrate: int = 320,
                 timeout: int = 1200) -> SeparationResult:
        """Run Demucs separation. Returns SeparationResult."""
        if not self.is_available():
            error("Demucs not available (not in PATH, venv, or importable)")
            return SeparationResult()

        a_path = Path(audio_path).expanduser().resolve()
        o_dir = Path(output_dir).expanduser().resolve()

        if not a_path.exists() or not a_path.is_file():
            error(f"Input file not found: {a_path}")
            return SeparationResult()

        # Validate params
        if shifts < 1 or shifts > 10:
            error("shifts must be 1–10")
            return SeparationResult()
        if not (0.0 <= overlap <= 0.99):
            error("overlap must be 0.0–0.99")
            return SeparationResult()
        if mp3 and mp3_bitrate not in self.VALID_BITRATES:
            error(f"mp3_bitrate must be one of {self.VALID_BITRATES}")
            return SeparationResult()

        o_dir.mkdir(parents=True, exist_ok=True)
        cmd = self._build_cmd(a_path, o_dir, stems, shifts, overlap, mp3, mp3_bitrate)

        info(f"Demucs separation: model={self.model}, device={self.device}, stems={stems}")
        if self.verbose:
            debug(f"Command: {' '.join(cmd)}")

        # Ensure venv/bin is in PATH for subprocess
        env = dict(os.environ)
        venv_bin = str(Path(sys.executable).resolve().parent)
        env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"

        # Inject thread limits to prevent CPU exhaustion
        env.update(_demucs_thread_env(self.cpu_threads))

        try:
            from src.utils.media_executor import run_media_subprocess
            r = run_media_subprocess(
                cmd, tool="demucs",
                description=f"demucs {self.model} {stems} {a_path.name}",
                timeout=timeout, heavy=True, env=env,
            )
            if r.returncode != 0:
                error(f"Demucs failed (exit {r.returncode}): {r.stderr.strip()}")
                return SeparationResult()
        except subprocess.TimeoutExpired:
            error(f"Demucs timed out after {timeout}s")
            return SeparationResult()
        except FileNotFoundError:
            error("Demucs executable not found")
            return SeparationResult()

        base_dir = self._find_output_dir(a_path, o_dir)

        if stems == "vocals":
            vocals_file = self._find_stem_file(base_dir, "vocals")
            if vocals_file:
                info(f"Vocals isolated: {vocals_file}")
                return SeparationResult(vocals=str(vocals_file))
            error(f"Vocals file not found in {base_dir}")
            return SeparationResult()

        # stems == "all"
        found: dict[str, str] = {}
        for name in ("vocals", "drums", "bass", "other"):
            p = self._find_stem_file(base_dir, name)
            if p:
                found[name] = str(p)
        if not found:
            error(f"No stems found in {base_dir}")
            return SeparationResult(stems={})
        info(f"Stems extracted: {', '.join(found.keys())}")
        return SeparationResult(stems=found)


# ── Pipeline interface ────────────────────────────────────────────────────────

def isolate_vocals(input_path: Path, output_dir: Path | None = None,
                   model: str = "htdemucs", device: str = "cpu",
                   cpu_threads: int = 0) -> Path | None:
    """Simple vocal isolation for the transcription pipeline. Returns vocals path or None."""
    sep = VocalSeparator(model=model, device=device, cpu_threads=cpu_threads)
    if not sep.is_available():
        warn("Demucs not installed — skipping vocal isolation")
        warn("Install with: pip install demucs torch")
        return None

    if output_dir is None:
        output_dir = input_path.parent / "separated"

    result = sep.separate(str(input_path), str(output_dir), stems="vocals")
    if result.vocals:
        return Path(result.vocals)
    return None


def check_demucs_available() -> tuple[bool, str]:
    """Check if Demucs is available. Returns (available, message)."""
    sep = VocalSeparator()
    if sep.is_available():
        return True, "Demucs available"
    return False, "Demucs not found — install with: pip install demucs torch"
