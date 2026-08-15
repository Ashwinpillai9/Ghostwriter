"""The activation wave's geometry and timing. Pure maths — no Tk, no window, no GPU."""

import pytest

from ghostwriter import wave

SIZE = (640, 360)
CENTER = (320, 180)


def test_reach_covers_the_farthest_corner():
    # From dead centre, every corner is the same distance away.
    assert wave.reach(CENTER, SIZE) == pytest.approx((320**2 + 180**2) ** 0.5 + 40)


def test_reach_grows_when_the_pill_sits_near_an_edge():
    # A pill in the corner needs a wave nearly twice as wide to clear the display.
    assert wave.reach((10, 10), SIZE) > wave.reach(CENTER, SIZE)


def test_nothing_is_drawn_before_the_wave_starts():
    assert wave.crests(0, CENTER, SIZE) == []


def test_nothing_is_left_after_the_wave_ends():
    assert wave.crests(wave.END_MS + 1, CENTER, SIZE) == []


def test_crests_enter_in_a_staggered_train():
    early = wave.crests(wave.STAGGER_MS + 10, CENTER, SIZE)
    later = wave.crests(wave.STAGGER_MS * 5, CENTER, SIZE)
    assert len(early) < len(later), "crests should keep joining the train"


def test_a_crest_expands_over_time():
    first = wave.crests(200, CENTER, SIZE)[0]
    later = wave.crests(600, CENTER, SIZE)[0]
    assert later[0] > first[0]


def test_the_leading_crest_reaches_the_far_corner():
    # Otherwise the wave visibly stops short of the screen edge.
    limit = wave.reach(CENTER, SIZE)
    widest = max(c[0] for c in wave.crests(wave.DURATION_MS - 30, CENTER, SIZE))
    assert widest >= limit * 0.45  # radius, so half of the full span


def test_crests_fade_out_rather_than_vanishing():
    late = wave.crests(wave.DURATION_MS - 20, CENTER, SIZE)
    assert late, "the first crest should still exist just before it expires"
    assert late[0][2] < 0.15


def test_the_flash_decays_to_nothing():
    assert wave.flash_at(0) > 0
    assert wave.flash_at(wave.FLASH_MS) == 0
    assert wave.flash_at(0) > wave.flash_at(wave.FLASH_MS / 2) > 0
