import time

import numpy as np

from ghostwriter.endpoint import SilenceEndpointer


def make(levels, **kwargs):
    """Endpointer that reads a scripted sequence of RMS levels, one per poll."""
    seq = iter(levels)
    last = [0.0]

    def source():
        try:
            last[0] = next(seq)
        except StopIteration:
            pass
        return last[0]

    defaults = dict(silence_timeout=0.1, threshold=0.01, min_speech=0.02, lead_in=0.2)
    defaults.update(kwargs)
    return SilenceEndpointer(source, **defaults)


def test_stops_after_trailing_silence():
    # Loud for a while, then quiet past the timeout.
    ep = make([0.5] * 40 + [0.0] * 200)
    assert ep.wait(cancelled=lambda: False, poll=0.005) == "silence"


def test_gives_up_when_nobody_speaks():
    ep = make([0.0] * 500)
    assert ep.wait(cancelled=lambda: False, poll=0.005) == "no_speech"


def test_cancel_is_immediate():
    ep = make([0.5] * 500)
    assert ep.wait(cancelled=lambda: True, poll=0.005) == "cancelled"


def test_max_duration_caps_a_long_utterance():
    ep = make([0.5] * 5000, silence_timeout=99.0, max_duration=0.15)
    assert ep.wait(cancelled=lambda: False, poll=0.005) == "max_duration"


def test_brief_blip_does_not_count_as_speech():
    # One loud sample then silence: too short to be speech, so this is "no_speech", not "silence".
    ep = make([0.5] + [0.0] * 500)
    assert ep.wait(cancelled=lambda: False, poll=0.005) == "no_speech"


def test_reason_to_stop_waits_while_speech_is_recent():
    ep = make([], silence_timeout=1.0, lead_in=5.0)
    now = time.monotonic()
    assert ep.reason_to_stop(started=now, speech_seen=True, last_voice=now) is None


# --- voice-activity endpointing ---------------------------------------------
#
# The energy tests above still cover the fallback path. These cover the detector that actually
# decides, and the bug it was written for: a room whose background noise sits above any usable
# loudness threshold, where the old endpointer could never see silence and every hands-free
# utterance ran to max_duration.


class FakeVad:
    """Scores frames from a scripted list of probabilities, Silero's call signature."""

    def __init__(self, scores):
        self.scores = scores

    def __call__(self, audio, num_samples=512):
        frames = max(1, len(audio) // num_samples)
        return np.array(self.scores[-frames:], dtype=np.float32).reshape(-1, 1)


def vad_endpointer(scores, level=0.9, **kwargs):
    """Endpointer whose VAD is scripted and whose *loudness* is always above the threshold."""
    defaults = dict(silence_timeout=0.1, threshold=0.01, min_speech=0.02, lead_in=0.2)
    defaults.update(kwargs)
    ep = SilenceEndpointer(
        level_source=lambda: level,  # A noisy room: energy alone would never call this silent.
        audio_source=lambda n: np.zeros(n, dtype=np.float32),
        **defaults,
    )
    ep._vad = FakeVad(scores)
    return ep


def test_noise_above_the_loudness_threshold_is_not_speech():
    # The regression: a mic whose idle RMS sits above silence_threshold used to hold the
    # recording open until max_duration. The VAD sees the same room as quiet.
    ep = vad_endpointer([0.02] * 16)
    assert not ep.speaking()
    assert ep.wait(cancelled=lambda: False, poll=0.005) == "no_speech"


def test_speech_is_still_heard_over_that_noise():
    assert vad_endpointer([0.95] * 16).speaking()


def test_a_stray_loud_frame_does_not_count_as_speech():
    # Roughly 1% of frames spike in a quiet room. Taking the max of the window let a single
    # one hold the recording open; the median ignores it.
    scores = [0.02] * 15 + [0.99]
    assert not vad_endpointer(scores).speaking()


def test_the_loudness_gate_is_used_when_no_audio_source_is_given():
    ep = SilenceEndpointer(level_source=lambda: 0.5, threshold=0.01)
    assert ep.speaking()
    assert not SilenceEndpointer(level_source=lambda: 0.0, threshold=0.01).speaking()


def test_a_broken_vad_falls_back_to_loudness_rather_than_stranding_the_recording():
    class Broken:
        def __call__(self, *a, **k):
            raise RuntimeError("no")

    ep = vad_endpointer([0.9] * 16, level=0.5)
    ep._vad = Broken()
    assert ep.speaking(), "should fall back to the loud level, not raise"
