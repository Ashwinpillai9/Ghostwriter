"""Dragging the status pill. Creates a real Tk window but never shows it."""

from types import SimpleNamespace

import pytest

from ghostwriter import overlay as overlay_module
from ghostwriter.overlay import HEIGHT, WIDTH, Overlay

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def _overlay():
    """One Overlay for the whole module.

    Building a Tk root re-sources the entire Tcl library from disk, and on this machine those
    reads intermittently fail under antivirus interception ("couldn't read file … No error").
    One root per test turned that into a flaky suite; one per module makes it rare and the run
    faster. The per-test fixture below resets the state a fresh instance would have had.
    """
    try:
        widget = Overlay(level_source=lambda: 0.0)
    except tk.TclError as exc:  # pragma: no cover - no window station, or Tcl unreadable
        pytest.skip(f"no display: {exc}")
    widget.root.update_idletasks()
    yield widget
    widget.shutdown()
    widget.root.destroy()


@pytest.fixture
def pill(_overlay, monkeypatch, tmp_path):
    monkeypatch.setattr(overlay_module, "POSITION_FILE", tmp_path / "overlay_position.json")
    _overlay.state = "idle"
    _overlay.message = ""
    _overlay.moving = False
    _overlay._drag_offset = None
    _overlay._dragged = False
    if _overlay.wave is not None:
        _overlay.wave.stop()
    _overlay._place()  # No saved file under tmp_path, so this lands on the default spot.
    return _overlay


def drag(pill, start, end):
    """Grab the pill 10px in from its corner, move to `end`, release.

    Event coordinates are relative to the window, which is larger than the pill, so the grab
    point has to be offset by the transparent padding around it.
    """
    grab_x, grab_y = overlay_module.PAD_X + 10, overlay_module.PAD_Y + 10
    pill._drag_start(SimpleNamespace(x=grab_x, y=grab_y))
    pill._drag_move(SimpleNamespace(x=grab_x, y=grab_y, x_root=end[0], y_root=end[1]))
    pill.root.update_idletasks()
    pill._drag_end(SimpleNamespace())


def test_dragging_moves_the_window(pill):
    drag(pill, (0, 0), (400, 300))
    assert pill.position == (390, 290)


def test_the_position_survives_a_restart(pill):
    # Only one Tk root can exist per process, so the restart is simulated by re-reading the
    # file the way a fresh Overlay would.
    drag(pill, (0, 0), (400, 300))
    assert pill._load_position() == (390, 290)


def test_a_drag_off_screen_is_clamped_back(pill):
    drag(pill, (0, 0), (99999, 99999))
    left, top, right, bottom = pill._virtual_bounds()
    x, y = pill.position
    assert left <= x <= right - WIDTH
    assert top <= y <= bottom - HEIGHT


def test_the_clamp_covers_every_monitor_not_just_the_primary(pill):
    left, top, right, _bottom = pill._virtual_bounds()
    if right - left <= pill.root.winfo_screenwidth():
        pytest.skip("single monitor")

    # Aim at the far edge of the virtual desktop rather than "just past the primary's width":
    # a DPI-scaled primary leaves a gap between the monitors that no cursor can occupy.
    drag(pill, (0, 0), (right - 20, top + 310))
    x, _y = pill.position
    assert x > pill.root.winfo_screenwidth(), (
        "the pill must be able to live on a second monitor, not just the primary"
    )
    assert pill._work_area(*pill.position) != pill._work_area(0, 0)


def test_a_clamped_position_lands_on_a_real_monitor(pill):
    # Monitors of different sizes leave gaps in the virtual rectangle; the pill must not sit
    # in one. _work_area resolves the nearest monitor, so the position it returns is on-screen.
    drag(pill, (0, 0), (99999, 99999))
    area = pill._work_area(*pill.position)
    if area is None:
        pytest.skip("no monitor API")
    left, top, right, bottom = area
    x, y = pill.position
    assert left <= x <= right - WIDTH
    assert top <= y <= bottom - HEIGHT


def test_a_corrupt_position_file_falls_back_to_the_default_spot(pill):
    overlay_module.POSITION_FILE.write_text("{not json", encoding="utf-8")
    pill._place()
    assert pill.position == pill._default_position()


def test_a_click_without_a_drag_saves_nothing(pill):
    pill._drag_start(SimpleNamespace(x=10, y=10))
    pill._drag_end(SimpleNamespace())
    assert not overlay_module.POSITION_FILE.exists()


def test_move_mode_keeps_the_pill_visible_until_you_let_go(pill):
    pill.start_move()
    pill._tick()
    assert pill.moving and pill.state == "moving"

    # A status update arriving mid-drag must not hide it.
    pill.set_state("idle")
    pill._tick()
    assert pill.state == "moving"

    drag(pill, (0, 0), (400, 300))
    pill._tick()
    assert not pill.moving and pill.state == "idle"


def test_the_accent_colours_recording_and_leaves_the_other_states_alone(pill):
    pill.accent = "#38bdf8"
    pill.state = "recording"
    assert pill.build_frame().color == "#38bdf8"
    # Amber still means "working", green "done", red "failed" — those carry meaning.
    for state, expected in (("transcribing", "#f59e0b"), ("done", "#22c55e"), ("error", "#ef4444")):
        pill.state = state
        assert pill.build_frame().color == expected





def test_the_wave_fills_whichever_monitor_the_pill_is_on(pill):
    if pill.wave is None:
        pytest.skip("no wave overlay")
    x, y = pill.position
    whole = pill._monitor_info(x, y, whole=True)
    work = pill._monitor_info(x, y)
    assert whole is not None
    # The wave covers the display edge to edge, unlike the work area the pill is clamped to.
    assert whole[3] >= work[3]

    pill._sync_wave("recording")
    assert pill.wave.playing
    assert pill.wave._monitor == whole
    # A square buffer on a wide display would stretch the crests into ovals.
    buffer_w, buffer_h = pill.wave._buffer_size
    assert buffer_w / buffer_h == pytest.approx(
        (whole[2] - whole[0]) / (whole[3] - whole[1]), rel=0.01
    )


def test_leaving_recording_pulls_the_wave(pill):
    if pill.wave is None:
        pytest.skip("no wave overlay")
    pill._sync_wave("recording")
    assert pill.wave.playing
    pill._sync_wave("idle")
    assert not pill.wave.playing


def test_the_wave_stops_itself_when_the_animation_expires(pill):
    if pill.wave is None:
        pytest.skip("no wave overlay")
    pill._sync_wave("recording")
    pill.wave.render(pill.style.wave.end_ms + 1)
    assert not pill.wave.playing, "a wave left playing would sit on screen forever"


def test_the_window_is_actually_bound_to_the_drag_handlers(pill):
    bound = pill.root.bind()
    assert {"<Button-1>", "<B1-Motion>", "<ButtonRelease-1>"} <= set(bound)


def test_dragging_moves_the_window_not_just_the_pill(pill):
    # The window is larger than the pill; geometry must place it PAD behind the pill so the
    # glow and wave have room without the pill drifting from where you dropped it.
    drag(pill, (0, 0), (500, 400))
    x, y = pill.position
    assert pill.root.geometry().endswith(f"+{x - overlay_module.PAD_X}+{y - overlay_module.PAD_Y}")


# --- live restyling ----------------------------------------------------------
#
# apply_style is called from whatever thread reloads the config, but the swap may destroy and
# rebuild the wave's Toplevel, so it has to land on the Tk thread. These drive the collection
# point directly rather than spinning the real loop.


def test_apply_style_does_nothing_until_the_tick_collects_it(pill):
    from ghostwriter.style import OverlayStyle

    pill.apply_style(OverlayStyle(accent="#a855f7"))
    assert pill.accent != "#a855f7", "the swap must wait for the Tk thread"
    pill._absorb_style()
    assert pill.accent == "#a855f7"
    assert pill.style.accent == "#a855f7"


def test_restyling_invalidates_the_warmed_chrome_plan(pill):
    from ghostwriter.style import OverlayStyle

    pill.warm(budget=1)
    assert pill._warm_todo is not None
    pill.apply_style(OverlayStyle(accent="#22c55e"))
    pill._absorb_style()
    assert pill._warm_todo is None, "cached chrome is keyed by colour, so it is now stale"


def test_disabling_the_wave_tears_its_window_down(pill):
    from ghostwriter.style import OverlayStyle, WaveStyle

    if pill.wave is None:
        pytest.skip("no wave overlay")
    pill.apply_style(OverlayStyle(wave=WaveStyle(enabled=False)))
    pill._absorb_style()
    assert pill.wave is None


def test_re_enabling_the_wave_builds_it_again(pill):
    from ghostwriter.style import OverlayStyle, WaveStyle

    pill.apply_style(OverlayStyle(wave=WaveStyle(enabled=False)))
    pill._absorb_style()
    assert pill.wave is None
    pill.apply_style(OverlayStyle(wave=WaveStyle(enabled=True)))
    pill._absorb_style()
    assert pill.wave is not None


def test_an_unchanged_wave_style_keeps_the_same_window(pill):
    if pill.wave is None:
        pytest.skip("no wave overlay")
    before = pill.wave
    pill.apply_style(overlay_module.OverlayStyle(accent="#ef4444"))
    pill._absorb_style()
    assert pill.wave is before, "only a wave change should rebuild the wave window"
