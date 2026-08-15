"""Recorder's live-audio tap, which the endpointer reads while a recording is in progress."""

import numpy as np

from ghostwriter.audio import Recorder


def filled(chunks, size=480):
    rec = Recorder(sample_rate=16000, device="")
    for value in chunks:
        rec._chunks.append(np.full(size, value, dtype=np.float32))
        rec._frames += size
    return rec


def test_nothing_recorded_yet_gives_an_empty_array():
    assert Recorder(sample_rate=16000, device="").recent(4096).size == 0


def test_recent_returns_the_tail_in_order():
    rec = filled([1.0, 2.0, 3.0])
    tail = rec.recent(480 * 2)
    assert len(tail) == 960
    # Oldest first: the 2.0 block precedes the 3.0 block.
    assert tail[0] == 2.0 and tail[-1] == 3.0


def test_asking_for_more_than_exists_returns_what_there_is():
    tail = filled([1.0]).recent(16000)
    assert len(tail) == 480


def test_the_tap_does_not_disturb_the_recording():
    rec = filled([1.0, 2.0])
    rec.recent(480)
    assert rec.stop().size == 960, "reading recent audio must not consume it"
