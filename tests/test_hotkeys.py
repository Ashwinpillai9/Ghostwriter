"""Hotkey dispatch, driven through the real virtual-key matching.

Events are built with genuine vk codes (`keys.vk`), so these tests exercise the same matching
the live hook does — only the hook installation and the physical key state are stubbed.
"""

import threading
import time

import pytest

import ghostwriter.hotkeys as hotkeys
from ghostwriter import keys


def event(name: str, down: bool = True) -> keys.KeyEvent:
    return keys.KeyEvent(vk=keys.vk(name), scan=0, down=down, extended=False, injected=False)


class FakeHook:
    """Captures the dispatch callback instead of installing a real Windows hook."""

    instances = []

    def __init__(self, callback):
        self.callback = callback
        self.started = False
        self.stopped = False
        FakeHook.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.fixture
def wired(monkeypatch):
    """Builds a manager over a fake hook, with controllable physical key state."""
    FakeHook.instances = []
    monkeypatch.setattr(hotkeys.keys, "Hook", FakeHook)
    held: set[str] = set()
    monkeypatch.setattr(hotkeys.keys, "is_pressed", lambda name: name in held)

    events = []

    def build(**config):
        manager = hotkeys.HotkeyManager(
            on_press=lambda mode: events.append(("press", mode)),
            on_release=lambda mode: events.append(("release", mode)),
            on_toggle=lambda: events.append(("toggle", None)),
            on_cancel=lambda: events.append(("cancel", None)),
        )
        manager.register({"push_to_talk": "right ctrl", "toggle": "ctrl+shift+d", **config})
        return manager, FakeHook.instances[-1].callback

    return build, held, events


def settle():
    """Callbacks run on their own threads so a slow one can't get the hook torn down."""
    time.sleep(0.05)


# --- key codes ---------------------------------------------------------------


def test_sided_ctrl_has_its_own_virtual_key():
    # The whole reason for matching on vk rather than scan code: these differ, scan codes don't.
    assert keys.vk("right ctrl") != keys.vk("left ctrl")
    assert keys.vk("right ctrl") == 0xA3


def test_generic_ctrl_matches_either_side_but_sided_does_not():
    assert keys.matches(keys.vk("left ctrl"), "ctrl")
    assert keys.matches(keys.vk("right ctrl"), "ctrl")
    assert keys.matches(keys.vk("right ctrl"), "right ctrl")
    assert not keys.matches(keys.vk("left ctrl"), "right ctrl")


def test_chord_parsing_and_trigger():
    assert keys.chord_parts("Ctrl+Shift+D") == ("ctrl", "shift", "d")
    assert keys.trigger("ctrl+shift+d") == "d"
    assert keys.trigger("right ctrl") == "right ctrl"


def test_unknown_key_is_rejected():
    with pytest.raises(keys.UnknownKey):
        keys.vk("nonsense key")


def test_sided_name_covers_its_generic_modifier():
    # Without this the default right-ctrl binding would see ctrl as an *extra* modifier held.
    assert "ctrl" in keys.covered_modifiers("right ctrl")
    # AltGr reports as ctrl+alt on layouts that have it.
    assert keys.covered_modifiers("right alt") >= {"alt", "ctrl"}


# --- exclusivity -------------------------------------------------------------


def test_extra_modifier_rejects_the_narrower_chord(monkeypatch):
    monkeypatch.setattr(hotkeys.keys, "is_pressed", lambda n: n in {"ctrl", "shift"})
    assert not hotkeys.exclusively_pressed("ctrl+space")
    assert hotkeys.exclusively_pressed("ctrl+shift+space")


def test_right_ctrl_tolerated_despite_holding_ctrl(monkeypatch):
    monkeypatch.setattr(hotkeys.keys, "is_pressed", lambda n: n in {"ctrl"})
    assert hotkeys.exclusively_pressed("right ctrl")


# --- the double-tap gate -----------------------------------------------------
#
# Right Ctrl is held for every Ctrl+C and Ctrl+V, so arming on the first press-down would start
# dictation on all of them. Only a second tap soon after the first tap's release counts.


def test_bare_ctrl_is_gated_but_a_chord_is_not():
    assert hotkeys.needs_double_tap("right ctrl")
    assert hotkeys.needs_double_tap("ctrl")
    assert not hotkeys.needs_double_tap("ctrl+shift+d")
    assert not hotkeys.needs_double_tap("right alt")


def test_single_tap_never_arms_and_is_never_suppressed(wired):
    build, _held, events = wired
    _manager, dispatch = build()

    assert dispatch(event("right ctrl", down=True)) is True
    assert dispatch(event("right ctrl", down=False)) is True
    settle()
    assert events == [], "a lone tap must never start dictation"


def test_double_tap_then_hold_arms_and_suppresses(wired):
    build, _held, events = wired
    _manager, dispatch = build()

    assert dispatch(event("right ctrl", down=True)) is True  # tap 1: untouched
    assert dispatch(event("right ctrl", down=False)) is True
    assert dispatch(event("right ctrl", down=True)) is False  # tap 2: arms, suppressed
    assert dispatch(event("right ctrl", down=False)) is False
    settle()
    assert events == [("press", "paste"), ("release", "paste")]


def test_second_tap_too_slow_does_not_arm(wired, monkeypatch):
    monkeypatch.setattr(hotkeys, "DOUBLE_TAP_WINDOW", 0.01)
    build, _held, events = wired
    _manager, dispatch = build()

    dispatch(event("right ctrl", down=True))
    dispatch(event("right ctrl", down=False))
    time.sleep(0.05)  # well past the (shrunk) window
    assert dispatch(event("right ctrl", down=True)) is True  # treated as a fresh tap 1
    settle()
    assert events == []


def test_a_fresh_double_tap_is_required_after_release(wired):
    build, _held, events = wired
    _manager, dispatch = build()

    for down in (True, False, True, False):
        dispatch(event("right ctrl", down=down))
    settle()
    assert events == [("press", "paste"), ("release", "paste")]

    # A single immediate tap must not re-arm on its own.
    assert dispatch(event("right ctrl", down=True)) is True
    settle()
    assert events == [("press", "paste"), ("release", "paste")]


def test_left_ctrl_never_triggers_a_right_ctrl_binding(wired):
    build, _held, events = wired
    _manager, dispatch = build()

    for down in (True, False, True, False):
        assert dispatch(event("left ctrl", down=down)) is True
    settle()
    assert events == []


def test_auto_repeat_does_not_re_fire_press(wired):
    build, _held, events = wired
    _manager, dispatch = build()

    dispatch(event("right ctrl", down=True))
    dispatch(event("right ctrl", down=False))
    dispatch(event("right ctrl", down=True))  # armed
    dispatch(event("right ctrl", down=True))  # auto-repeat
    dispatch(event("right ctrl", down=True))
    settle()
    assert events == [("press", "paste")], "auto-repeat must not look like a new press"


# --- suppression -------------------------------------------------------------


def test_suppress_false_passes_the_key_through(wired):
    build, _held, events = wired
    _manager, dispatch = build(suppress=False)

    dispatch(event("right ctrl", down=True))
    dispatch(event("right ctrl", down=False))
    assert dispatch(event("right ctrl", down=True)) is True  # arms, but not swallowed
    assert dispatch(event("right ctrl", down=False)) is True
    settle()
    assert events == [("press", "paste"), ("release", "paste")]


# --- toggle and cancel -------------------------------------------------------


def test_toggle_fires_only_with_its_modifiers_held(wired):
    build, held, events = wired
    _manager, dispatch = build()

    dispatch(event("d", down=True))  # no modifiers held
    settle()
    assert events == []

    held |= {"ctrl", "shift"}
    assert dispatch(event("d", down=True)) is False  # suppressed
    settle()
    assert events == [("toggle", None)]


def test_cancel_fires_but_always_reaches_the_app(wired):
    build, _held, events = wired
    _manager, dispatch = build(cancel="esc")

    # Esc must keep working normally everywhere else, so it is never swallowed.
    assert dispatch(event("esc", down=True)) is True
    settle()
    assert events == [("cancel", None)]


# --- transient bindings ------------------------------------------------------


def test_temporary_binding_fires_then_stops_after_removal(wired):
    build, _held, _events = wired
    manager, dispatch = build()
    fired = []

    token = manager.add_temporary("down", lambda: fired.append(1))
    assert dispatch(event("down", down=True)) is True  # never suppressed
    settle()
    assert fired == [1]

    manager.remove_temporary(token)
    dispatch(event("down", down=True))
    settle()
    assert fired == [1], "removed binding must stop firing"


def test_temporary_binding_survives_a_reregister(wired):
    # An utterance in flight keeps its stop key even if settings rewrite the chords underneath.
    build, _held, _events = wired
    manager, dispatch = build()
    fired = []

    manager.add_temporary("down", lambda: fired.append(1))
    manager.reregister({"push_to_talk": "right alt", "toggle": "ctrl+shift+d"})
    dispatch(event("down", down=True))
    settle()
    assert fired == [1]


# --- lifecycle ---------------------------------------------------------------


def test_unknown_chord_is_skipped_not_fatal(wired):
    build, _held, _events = wired
    manager, _dispatch = build(push_to_talk="nonsense key")
    assert all(b.chord != "nonsense key" for b in manager._bindings)


def test_unregister_stops_the_hook(wired):
    build, _held, _events = wired
    manager, _dispatch = build()
    manager.unregister()
    assert FakeHook.instances[-1].stopped
    assert manager._bindings == []


def test_reregister_swaps_chords_without_a_second_hook(wired):
    build, held, events = wired
    manager, dispatch = build()
    before = len(FakeHook.instances)

    manager.reregister({"push_to_talk": "right alt", "toggle": "ctrl+shift+d"})
    assert len(FakeHook.instances) == before, "the hook must be reused, not reinstalled"

    # The old binding is gone; the new one works. Right Alt is not gated, so one press is enough.
    for down in (True, False, True, False):
        dispatch(event("right ctrl", down=down))
    settle()
    assert events == []

    assert dispatch(event("right alt", down=True)) is False
    settle()
    assert events == [("press", "paste")]


def test_callbacks_run_off_the_hook_thread(wired):
    # Windows unhooks a low-level hook that takes ~300ms, so dispatch must not block on a
    # callback. A callback that blocks forever must still let the hook return.
    build, _held, _events = wired
    started = threading.Event()
    manager = hotkeys.HotkeyManager(
        on_press=lambda mode: (started.set(), time.sleep(5)),
        on_release=lambda mode: None,
        on_toggle=lambda: None,
        on_cancel=lambda: None,
    )
    manager.register({"push_to_talk": "right ctrl"})
    dispatch = FakeHook.instances[-1].callback

    dispatch(event("right ctrl", down=True))
    dispatch(event("right ctrl", down=False))
    begin = time.monotonic()
    dispatch(event("right ctrl", down=True))  # arms; callback blocks for 5s
    assert time.monotonic() - begin < 0.5, "dispatch must not wait for the callback"
    assert started.wait(1.0)
