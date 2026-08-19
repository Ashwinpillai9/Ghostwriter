"""Measures a microphone and its room, and says whether dictation will stop on its own.

Records silence, then speech, and compares them the way `endpoint.py` does. Shared by
`scripts/mic_check.py` and the settings window's Mic tab so there is one implementation of
"is this room usable", rather than a script and a UI that can disagree.

Nothing here prints or draws. The caller decides how to report.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd

from .endpoint import VAD_SAMPLES

log = logging.getLogger(__name__)

RATE = 16000

# Verdicts, in the order they are checked.
FINE = "fine"
NOISY = "noisy"           # the room sits too close to speech for the current threshold
QUIET_SPEECH = "quiet"    # the threshold is above the speaker's voice
UNUSABLE = "unusable"     # nothing separates this room from speech


@dataclass
class RoomReport:
    """What a measurement found, and what to do about it."""

    quiet_median: float
    talking_median: float
    quiet_hit: float          # fraction of *silent* frames that read as speech
    talking_hit: float        # fraction of *spoken* frames that read as speech
    longest_quiet: float      # longest unbroken quiet stretch, in seconds
    needed_quiet: float       # how long a stretch has to be to end an utterance
    quiet_rms: float
    talking_rms: float
    verdict: str
    message: str
    suggestions: dict[str, float] = field(default_factory=dict)

    @property
    def headroom(self) -> float:
        """How many times louder speech is than the room. Below ~3 is uncomfortable."""
        if self.quiet_rms <= 0:
            return float("inf")
        return self.talking_rms / self.quiet_rms

    @property
    def ok(self) -> bool:
        return self.verdict == FINE


def record(seconds: float, device, on_tick: Callable[[int], None] | None = None) -> np.ndarray:
    """Capture `seconds` of audio, calling `on_tick` with the whole seconds remaining."""
    frames: list[np.ndarray] = []
    with sd.InputStream(
        samplerate=RATE, channels=1, dtype="float32", device=device, blocksize=VAD_SAMPLES,
        callback=lambda indata, *_: frames.append(indata[:, 0].copy()),
    ):
        remaining = int(seconds)
        while remaining > 0:
            if on_tick is not None:
                on_tick(remaining)
            time.sleep(1)
            remaining -= 1
        leftover = seconds - int(seconds)
        if leftover > 0:
            time.sleep(leftover)
    return np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)


def speech_probability(model, audio: np.ndarray) -> np.ndarray:
    usable = len(audio) - len(audio) % VAD_SAMPLES
    if usable < VAD_SAMPLES:
        return np.zeros(1)
    return np.asarray(model(audio[:usable], num_samples=VAD_SAMPLES)).reshape(-1)


def longest_run(mask: np.ndarray, seconds_each: float) -> float:
    """The longest unbroken run of True, in seconds."""
    best = run = 0
    for flag in mask:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best * seconds_each


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def analyse(
    quiet: np.ndarray,
    talking: np.ndarray,
    model,
    threshold: float,
    silence_timeout: float,
) -> RoomReport:
    """Turn two recordings into a verdict. Split from capture so it is testable without a mic."""
    frame_sec = VAD_SAMPLES / RATE
    quiet_scores = speech_probability(model, quiet)
    talking_scores = speech_probability(model, talking)

    report = RoomReport(
        quiet_median=float(np.median(quiet_scores)),
        talking_median=float(np.median(talking_scores)),
        quiet_hit=float((quiet_scores >= threshold).mean()),
        talking_hit=float((talking_scores >= threshold).mean()),
        longest_quiet=longest_run(quiet_scores < threshold, frame_sec),
        needed_quiet=silence_timeout,
        quiet_rms=rms(quiet),
        talking_rms=rms(talking),
        verdict=FINE,
        message="",
    )

    if report.longest_quiet >= silence_timeout and report.talking_hit > 0.4:
        report.verdict = FINE
        report.message = "Dictation will stop on its own when you stop talking."
        _suggest_gentler(report, quiet_scores, talking_scores, threshold, silence_timeout)
        return report

    if report.longest_quiet < silence_timeout:
        # The room never goes quiet enough for long enough. Look for a stricter threshold that
        # this room clears while the speaker still comfortably exceeds it.
        for candidate in [round(x, 2) for x in np.arange(threshold, 0.96, 0.05)]:
            clears = longest_run(quiet_scores < candidate, frame_sec) >= silence_timeout * 1.5
            if clears and float((talking_scores >= candidate).mean()) > 0.35:
                report.verdict = NOISY
                report.message = "This room is too noisy for the current sensitivity."
                report.suggestions = {"endpoint.vad_threshold": candidate}
                _suggest_fallback(report)
                return report
        report.verdict = UNUSABLE
        report.message = (
            "This room's background is too close to speech to separate reliably. "
            "Try a headset microphone, a quieter input, or the stop key."
        )
        return report

    report.verdict = QUIET_SPEECH
    report.message = "Your speech is scoring too low — the sensitivity is above your voice."
    lowered = max(0.05, round(report.talking_median - 0.15, 2))
    report.suggestions = {"endpoint.vad_threshold": lowered}
    _suggest_fallback(report)
    return report


def _suggest_gentler(report, quiet_scores, talking_scores, threshold, silence_timeout) -> None:
    """In a room that already works, offer a more sensitive setting if it still would.

    A quiet room can usually afford to listen harder, which means being cut off less often
    mid-sentence. Only offered when the room still clears the silence test with room to spare.
    """
    frame_sec = VAD_SAMPLES / RATE
    for candidate in [round(x, 2) for x in np.arange(threshold - 0.05, 0.14, -0.05)]:
        if candidate >= threshold:
            continue
        clears = longest_run(quiet_scores < candidate, frame_sec) >= silence_timeout * 2
        if clears and float((talking_scores >= candidate).mean()) > 0.5:
            report.suggestions = {"endpoint.vad_threshold": candidate}
            break
    _suggest_fallback(report)


def _suggest_fallback(report: RoomReport) -> None:
    """A loudness gate for the case where the speech model will not load.

    Placed a little above the room's own noise floor. Only a fallback: `endpoint.py` uses the
    speech model whenever it can, precisely because a fixed loudness threshold is unreliable on
    a microphone with automatic gain.
    """
    if report.quiet_rms <= 0:
        return
    suggested = round(min(report.quiet_rms * 2.5, max(report.talking_rms * 0.25, 0.002)), 4)
    if suggested > 0:
        report.suggestions["endpoint.silence_threshold"] = suggested


def measure(
    seconds: float = 6.0,
    device=None,
    threshold: float = 0.5,
    silence_timeout: float = 1.2,
    on_phase: Callable[[str, int], None] | None = None,
) -> RoomReport:
    """Record a silent room then a speaking one, and report.

    `on_phase("quiet"|"talking", seconds_remaining)` lets a caller show a countdown.
    """
    from faster_whisper.vad import get_vad_model

    model = get_vad_model()

    def tick(phase):
        return (lambda remaining: on_phase(phase, remaining)) if on_phase else None

    quiet = record(seconds, device, tick("quiet"))
    talking = record(seconds, device, tick("talking"))
    return analyse(quiet, talking, model, threshold, silence_timeout)
