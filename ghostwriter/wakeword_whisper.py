"""Wake-word listener that needs no trained model.

openWakeWord has no pretrained "hey ghost", and training one takes a GPU box plus several GB
of negative-audio datasets — a barrier that would leave every user stuck on a fallback phrase
like "hey jarvis". This backend sidesteps training entirely: a voice-activity detector watches
the microphone, and only a completed burst of speech is decoded by a tiny Whisper model and
string-matched against the phrase.

Any phrase works, out of the box, with nothing to download beyond the ~75 MB tiny.en model.
The gate is Silero VAD, which faster-whisper already ships — so no new dependency, and unlike
a plain loudness threshold it ignores fans, keyboards and a hot microphone's own hiss. That
matters: on a mic with automatic gain the idle noise floor alone sits above any fixed
threshold, which would leave the decoder running non-stop. The large dictation model is still
only touched once the phrase fires.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
from collections.abc import Callable
from difflib import SequenceMatcher

import numpy as np
import sounddevice as sd

from .audio import resolve_device

log = logging.getLogger(__name__)

VAD_SAMPLES = 512  # Silero's fixed input size: 32 ms at 16 kHz.
FRAMES_PER_CHUNK = 8  # VAD runs over 256 ms at a time, keeping its state within the chunk.
FRAME_SAMPLES = VAD_SAMPLES * FRAMES_PER_CHUNK
SAMPLE_RATE = 16000
WINDOW_SEC = 2.5  # Rolling audio kept for the decoder; a wake phrase is far shorter.
HANGOVER_SEC = 0.32  # Silence that marks the end of a burst.
MIN_BURST_SEC = 0.25  # Shorter than this is a cough or a door, not a phrase.
MAX_BURST_SEC = 2.0  # A burst this long is a sentence; decode it and move on.

_PUNCTUATION = re.compile(r"[^a-z0-9 ]+")


def normalize(text: str) -> str:
    return " ".join(_PUNCTUATION.sub(" ", text.lower()).split())


def matches_phrase(text: str, phrase: str, aliases: list[str], fuzz: float = 0.8) -> bool:
    """True when `text` contains the wake phrase, allowing for Whisper's near misses.

    Exact containment handles the clean case. The fuzzy pass slides a window of the phrase's
    word count across the transcript, so "okay hey ghosts" still fires while a long unrelated
    sentence does not — comparing against the whole transcript would let length differences
    mask a match.
    """
    text = normalize(text)
    if not text:
        return False
    candidates = [normalize(p) for p in [phrase, *aliases]]
    candidates = [p for p in candidates if p]
    if any(p in text for p in candidates):
        return True

    words = text.split()
    for candidate in candidates:
        parts = candidate.split()
        size = len(parts)
        for start in range(max(len(words) - size + 1, 1)):
            window = words[start : start + size]
            # The attention word has to actually be there. Whole-window similarity alone lets
            # "the ghost writer branch" through, because only the throwaway first word differs.
            if SequenceMatcher(None, parts[0], window[0]).ratio() < fuzz:
                continue
            if SequenceMatcher(None, candidate, " ".join(window)).ratio() >= fuzz:
                return True
    return False


class WhisperWakeWordListener:

    def __init__(
        self,
        on_detect: Callable[[], None],
        phrase: str = "hey ghost",
        aliases: list[str] | None = None,
        model_name: str = "tiny.en",
        device_type: str = "cpu",
        compute_type: str = "int8",
        threshold: float = 0.8,
        vad_threshold: float = 0.5,
        cooldown_sec: float = 2.0,
        device: str = "",
    ):
        self.on_detect = on_detect
        self.phrase = phrase
        self.aliases = aliases or []
        self.whisper_model = model_name
        self.device_type = device_type
        self.compute_type = compute_type
        self.threshold = threshold
        self.vad_threshold = vad_threshold
        self.cooldown_sec = cooldown_sec
        self.device = resolve_device(device)

        self._frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)
        self._stream: sd.InputStream | None = None
        self._worker: threading.Thread | None = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._transcriber = None
        self._vad = None
        self.model_name = phrase.replace(" ", "_")

    # --- model -----------------------------------------------------------

    def load(self) -> None:
        from faster_whisper.vad import get_vad_model

        from .transcribe import Transcriber

        self._vad = get_vad_model()

        # Biasing the decoder with the phrase itself is what makes a tiny model reliable on
        # an invented word like "ghost" as a name.
        self._transcriber = Transcriber(
            name=self.whisper_model,
            device=self.device_type,
            compute_type=self.compute_type,
            language="en",
            vocabulary=[self.phrase],
            vad=False,
        )

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._running.is_set():
            return
        if self._transcriber is None:
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
            dtype="float32",
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

    # --- detection -------------------------------------------------------

    def _speech_flags(self, chunk: np.ndarray) -> np.ndarray:
        """Per-32 ms speech/not-speech decisions for one captured chunk."""
        try:
            probs = self._vad(chunk.astype(np.float32), num_samples=VAD_SAMPLES)
        except Exception:  # noqa: BLE001 - a VAD hiccup shouldn't deafen the listener
            log.exception("wake-word VAD failed")
            return np.zeros(FRAMES_PER_CHUNK, dtype=bool)
        return np.asarray(probs).reshape(-1) >= self.vad_threshold

    def _detect_loop(self) -> None:
        window: list[np.ndarray] = []
        window_samples = 0
        max_window = int(WINDOW_SEC * SAMPLE_RATE)
        # Burst lengths are counted in VAD frames, since that is the resolution we decide at.
        hangover = round(HANGOVER_SEC * SAMPLE_RATE / VAD_SAMPLES)
        min_burst = round(MIN_BURST_SEC * SAMPLE_RATE / VAD_SAMPLES)
        max_burst = round(MAX_BURST_SEC * SAMPLE_RATE / VAD_SAMPLES)

        speech = 0
        silence = 0
        cooldown = 0.0

        while self._running.is_set():
            try:
                chunk = self._frames.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._paused.is_set():
                window.clear()
                window_samples = speech = silence = 0
                continue

            window.append(chunk)
            window_samples += len(chunk)
            while window_samples > max_window:
                window_samples -= len(window.pop(0))

            fire = False
            for voiced in self._speech_flags(chunk):
                if voiced:
                    speech += 1
                    silence = 0
                elif speech:
                    silence += 1
                if speech >= min_burst and (silence >= hangover or speech >= max_burst):
                    speech = silence = 0
                    fire = True
                elif silence >= hangover:
                    speech = silence = 0  # Too short to be the phrase.

            if cooldown > 0:
                cooldown = max(cooldown - len(chunk) / SAMPLE_RATE, 0.0)
                continue
            if not fire:
                continue

            audio = np.concatenate(window) if window else np.zeros(0, dtype=np.float32)
            if self._heard(audio):
                cooldown = self.cooldown_sec
                window.clear()
                window_samples = 0
                log.info("wake word detected (%s)", self.phrase)
                try:
                    self.on_detect()
                except Exception:  # noqa: BLE001
                    log.exception("wake-word callback failed")

    def _heard(self, audio: np.ndarray) -> bool:
        if audio.size == 0:
            return False
        try:
            text = self._transcriber.transcribe(audio)
        except Exception:  # noqa: BLE001 - never let a bad decode kill the listener
            log.exception("wake-word transcription failed")
            return False
        if not text:
            return False
        log.debug("wake-word candidate: %r", text)
        return matches_phrase(text, self.phrase, self.aliases, self.threshold)
