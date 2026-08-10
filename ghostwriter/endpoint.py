"""Decides when a hands-free utterance has ended.

Used only for wake-word dictation — hold-to-talk already knows when you're done. Energy-based
rather than a neural VAD: the signal is just "has the mic been quiet for a while", and Whisper
re-runs its own VAD over the audio afterwards anyway.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class SilenceEndpointer:
    """Polls the recorder's RMS level and reports when the speaker has stopped."""

    def __init__(
        self,
        level_source: Callable[[], float],
        silence_timeout: float = 1.2,
        threshold: float = 0.012,
        min_speech: float = 0.4,
        lead_in: float = 2.0,
        max_duration: float = 60.0,
    ):
        self.level_source = level_source
        self.silence_timeout = silence_timeout
        self.threshold = threshold
        self.min_speech = min_speech
        # Grace period for the speaker to start talking after the wake word.
        self.lead_in = lead_in
        self.max_duration = max_duration

    def reason_to_stop(self, started: float, speech_seen: bool, last_voice: float) -> str | None:
        now = time.monotonic()
        if now - started >= self.max_duration:
            return "max_duration"
        if speech_seen:
            if now - last_voice >= self.silence_timeout:
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
            level = self.level_source()
            now = time.monotonic()
            if level >= self.threshold:
                last_voice = now
                if speech_start is None:
                    speech_start = now
                elif not speech_seen and now - speech_start >= self.min_speech:
                    speech_seen = True
            else:
                # A brief dip mid-word shouldn't count as the start of speech.
                if speech_start is not None and not speech_seen:
                    speech_start = None
            reason = self.reason_to_stop(started, speech_seen, last_voice)
            if reason:
                return reason
            time.sleep(poll)
