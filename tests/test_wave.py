"""The activation wave's geometry and timing. Pure maths — no Tk, no window, no GPU."""

import pytest

from ghostwriter import wave
from ghostwriter.style import WaveStyle

SIZE = (640, 360)
CENTER = (320, 180)
STYLE = WaveStyle()


def test_reach_covers_the_farthest_corner():
    # From dead centre, every corner is the same distance away.
    assert wave.reach(CENTER, SIZE, STYLE) == pytest.approx((320**2 + 180**2) ** 0.5 + 40)


def test_reach_grows_when_the_pill_sits_near_an_edge():
    # A pill in the corner needs a wave nearly twice as wide to clear the display.
    assert wave.reach((10, 10), SIZE, STYLE) > wave.reach(CENTER, SIZE, STYLE)


def test_nothing_is_drawn_before_the_wave_starts():
    assert wave.crests(0, CENTER, SIZE, STYLE) == []


def test_nothing_is_left_after_the_wave_ends():
    assert wave.crests(STYLE.end_ms + 1, CENTER, SIZE, STYLE) == []


def test_crests_enter_in_a_staggered_train():
    early = wave.crests(STYLE.stagger_ms + 10, CENTER, SIZE, STYLE)
    later = wave.crests(STYLE.stagger_ms * 5, CENTER, SIZE, STYLE)
    assert len(early) < len(later), "crests should keep joining the train"


def test_a_crest_expands_over_time():
    first = wave.crests(200, CENTER, SIZE, STYLE)[0]
    later = wave.crests(600, CENTER, SIZE, STYLE)[0]
    assert later[0] > first[0]


def test_the_leading_crest_reaches_the_far_corner():
    # The regression this guards: the design's `size` is a diameter, and halving it a second
    # time on the way to a radius left every crest stopping halfway to the edge.
    limit = wave.reach(CENTER, SIZE, STYLE)
    widest = max(c[0] for c in wave.crests(STYLE.duration_ms - 30, CENTER, SIZE, STYLE))
    assert widest >= limit * 0.95


def test_crests_fade_out_rather_than_vanishing():
    late = wave.crests(STYLE.duration_ms - 20, CENTER, SIZE, STYLE)
    assert late, "the first crest should still exist just before it expires"
    assert late[0][2] < 0.15


def test_the_flash_decays_to_nothing():
    assert wave.flash_at(0, STYLE) > 0
    assert wave.flash_at(STYLE.flash_ms, STYLE) == 0
    assert wave.flash_at(0, STYLE) > wave.flash_at(STYLE.flash_ms / 2, STYLE) > 0
