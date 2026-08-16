"""The activation ripple's geometry and timing. Pure maths — no Tk, no window, no GPU."""

import pytest

from ghostwriter import wave
from ghostwriter.style import WaveStyle

SIZE = (960, 540)
CENTER = (480, 389)
STYLE = WaveStyle()


def crest_radii(elapsed: float, style: WaveStyle = STYLE) -> list[float]:
    """Radii of the lit crests — the local maxima of the sampled ripple."""
    samples = wave.ripples(elapsed, CENTER, SIZE, style)
    return [
        samples[i][0]
        for i in range(1, len(samples) - 1)
        if samples[i][2] > samples[i - 1][2] and samples[i][2] >= samples[i + 1][2]
    ]


def test_reach_covers_the_farthest_corner():
    assert wave.reach(CENTER, SIZE, STYLE) == pytest.approx(
        (480**2 + 389**2) ** 0.5 + STYLE.overshoot
    )


def test_reach_grows_when_the_pill_sits_near_an_edge():
    assert wave.reach((10, 10), SIZE, STYLE) > wave.reach(CENTER, SIZE, STYLE)


def test_nothing_is_drawn_before_the_ripple_starts():
    assert wave.ripples(0, CENTER, SIZE, STYLE) == []


def test_nothing_is_left_after_the_ripple_ends():
    assert wave.ripples(STYLE.end_ms + 1, CENTER, SIZE, STYLE) == []


def test_crests_sit_one_wavelength_apart():
    # The whole point of the model: a droplet's ripples keep a constant spacing as they
    # travel. Rings that each ease outward independently bunch up instead, which reads as
    # concentric circles rather than as water.
    radii = crest_radii(1200)
    assert len(radii) >= 3, "several crests should be visible at once"
    gaps = [b - a for a, b in zip(radii, radii[1:])]
    for gap in gaps:
        # Peaks land on the radial sample grid, so they can only be located to within a step.
        assert gap == pytest.approx(STYLE.wavelength, abs=STYLE.sample_px * 2)


def test_the_wavelength_is_configurable():
    wide = WaveStyle(wavelength=110)
    radii = crest_radii(1200, wide)
    gaps = [b - a for a, b in zip(radii, radii[1:])]
    assert gaps, "a longer wavelength should still produce more than one crest"
    assert min(gaps) > STYLE.wavelength


def test_the_train_travels_outward_at_a_steady_speed():
    # Constant speed, not a decelerating ease — the deceleration is what made the old model
    # pile its rings up near the edge.
    fronts = [max(r[0] for r in wave.ripples(t, CENTER, SIZE, STYLE)) for t in (600, 900, 1200)]
    first, second = fronts[1] - fronts[0], fronts[2] - fronts[1]
    assert first == pytest.approx(second, rel=0.2)


def test_the_leading_crest_crosses_the_whole_screen():
    limit = wave.reach(CENTER, SIZE, STYLE)
    front = max(r[0] for r in wave.ripples(STYLE.duration_ms - 60, CENTER, SIZE, STYLE))
    assert front >= limit * 0.9


def test_there_is_dark_water_between_the_crests():
    # Only the positive lobe of the wave is lit, so troughs must drop out entirely.
    samples = wave.ripples(1000, CENTER, SIZE, STYLE)
    radii = [r[0] for r in samples]
    covered = max(radii) - min(radii)
    lit = len(samples) * STYLE.sample_px
    assert lit < covered * 0.75, "the crests should not fill the band they travel in"


def test_a_crest_dims_as_its_ring_grows():
    early = max(r[2] for r in wave.ripples(400, CENTER, SIZE, STYLE))
    late = max(r[2] for r in wave.ripples(1500, CENTER, SIZE, STYLE))
    assert late < early


def test_the_flash_decays_to_nothing():
    assert wave.flash_at(0, STYLE) > 0
    assert wave.flash_at(STYLE.flash_ms, STYLE) == 0
    assert wave.flash_at(0, STYLE) > wave.flash_at(STYLE.flash_ms / 2, STYLE) > 0


def test_a_disabled_flash_stays_dark():
    assert wave.flash_at(10, WaveStyle(flash_ms=0)) == 0
