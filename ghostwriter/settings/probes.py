"""The things the settings window can only learn by asking the hardware.

Kept apart from `bridge.py` so that the config surface — which is pure data and fully testable —
does not get tangled up with microphones, GPUs and model caches.

Everything here runs in the settings process and touches only its own resources. It never
reaches into the running application: the mic level opens its own stream rather than borrowing
the recorder, and the wake-word test loads its own model rather than pausing the listener. That
is what keeps a settings window incapable of breaking dictation.
"""

from __future__ import annotations

import base64
import io
import logging
import threading
import time
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


# --- microphone --------------------------------------------------------------


def input_devices() -> list[dict[str, Any]]:
    """Input devices, with the system default first."""
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        default = sd.default.device[0] if sd.default.device else None
    except Exception:  # noqa: BLE001 - no audio backend is survivable; the list is just empty
        log.exception("could not list input devices")
        return []

    out = [{"index": None, "name": "System default", "isDefault": True}]
    for index, info in enumerate(devices):
        if info.get("max_input_channels", 0) <= 0:
            continue
        out.append(
            {
                "index": index,
                "name": info["name"],
                "isDefault": index == default,
                "channels": info["max_input_channels"],
            }
        )
    return out


class LevelMeter:
    """A short-lived input stream that reports its own loudness.

    Deliberately separate from the application's `Recorder`: the settings window may be open
    while dictation is idle, and it must not hold or reconfigure the device the app will use.
    """

    def __init__(self) -> None:
        self._stream = None
        self._level = 0.0
        self._peak = 0.0
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._stream is not None

    def start(self, device=None) -> bool:
        import sounddevice as sd

        self.stop()
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=device,
                blocksize=int(SAMPLE_RATE * 0.05),
                callback=self._on_audio,
            )
            self._stream.start()
        except Exception:  # noqa: BLE001 - a busy or missing device is the user's answer
            log.exception("could not open input device %r", device)
            self._stream = None
            return False
        return True

    def _on_audio(self, indata, frames, time_info, status):  # noqa: ARG002 - sounddevice API
        block = indata[:, 0]
        level = float(np.sqrt(np.mean(block**2)))
        with self._lock:
            self._level = level
            # Decay the peak rather than resetting it, so a meter has something to hold onto
            # between polls without looking jumpy.
            self._peak = max(level, self._peak * 0.92)

    def read(self) -> dict[str, float]:
        with self._lock:
            return {"level": self._level, "peak": self._peak}

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001 - the device may already be gone
                pass
        with self._lock:
            self._level = self._peak = 0.0


# --- wake word ---------------------------------------------------------------


def test_wake_word(
    phrase: str,
    aliases: list[str],
    threshold: float,
    seconds: float = 4.0,
    device=None,
    model_name: str = "tiny.en",
    compute_type: str = "int8",
) -> dict[str, Any]:
    """Record a few seconds and report what was heard, and how close it was.

    Uses the same decoder and the same `matches_phrase` the listener does, so a pass here means
    the real thing would fire — the point of the control is to be trustworthy, not merely
    encouraging.
    """
    import sounddevice as sd

    from ..transcribe import Transcriber
    from ..wakeword_whisper import matches_phrase, normalize

    frames: list[np.ndarray] = []
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", device=device,
            blocksize=int(SAMPLE_RATE * 0.05),
            callback=lambda indata, *_: frames.append(indata[:, 0].copy()),
        ):
            time.sleep(seconds)
    except Exception as exc:  # noqa: BLE001
        log.exception("wake-word test could not record")
        return {"ok": False, "error": str(exc)}

    audio = np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
    if audio.size == 0:
        return {"ok": False, "error": "nothing was recorded"}

    try:
        transcriber = Transcriber(
            name=model_name, device="cpu", compute_type=compute_type,
            language="en", vocabulary=[phrase], vad=False,
        )
        heard = transcriber.transcribe(audio)
    except Exception as exc:  # noqa: BLE001
        log.exception("wake-word test could not decode")
        return {"ok": False, "error": str(exc)}

    matched = matches_phrase(heard, phrase, aliases, threshold)
    return {
        "ok": True,
        "heard": heard,
        "normalized": normalize(heard),
        "matched": matched,
        "threshold": threshold,
        "score": _similarity(heard, phrase, aliases),
        "level": float(np.sqrt(np.mean(audio**2))),
    }


def _similarity(heard: str, phrase: str, aliases: list[str]) -> float:
    """Best match of what was heard against the phrase and its spellings, 0..1.

    Reported so a near miss reads as "0.74, just under your 0.80" rather than a bare failure.
    """
    from difflib import SequenceMatcher

    from ..wakeword_whisper import normalize

    text = normalize(heard)
    if not text:
        return 0.0
    best = 0.0
    for candidate in [normalize(p) for p in [phrase, *aliases] if normalize(p)]:
        if candidate in text:
            return 1.0
        words = text.split()
        size = len(candidate.split())
        for start in range(max(len(words) - size + 1, 1)):
            window = " ".join(words[start : start + size])
            best = max(best, SequenceMatcher(None, candidate, window).ratio())
    return round(best, 3)


# --- models ------------------------------------------------------------------

# Approximate download sizes, for telling the user what a choice costs before they make it.
MODEL_SIZES = {
    "tiny.en": "~75 MB",
    "base.en": "~145 MB",
    "small.en": "~480 MB",
    "medium.en": "~1.5 GB",
    "distil-large-v3": "~1.5 GB",
    "large-v3-turbo": "~1.6 GB",
}

MODEL_NOTES = {
    "tiny.en": "fastest, roughest — fine for short commands",
    "small.en": "a good middle",
    "large-v3-turbo": "most accurate, still quick on a GPU",
}


def repo_for(name: str) -> str:
    """The Hugging Face repo a model name resolves to.

    Mirrors `Transcriber._load`: our own alias table first, because it overrides
    `large-v3-turbo` to a different repo than faster-whisper's own default, then
    faster-whisper's table, then the raw name for a user-supplied repo id.
    """
    from ..transcribe import MODEL_ALIASES

    if name in MODEL_ALIASES:
        return MODEL_ALIASES[name]
    try:
        from faster_whisper.utils import _MODELS

        if name in _MODELS:
            return _MODELS[name]
    except Exception:  # noqa: BLE001 - table moved or renamed; fall through to the raw name
        log.debug("faster_whisper._MODELS unavailable", exc_info=True)
    return name


def downloaded_repos() -> set[str]:
    """Repo ids present in the Hugging Face cache."""
    try:
        from huggingface_hub import scan_cache_dir

        return {repo.repo_id for repo in scan_cache_dir().repos}
    except Exception:  # noqa: BLE001 - an unreadable cache means "we cannot tell", not a crash
        log.debug("could not scan the Hugging Face cache", exc_info=True)
        return set()


def model_catalog(current: str) -> list[dict[str, Any]]:
    """Every offered model, with its size and whether it is already on disk."""
    cached = downloaded_repos()
    names = list(MODEL_SIZES)
    if current not in names:
        names.append(current)  # a hand-written repo id in config.toml
    return [
        {
            "name": name,
            "repo": repo_for(name),
            "size": MODEL_SIZES.get(name, "unknown"),
            "note": MODEL_NOTES.get(name, ""),
            "downloaded": repo_for(name) in cached,
            "current": name == current,
        }
        for name in names
    ]


def gpu_info() -> dict[str, Any]:
    """Whether CUDA is usable, for the badge on the Model tab."""
    try:
        import ctranslate2

        count = ctranslate2.get_cuda_device_count()
    except Exception:  # noqa: BLE001
        log.debug("could not query CUDA", exc_info=True)
        return {"cuda": False, "devices": 0}
    return {"cuda": count > 0, "devices": count}


# --- pill preview ------------------------------------------------------------


def pill_preview(accent: str, state: str = "recording", width: int = 420) -> str | None:
    """A PNG of the real status pill, as a data URI.

    Rendered through `pill.py` rather than approximated in CSS. A copy would drift from the
    real pill the first time either changed, and the whole point of a preview is that it does
    not lie.
    """
    try:
        from ..pill import Frame
        from ..style import OverlayStyle

        style = OverlayStyle()
        colour = accent if state == "recording" else style.colors.get(state, accent)
        bars = [0.25, 0.6, 0.95, 0.45, 0.8, 0.3, 0.65, 0.4, 0.9, 0.5, 0.7,
                0.35, 0.85, 0.55, 0.75, 0.3, 0.6, 0.45, 0.8, 0.4, 0.7]
        frame = Frame(
            state=state,
            color=colour,
            glow=34.0 if state == "recording" else 24.0,
            bloom=0.14 if state == "recording" else 0.08,
            bars=bars if state == "recording" else [],
            bars_opacity=1.0 if state == "recording" else 0.0,
            orb=None if state == "recording" else (16.0, 10.0, 10.0, -5.0),
            label="" if state in ("recording", "idle") else _LABELS.get(state, ""),
            label_opacity=0.0 if state in ("recording", "idle") else 1.0,
        )
        image = frame.render()
        if width and width != image.width:
            height = round(image.height * width / image.width)
            image = image.resize((width, height))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 - a preview is a nicety; the tab still works without it
        log.exception("could not render the pill preview")
        return None


_LABELS = {
    "transcribing": "Transcribing…",
    "done": "Pasted",
    "error": "Transcription failed",
    "moving": "Drag me, then let go",
}
