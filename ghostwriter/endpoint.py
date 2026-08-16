"""Decides when a hands-free utterance has ended.

Used only for wake-word dictation — hold-to-talk already knows when you're done.

This asks a voice-activity detector whether the last fraction of a second contained speech,
rather than whether the microphone was loud. On a laptop mic array with automatic gain, an
empty room measures a median RMS of ~0.024 with peaks past 0.15, so a fixed loudness threshold
is either above the speech you want or below the noise you don't: at the old default of 0.012,
91% of *silent* frames counted as speech and the longest quiet stretch in eight seconds was
0.26s, against the 1.2s needed to stop. The utterance then ran until `max_duration_sec`.

Silero scores the same room at a median speech probability of 0.023 and finds the whole eight
seconds quiet. It already ships inside faster-whisper, so this costs no new dependency.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)

VAD_SAMPLES = 512  # Silero's fixed input size: 32ms at 16kHz.
# Silero is an LSTM and its hidden state is zeroed on every call, so the first frames of a
# window are scored without context and come out biased high — a silent room reads 0.8 through
# a 256ms window and 0.02 through a second of audio. Feed it a second, then judge only the
# most recent quarter of that, by which point the model has settled.
VAD_WINDOW = VAD_SAMPLES * 32
VAD_JUDGE = 8


class SilenceEndpointer:
    """Watches the recording and reports when the speaker has stopped."""

    def __init__(
        self,
        level_source: Callable[[], float],
        silence_timeout: float = 1.2,
        threshold: float = 0.012,
        min_speech: float = 0.4,
        lead_in: float = 2.0,
        max_duration: float = 60.0,
        min_recording: float = 4.0,
        audio_source: Callable[[int], np.ndarray] | None = None,
        vad_threshold: float = 0.5,
        sample_rate: int = 16000,
    ):
        self.level_source = level_source
        self.silence_timeout = silence_timeout
        self.threshold = threshold
        self.min_speech = min_speech
        # Grace period for the speaker to start talking after the wake word.
        self.lead_in = lead_in
        self.max_duration = max_duration
        # Floor under "silence" only: a pause early on, while you're mid-thought, shouldn't
        # end the recording just because it happened to be long enough. no_speech and
        # max_duration are unaffected — this only holds off ending an utterance that has
        # already started.
        self.min_recording = min_recording
        self.audio_source = audio_source
        self.vad_threshold = vad_threshold
        self.sample_rate = sample_rate
        self._vad = None
        self._vad_failed = False

    # --- speech detection -------------------------------------------------

    def _model(self):
        """Load Silero lazily, and only once. Falls back to loudness if it won't load."""
        if self._vad is None and not self._vad_failed:
            try:
                from faster_whisper.vad import get_vad_model

                self._vad = get_vad_model()
            except Exception:  # noqa: BLE001 - no VAD is survivable; a stuck recording is not
                log.warning("voice-activity model unavailable; endpointing on loudness")
                self._vad_failed = True
        return self._vad

    def speaking(self) -> bool:
        """True when the last fraction of a second sounded like speech."""
        if self.audio_source is not None:
            model = self._model()
            if model is not None:
                audio = self.audio_source(VAD_WINDOW)
                usable = len(audio) - len(audio) % VAD_SAMPLES
                if usable >= VAD_SAMPLES * VAD_JUDGE:
                    try:
                        scores = np.asarray(model(audio[-usable:], num_samples=VAD_SAMPLES))
                        recent = scores.reshape(-1)[-VAD_JUDGE:]
                        # Median, not max: speech is continuous, so it holds a majority of the
                        # window, while the stray frames a quiet room throws above the
                        # threshold — about 1% of them — never do.
                        return float(np.median(recent)) >= self.vad_threshold
                    except Exception:  # noqa: BLE001 - a bad frame must not strand the recording
                        log.debug("VAD failed on a frame", exc_info=True)
        return self.level_source() >= self.threshold

    # --- decision ---------------------------------------------------------

    def reason_to_stop(self, started: float, speech_seen: bool, last_voice: float) -> str | None:
        now = time.monotonic()
        if now - started >= self.max_duration:
            return "max_duration"
        if speech_seen:
            if now - started >= self.min_recording and now - last_voice >= self.silence_timeout:
                return "silence"
        elif now - started >= self.lead_in:
            return "no_speech"
        return None

    def wait(self, cancelled: Callable[[], bool], poll: float = 0.05) -> str:
        """Block until the utterance ends. Returns why it ended."""
        started = time.monotonic()
        last_voice = started
        speech_start: float | None = None
        speech_seen = False

        while True:
            if cancelled():
                return "cancelled"
            voice = self.speaking()
            now = time.monotonic()
            if voice:
                last_voice = now
                if speech_start is None:
                    speech_start = now
                elif not speech_seen and now - speech_start >= self.min_speech:
                    speech_seen = True
            elif (
                speech_start is not None
                and not speech_seen
                and now - last_voice >= self.silence_timeout
            ):
                # Real speech is not a continuous tone: stop consonants, breaths and the gaps
                # between words all read as momentary not-speech, even mid-sentence. Only give
                # up on this being the start of an utterance after a pause as long as the one
                # that would end an utterance already in progress — the same silence_timeout,
                # so "how long a pause counts as real" means one thing throughout.
                speech_start = None
            reason = self.reason_to_stop(started, speech_seen, last_voice)
            if reason:
                return reason
            time.sleep(poll)
