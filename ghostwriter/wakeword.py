"""Always-on wake-word listener built on openWakeWord.

Runs a small ONNX model over 80 ms microphone frames on the CPU. The Whisper GPU model is
only touched after the wake word fires, so idle cost stays near zero.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
import sounddevice as sd

from .audio import resolve_device

log = logging.getLogger(__name__)

FRAME_SAMPLES = 1280  # openWakeWord expects 80 ms of 16 kHz int16 audio per predict() call.
SAMPLE_RATE = 16000


class WakeWordListener:
    def __init__(
        self,
        on_detect: Callable[[], None],
        model_path: str = "",
        fallback_model: str = "hey_jarvis",
        threshold: float = 0.5,
        cooldown_sec: float = 2.0,
        device: str = "",
    ):
        self.on_detect = on_detect
        self.threshold = threshold
        self.cooldown_frames = int(cooldown_sec * SAMPLE_RATE / FRAME_SAMPLES)
        self.device = resolve_device(device)
        self.model_path = model_path
        self.fallback_model = fallback_model

        self._frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)
        self._stream: sd.InputStream | None = None
        self._worker: threading.Thread | None = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._model = None
        self.model_name = ""
        self.using_fallback = False

    # --- model -----------------------------------------------------------

    @staticmethod
    def _ensure_pretrained() -> None:
        """openWakeWord ships without weights; the melspectrogram/embedding models are
        required even when a custom wake word is used."""
        import openwakeword
        import openwakeword.utils

        models_dir = Path(openwakeword.__file__).parent / "resources" / "models"
        if not (models_dir / "melspectrogram.onnx").exists():
            log.info("downloading openWakeWord base models (one time)")
            openwakeword.utils.download_models()

    def load(self) -> None:
        self._ensure_pretrained()
        from openwakeword.model import Model

        path = Path(self.model_path) if self.model_path else None
        if path and not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path

        if path and path.exists():
            self._model = Model(wakeword_models=[str(path)], inference_framework="onnx")
            self.using_fallback = False
        else:
            if self.model_path:
                log.warning(
                    "custom wake-word model %s not found; falling back to %r",
                    path,
                    self.fallback_model,
                )
            self._model = Model(
                wakeword_models=[self.fallback_model], inference_framework="onnx"
            )
            self.using_fallback = True
        self.model_name = next(iter(self._model.models.keys()))

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._running.is_set():
            return
        if self._model is None:
            self.load()
        self._running.set()
        self._paused.clear()
        self._worker = threading.Thread(target=self._detect_loop, daemon=True)
        self._worker.start()
        self._open_stream()

    def stop(self) -> None:
        self._running.clear()
        self._close_stream()

    def pause(self) -> None:
        """Release the microphone so the dictation recorder can own it exclusively."""
        self._paused.set()
        self._close_stream()
        self._drain()

    def resume(self) -> None:
        if not self._running.is_set():
            return
        self._drain()
        self._reset_model()
        self._paused.clear()
        self._open_stream()

    @property
    def listening(self) -> bool:
        return self._running.is_set() and not self._paused.is_set()

    # --- audio -----------------------------------------------------------

    def _open_stream(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            device=self.device,
            blocksize=FRAME_SAMPLES,
            callback=self._callback,
        )
        self._stream.start()

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001 - device may already be gone
                pass

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002 - sounddevice API
        try:
            self._frames.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass  # Detection fell behind; dropping a frame beats stalling the audio thread.

    def _drain(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    def _reset_model(self) -> None:
        """Clear the model's internal buffers so audio from before a pause can't retrigger."""
        try:
            self._model.reset()
        except Exception:  # noqa: BLE001 - older versions lack reset()
            pass

    # --- detection -------------------------------------------------------

    def _detect_loop(self) -> None:
        cooldown = 0
        while self._running.is_set():
            try:
                frame = self._frames.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._paused.is_set():
                continue
            if cooldown > 0:
                cooldown -= 1
                continue
            try:
                scores = self._model.predict(frame)
            except Exception:  # noqa: BLE001 - never let a bad frame kill the listener
                log.exception("wake-word inference failed")
                continue
            if max(scores.values(), default=0.0) >= self.threshold:
                cooldown = self.cooldown_frames
                log.info("wake word detected (%s)", self.model_name)
                try:
                    self.on_detect()
                except Exception:  # noqa: BLE001
                    log.exception("wake-word callback failed")
