"""Config parsing for the overlay's look.

The point of every test here is the same: a mistake in config.toml costs one warning at
startup, never an exception inside the render loop.
"""

import pytest

from ghostwriter.config import Config
from ghostwriter.style import DEFAULT_ACCENT, OverlayStyle, WaveStyle, rgb


def style(**overlay) -> OverlayStyle:
    return OverlayStyle.from_config(Config({"overlay": overlay}))


def test_an_empty_config_gives_the_designed_defaults():
    built, default = style(), OverlayStyle()
    assert built.accent == default.accent
    assert built.colors == default.colors
    assert built.wave.intensity == default.wave.intensity
    assert built.wave.halos == default.wave.halos


def test_values_come_through():
    built = style(
        accent="#a855f7",
        frame_ms=33,
        colors={"done": "#00ff00"},
        wave={"wavelength": 40, "intensity": 0.5, "cores": ["#112233", "#445566"]},
    )
    assert built.accent == "#a855f7"
    assert built.frame_ms == 33
    assert built.colors["done"] == "#00ff00"
    assert built.wave.wavelength == 40
    assert built.wave.intensity == 0.5
    assert built.wave.cores == ((17, 34, 51), (68, 85, 102))


def test_untouched_colours_keep_their_defaults():
    built = style(colors={"done": "#00ff00"})
    assert built.colors["error"] == OverlayStyle().colors["error"]


@pytest.mark.parametrize("junk", ["", "not-a-colour", "#fff", None, 42, "#gggggg", []])
def test_a_junk_accent_falls_back(junk):
    assert style(accent=junk).accent == DEFAULT_ACCENT


@pytest.mark.parametrize(
    ("key", "junk"),
    [
        ("wavelength", "sixty"),
        ("wavelength", 0),  # below the floor
        ("wavelength", 9999),  # above the ceiling
        ("packet_px", "long"),
        ("sharpness", -2),
        ("damping", 0),
        ("intensity", -1),
        ("intensity", None),
        ("buffer_width", 4),
        ("speed_scale", "fast"),
        ("enabled", "yes"),  # a string is not a bool
    ],
)
def test_junk_wave_values_fall_back(key, junk):
    built = style(wave={key: junk})
    assert getattr(built.wave, key) == getattr(WaveStyle(), key)


def test_a_junk_colour_inside_a_list_falls_back_to_that_slot_only():
    # The good slots survive; only the unusable one is replaced, and it falls back to the
    # accent-derived crest colour rather than to a blue from the original design.
    built = style(wave={"halos": ["#000000", "nope", "#ffffff"]})
    assert built.wave.halos[0] == (0, 0, 0)
    assert built.wave.halos[1] == WaveStyle().halos[0]  # the bad one
    assert built.wave.halos[2] == (255, 255, 255)


def test_an_empty_colour_list_falls_back_rather_than_drawing_nothing():
    assert style(wave={"cores": []}).wave.cores == WaveStyle().cores


def test_derived_values_track_the_configured_ones():
    # end_ms and the crest speed are computed from duration_ms, so a configured duration has
    # to carry through to both or the wave gets cut off mid-screen.
    built = style(wave={"duration_ms": 1000})
    assert built.wave.end_ms == pytest.approx(1300)
    assert built.wave.speed(500) == pytest.approx(0.5)
    assert style(wave={"speed_scale": 2.0}).wave.speed(500) > built.wave.speed(500)


def test_recording_wears_the_accent_and_other_states_do_not():
    built = style(accent="#a855f7")
    assert built.color_for("recording") == "#a855f7"
    assert built.color_for("done") == built.colors["done"]
    assert built.color_for("nonsense") == built.colors["idle"]


def test_rgb_rejects_short_hex():
    with pytest.raises(ValueError):
        rgb("#fff")


# --- the wave follows the accent ---------------------------------------------
#
# These go through config.load() rather than the raw-dict helper above, because the bug they
# guard was in DEFAULTS: a default halos/cores list there meant cfg.get() never returned None,
# so the derivation never ran and a purple pill still threw a blue ripple.


def test_crest_colours_follow_the_accent_through_a_real_config(tmp_path):
    from ghostwriter import config as config_module
    from ghostwriter.style import wave_colors

    path = tmp_path / "config.toml"
    path.write_text('[overlay]\naccent = "#a855f7"\n', encoding="utf-8")
    built = OverlayStyle.from_config(config_module.load(path))

    halo, core = wave_colors("#a855f7")
    assert built.wave.halos[0] == halo
    assert built.wave.cores[0] == core


def test_defaults_do_not_shadow_the_derivation(tmp_path):
    from ghostwriter import config as config_module

    # An empty file must still leave halos/cores unset so from_config derives them.
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")
    cfg = config_module.load(path)
    assert cfg.get("overlay.wave.halos") is None
    assert cfg.get("overlay.wave.cores") is None


def test_an_explicit_palette_still_wins(tmp_path):
    from ghostwriter import config as config_module

    path = tmp_path / "config.toml"
    path.write_text(
        '[overlay]\naccent = "#a855f7"\n\n[overlay.wave]\nhalos = ["#000000"]\n',
        encoding="utf-8",
    )
    built = OverlayStyle.from_config(config_module.load(path))
    assert built.wave.halos[0] == (0, 0, 0), "an explicit colour must override the accent"


def test_derived_crests_read_as_dark_water_and_a_lit_edge():
    from ghostwriter.style import wave_colors

    for accent in ("#38bdf8", "#a855f7", "#ef4444", "#22c55e"):
        halo, core = wave_colors(accent)
        base = rgb(accent)
        assert sum(halo) < sum(base), f"{accent}: the halo must be deeper than the accent"
        assert sum(core) > sum(base), f"{accent}: the core must be lighter than the accent"
