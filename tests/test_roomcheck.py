"""Room measurement.

`analyse` is pure — two arrays of audio and a speech model in, a verdict out — so the whole
decision is testable without a microphone. Only capture needs hardware, and that is one
function.
"""

import numpy as np
import pytest

from ghostwriter import roomcheck

RATE = roomcheck.RATE
FRAME = roomcheck.VAD_SAMPLES


def audio(seconds: float, amplitude: float) -> np.ndarray:
    """A block of noise at a given loudness."""
    rng = np.random.default_rng(0)
    return (rng.standard_normal(int(seconds * RATE)) * amplitude).astype(np.float32)


def model_scoring(quiet_score: float, talking_score: float):
    """A stand-in speech model: scores by how loud the audio is, so tests can script it."""

    def score(chunk, num_samples=FRAME):  # noqa: ARG001 - matches the real signature
        frames = len(chunk) // num_samples
        loud = float(np.sqrt(np.mean(chunk**2))) > 0.02
        return np.full(frames, talking_score if loud else quiet_score)

    return score


def test_a_quiet_room_with_clear_speech_is_fine():
    report = roomcheck.analyse(
        quiet=audio(6, 0.002),
        talking=audio(6, 0.08),
        model=model_scoring(0.02, 0.9),
        threshold=0.5,
        silence_timeout=1.2,
    )
    assert report.verdict == roomcheck.FINE
    assert report.ok
    assert report.headroom > 10


def test_a_noisy_room_is_diagnosed_and_a_stricter_threshold_suggested():
    # The room scores just above the threshold, so it never counts as quiet; speech scores
    # higher still, so a stricter setting separates them.
    report = roomcheck.analyse(
        quiet=audio(6, 0.002),
        talking=audio(6, 0.08),
        model=model_scoring(0.55, 0.95),
        threshold=0.5,
        silence_timeout=1.2,
    )
    assert report.verdict == roomcheck.NOISY
    assert not report.ok
    suggested = report.suggestions["endpoint.vad_threshold"]
    assert suggested > 0.55, "must clear the room's own noise"
    assert suggested < 0.95, "must stay below the speaker's voice"


def test_a_room_that_cannot_be_separated_says_so():
    # Room and speech score identically: no threshold can tell them apart.
    report = roomcheck.analyse(
        quiet=audio(6, 0.002),
        talking=audio(6, 0.08),
        model=model_scoring(0.99, 0.99),
        threshold=0.5,
        silence_timeout=1.2,
    )
    assert report.verdict == roomcheck.UNUSABLE
    assert "headset" in report.message or "quieter" in report.message
    assert "endpoint.vad_threshold" not in report.suggestions


def test_speech_below_the_threshold_is_diagnosed_separately():
    # The room is quiet enough, but the speaker never clears the bar.
    report = roomcheck.analyse(
        quiet=audio(6, 0.002),
        talking=audio(6, 0.08),
        model=model_scoring(0.01, 0.2),
        threshold=0.5,
        silence_timeout=1.2,
    )
    assert report.verdict == roomcheck.QUIET_SPEECH
    assert report.suggestions["endpoint.vad_threshold"] < 0.5


def test_a_fallback_loudness_gate_is_suggested_above_the_noise_floor():
    report = roomcheck.analyse(
        quiet=audio(6, 0.004),
        talking=audio(6, 0.09),
        model=model_scoring(0.02, 0.9),
        threshold=0.5,
        silence_timeout=1.2,
    )
    gate = report.suggestions.get("endpoint.silence_threshold")
    assert gate is not None
    assert gate > report.quiet_rms, "a gate below the room's own noise would never close"
    assert gate < report.talking_rms, "a gate above speech would never open"


def test_headroom_is_speech_over_room():
    report = roomcheck.analyse(
        quiet=audio(4, 0.01),
        talking=audio(4, 0.10),
        model=model_scoring(0.02, 0.9),
        threshold=0.5,
        silence_timeout=1.0,
    )
    assert report.headroom == pytest.approx(report.talking_rms / report.quiet_rms)
    assert 8 < report.headroom < 12


def test_silence_is_not_a_division_by_zero():
    report = roomcheck.analyse(
        quiet=np.zeros(RATE * 2, dtype=np.float32),
        talking=audio(2, 0.08),
        model=model_scoring(0.0, 0.9),
        threshold=0.5,
        silence_timeout=0.5,
    )
    assert report.headroom == float("inf")
    assert "endpoint.silence_threshold" not in report.suggestions


def test_longest_run_measures_unbroken_stretches():
    frame = 0.032
    assert roomcheck.longest_run(np.array([True] * 5), frame) == pytest.approx(5 * frame)
    assert roomcheck.longest_run(
        np.array([True, True, False, True, True, True]), frame
    ) == pytest.approx(3 * frame)
    assert roomcheck.longest_run(np.array([False, False]), frame) == 0


def test_rms_of_nothing_is_zero():
    assert roomcheck.rms(np.zeros(0, dtype=np.float32)) == 0.0


def test_too_little_audio_does_not_crash():
    tiny = np.zeros(10, dtype=np.float32)
    assert roomcheck.speech_probability(model_scoring(0.0, 0.0), tiny).size == 1
