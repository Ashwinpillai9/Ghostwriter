import time

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
