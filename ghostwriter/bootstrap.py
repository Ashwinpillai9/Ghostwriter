"""Fetching, on first run, what the build deliberately did not ship with.

The CUDA runtime is 1.94 GB of a 2.23 GB payload and is useless without an NVIDIA card, so the
installer leaves it out and this fetches it — only where it will actually be used. The Whisper
model is another 1.6 GB and `faster-whisper` already downloads it on demand; this only triggers
that early, so the wait lands at a moment the user is expecting one rather than on their first
dictation.

Nothing here is required for Ghostwriter to work. No NVIDIA card means CPU transcription, which
`Transcriber._load` already falls back to. No internet means it says so and tries again next
start — reinstalling should never be the remedy for a bad network moment.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

# Kept in step with pyproject.toml: the same runtime the source install pins.
CUDA_PACKAGES = ("nvidia-cublas-cu12>=12.8", "nvidia-cudnn-cu12>=9.7,<10")

Progress = Callable[[str], None]


def _marker() -> Path:
    return paths.data_dir() / "bootstrap.json"


def completed() -> dict:
    """What previous runs managed to fetch, so a normal start does no network work."""
    try:
        return json.loads(_marker().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _record(**updates) -> None:
    state = completed()
    state.update(updates)
    try:
        _marker().parent.mkdir(parents=True, exist_ok=True)
        _marker().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:  # noqa: BLE001 - losing the marker costs a re-check, not correctness
        log.warning("could not record bootstrap state")


# --- what this machine can use ----------------------------------------------


def has_nvidia_gpu() -> bool:
    """Whether an NVIDIA card is present, asked without any CUDA installed.

    `nvidia-smi` ships with the *driver* rather than the toolkit, so it is there on any machine
    with a working NVIDIA card — which is exactly the population that wants the runtime. The
    display-adapter query is the fallback for a machine where it is missing from PATH.
    """
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable, no shell
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            log.info("NVIDIA GPU: %s", result.stdout.strip().splitlines()[0])
            return True
    except (OSError, subprocess.SubprocessError):
        log.debug("nvidia-smi unavailable", exc_info=True)

    try:
        result = subprocess.run(  # noqa: S603 - fixed executable, no shell
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
        return "nvidia" in result.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        log.debug("could not list display adapters", exc_info=True)
        return False


# --- the CUDA runtime --------------------------------------------------------


def cuda_present() -> bool:
    """Whether the runtime has already been unpacked for this machine."""
    root = paths.runtime_dir() / "nvidia"
    return root.is_dir() and any(root.rglob("*.dll"))


def fetch_cuda(on_progress: Progress | None = None) -> bool:
    """Download the CUDA runtime into the per-user runtime directory.

    Installed beside the config rather than beside the program files: an update replaces the
    program directory wholesale, and re-downloading 2 GB on every update would be absurd.
    """
    say = on_progress or (lambda _message: None)
    target = paths.runtime_dir()
    target.mkdir(parents=True, exist_ok=True)

    say("Fetching GPU support…")
    try:
        result = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            [sys.executable, "-m", "pip", "install", "--no-deps", "--upgrade",
             "--target", str(target), *CUDA_PACKAGES],
            capture_output=True, text=True, timeout=1800,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not fetch the CUDA runtime: %s", exc)
        say("Could not fetch GPU support — using the processor")
        return False

    if result.returncode != 0 or not cuda_present():
        log.warning("CUDA fetch failed: %s", (result.stderr or "")[:400])
        say("Could not fetch GPU support — using the processor")
        return False

    _record(cuda=True)
    say("GPU support ready")
    return True


# --- the model ---------------------------------------------------------------


def fetch_model(name: str, on_progress: Progress | None = None) -> bool:
    """Pull the dictation model into the shared Hugging Face cache.

    Only downloads; the model is loaded properly later by `Transcriber`. Doing it here means
    the several-minute wait happens while the user is watching a progress message, not when
    they press the dictation key for the first time.
    """
    say = on_progress or (lambda _message: None)
    say("Fetching the speech model — this happens once…")
    try:
        from faster_whisper.utils import download_model

        from .transcribe import MODEL_ALIASES

        download_model(MODEL_ALIASES.get(name, name))
    except Exception as exc:  # noqa: BLE001 - offline is an answer, not a crash
        log.warning("could not fetch the model: %s", exc)
        say("Could not fetch the speech model — will retry next start")
        return False

    _record(model=name)
    say("Speech model ready")
    return True


# --- the whole thing ---------------------------------------------------------

def needed(model_name: str, device: str) -> bool:
    """Whether anything is missing. A normal start answers this without touching the network."""
    state = completed()
    if state.get("model") != model_name:
        return True
    return device == "cuda" and has_nvidia_gpu() and not cuda_present()


def run(model_name: str, device: str, on_progress: Progress | None = None) -> dict:
    """Fetch whatever is missing. Never raises; a failure is reported and retried next start."""
    say = on_progress or (lambda _message: None)
    outcome = {"cuda": cuda_present(), "model": completed().get("model") == model_name}

    if device == "cuda" and not outcome["cuda"]:
        if has_nvidia_gpu():
            outcome["cuda"] = fetch_cuda(say)
        else:
            # Not a failure. Most machines are this, and CPU dictation works.
            log.info("no NVIDIA GPU; skipping the CUDA runtime")
            _record(cuda=False, cuda_skipped="no NVIDIA GPU")

    if not outcome["model"]:
        outcome["model"] = fetch_model(model_name, say)

    return outcome


def disk_free(path: Path | None = None) -> int:
    """Free bytes where downloads will land, so a caller can warn before starting."""
    try:
        return shutil.disk_usage(str(path or paths.data_dir())).free
    except OSError:
        return 0
