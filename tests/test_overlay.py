"""Dragging the status pill. Creates a real Tk window but never shows it."""

from types import SimpleNamespace

import pytest

from ghostwriter import overlay as overlay_module
from ghostwriter.overlay import HEIGHT, WIDTH, Overlay

tk = pytest.importorskip("tkinter")


@pytest.fixture
def pill(monkeypatch, tmp_path):
    monkeypatch.setattr(overlay_module, "POSITION_FILE", tmp_path / "overlay_position.json")
    try:
        widget = Overlay(level_source=lambda: 0.0)
    except tk.TclError:  # pragma: no cover - no window station available
        pytest.skip("no display")
    widget.root.update_idletasks()
    yield widget
    widget.root.destroy()


def drag(pill, start, end):
    """Press at `start`, move to `end`, release — in screen coordinates."""
    offset_x, offset_y = 10, 10
    pill._drag_start(SimpleNamespace(x=offset_x, y=offset_y))
    pill._drag_move(
        SimpleNamespace(x=offset_x, y=offset_y, x_root=end[0], y_root=end[1])
    )
    pill.root.update_idletasks()
    pill._drag_end(SimpleNamespace())


def test_dragging_moves_the_window(pill):
    drag(pill, (0, 0), (400, 300))
    assert pill.position == (390, 290)
    assert pill.root.geometry().endswith("+390+290")


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


def test_the_canvas_is_actually_bound_to_the_drag_handlers(pill):
    bound = pill.canvas.bind()
    assert {"<Button-1>", "<B1-Motion>", "<ButtonRelease-1>"} <= set(bound)
