"""Microphone capture. Records mono float32 at the model's sample rate."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd


def resolve_device(name_substring: str) -> int | None:
    """Map a partial device name to an index. None means the system default."""
    if not name_substring:
        return None
    needle = name_substring.lower()
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0 and needle in info["name"].lower():
            return index
    return None


class Recorder:
    """Push-to-talk recorder. start() opens the stream, stop() returns the audio."""

    def __init__(self, sample_rate: int = 16000, device: str = "", max_seconds: float = 300.0):
        self.sample_rate = sample_rate
        self.device = resolve_device(device)
        self.max_frames = int(max_seconds * sample_rate)
        self._chunks: list[np.ndarray] = []
        self._frames = 0
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self.level = 0.0  # Latest RMS, 0..1, for the overlay waveform.

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002 - sounddevice API
        block = indata[:, 0].copy()
        self.level = float(np.sqrt(np.mean(block**2)))
        with self._lock:
            if self._frames >= self.max_frames:
                return
            self._chunks.append(block)
            self._frames += frames

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._chunks = []
            self._frames = 0
        self.level = 0.0
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device,
            blocksize=int(self.sample_rate * 0.03),
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Close the stream and return everything captured since start()."""
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        self.level = 0.0
        with self._lock:
            chunks, self._chunks = self._chunks, []
            self._frames = 0
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32)

    def duration(self) -> float:
        with self._lock:
            return self._frames / self.sample_rate

    def recent(self, samples: int) -> np.ndarray:
        """The last `samples` frames captured so far, for anything watching the audio live.

        Returns fewer than asked for early in a recording, and an empty array before one
        starts. Copies, so the caller can hold it while recording continues.
        """
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            tail: list[np.ndarray] = []
            have = 0
            for chunk in reversed(self._chunks):
                tail.append(chunk)
                have += len(chunk)
                if have >= samples:
                    break
        audio = np.concatenate(list(reversed(tail))).astype(np.float32)
        return audio[-samples:] if len(audio) > samples else audio
