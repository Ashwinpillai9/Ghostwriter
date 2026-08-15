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

    # min_recording defaults to 0 here (unlike the real 4s default) so tests that aren't about
    # that floor aren't all waiting on it; the dedicated tests further down set it explicitly.
    defaults = dict(
        silence_timeout=0.1, threshold=0.01, min_speech=0.02, lead_in=0.2, min_recording=0.0
    )
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


def test_a_natural_pause_mid_utterance_does_not_discard_it():
    # The regression: real speech dips below the voice threshold constantly — stop consonants,
    # breaths, the gap between words — and the old code reset the "have you started talking"
    # timer on any single such dip. Neither burst here reaches min_speech on its own; only
    # treating them as one utterance, because the gap between them is short, does.
    ep = make([0.5] * 3 + [0.0] * 3 + [0.5] * 3 + [0.0] * 40)
    assert ep.wait(cancelled=lambda: False, poll=0.005) == "silence"


def test_a_real_gap_still_resets_rather_than_accumulating_forever():
    # The other side of that fix: it must not become so lenient that two unrelated blips far
    # apart get stitched into one utterance. A gap as long as silence_timeout is treated as a
    # real pause, exactly as it would be to end an utterance already in progress.
    ep = make([0.5] * 3 + [0.0] * 40 + [0.5] * 3 + [0.0] * 400, lead_in=1.0)
    assert ep.wait(cancelled=lambda: False, poll=0.005) == "no_speech"


def test_reason_to_stop_waits_while_speech_is_recent():
    ep = make([], silence_timeout=1.0, lead_in=5.0)
    now = time.monotonic()
    assert ep.reason_to_stop(started=now, speech_seen=True, last_voice=now) is None


# --- the minimum-recording floor ---------------------------------------------
#
# "Say the wake word, then pause to think" is common and shouldn't be punished: a real pause
# early in a long thought must not end the recording just because it happened to run past
# silence_timeout. min_recording holds "silence" off — and only "silence" — until at least
# that much time has passed since recording began.


def test_a_pause_that_would_normally_end_it_is_held_off_until_min_recording():
    # Loud briefly (confirms speech), then quiet — long enough to trigger silence_timeout, but
    # short of min_recording. The old behaviour (no floor) would stop here; the floor must not
    # let it.
    ep = make([0.5] * 10 + [0.0] * 40, silence_timeout=0.1, min_recording=0.5)
    reason = ep.reason_to_stop(
        started=time.monotonic() - 0.3, speech_seen=True, last_voice=time.monotonic() - 0.2
    )
    assert reason is None


def test_silence_fires_once_min_recording_has_elapsed():
    ep = make([], min_recording=0.2)
    last_voice = time.monotonic() - 999  # long since anyone spoke
    reason = ep.reason_to_stop(
        started=time.monotonic() - 1.0, speech_seen=True, last_voice=last_voice
    )
    assert reason == "silence"


def test_min_recording_end_to_end_outlasts_an_early_pause():
    # A real run of wait(): speak briefly, go quiet well before min_recording elapses, and
    # confirm the utterance keeps running rather than ending on that first pause.
    ep = make(
        [0.5] * 6 + [0.0] * 400,
        silence_timeout=0.05,
        min_speech=0.02,
        min_recording=0.25,
        max_duration=2.0,
    )
    started = time.monotonic()
    reason = ep.wait(cancelled=lambda: False, poll=0.005)
    elapsed = time.monotonic() - started
    assert reason == "silence"
    assert elapsed >= 0.25, "must not end before min_recording has elapsed"


def test_min_recording_does_not_delay_no_speech():
    # Saying nothing at all is a different failure mode from pausing mid-thought — giving up
    # after lead_in must not wait on a floor meant for utterances that already started.
    ep = make([0.0] * 500, lead_in=0.05, min_recording=5.0)
    started = time.monotonic()
    reason = ep.wait(cancelled=lambda: False, poll=0.005)
    elapsed = time.monotonic() - started
    assert reason == "no_speech"
    assert elapsed < 1.0


def test_min_recording_never_overrides_max_duration():
    ep = make([0.5] * 5000, silence_timeout=99.0, max_duration=0.1, min_recording=10.0)
    assert ep.wait(cancelled=lambda: False, poll=0.005) == "max_duration"


def test_the_default_floor_is_four_seconds():
    ep = SilenceEndpointer(level_source=lambda: 0.0)
    assert ep.min_recording == 4.0


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
    # min_recording defaults to 0 here (unlike the real 4s default) so tests that aren't about
    # that floor aren't all waiting on it; the dedicated tests further down set it explicitly.
    defaults = dict(
        silence_timeout=0.1, threshold=0.01, min_speech=0.02, lead_in=0.2, min_recording=0.0
    )
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
