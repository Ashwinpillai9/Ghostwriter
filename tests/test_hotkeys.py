import threading

import keyboard as real_keyboard

import ghostwriter.hotkeys as hotkeys


def fake_pressed(held: set[str]):
    return lambda key: key in held


def test_trigger_key_is_last_component():
    assert hotkeys.trigger_key("ctrl+space") == "space"
    assert hotkeys.trigger_key("ctrl+shift+enter") == "enter"


def test_chord_matches_when_only_its_modifiers_are_held(monkeypatch):
    monkeypatch.setattr(hotkeys.keyboard, "is_pressed", fake_pressed({"ctrl", "space"}))
    assert hotkeys.exclusively_pressed("ctrl+space")


def test_right_alt_resolves_to_a_single_scan_code():
    # The name alone matches Left Alt as well, which suppress=True would then swallow.
    resolved = hotkeys.resolve_key("right alt")
    assert resolved == hotkeys.keyboard.key_to_scan_codes("right menu")[0]
    assert hotkeys.trigger_key("right alt") == resolved
    assert hotkeys.resolve_chord("right alt") == (resolved,)
    assert hotkeys.keyboard.parse_hotkey(hotkeys.resolve_chord("right alt")) == (((resolved,),),)


def test_ordinary_keys_pass_through_by_name():
    assert hotkeys.resolve_chord("ctrl+shift+d") == ("ctrl", "shift", "d")


# Right Ctrl cannot be matched through add_hotkey's scan codes at all: a real Right Ctrl press
# and a real Left Ctrl press report the identical scan code (29) on the low-level hook, verified
# directly with scripts/keyboard_probe.py. Only `event.name` tells them apart, so it is bound
# with a raw `keyboard.hook()` instead — these tests cover that path, not scan-code resolution.


def test_right_ctrl_hold_uses_a_raw_hook_not_add_hotkey(monkeypatch):
    fake = register_with(monkeypatch, push_to_talk="right ctrl")
    # Only the toggle goes through add_hotkey; push_to_talk must not, since any scan-code spec
    # for "right ctrl" would either miss real presses or also match Left Ctrl.
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == hotkeys.resolve_chord("ctrl+shift+d")
    assert len(fake.hooks) == 1
    (_callback, suppress) = fake.hooks[0]
    assert suppress


def test_right_ctrl_hook_ignores_events_for_other_keys(monkeypatch):
    fake = register_with(monkeypatch, push_to_talk="right ctrl")
    on_event = fake.hooks[0][0]
    event = FakeEvent(name="left ctrl", event_type=real_keyboard.KEY_DOWN)
    assert on_event(event) is True  # pass through untouched


def test_right_ctrl_hook_press_and_release_fire_by_name(monkeypatch):
    events = []
    done = threading.Event()

    def on_press(mode):
        events.append(("press", mode))

    def on_release(mode):
        events.append(("release", mode))
        done.set()

    fake = FakeKeyboard()
    monkeypatch.setattr(hotkeys, "keyboard", fake)
    manager = hotkeys.HotkeyManager(on_press, on_release, lambda: None, lambda: None)
    manager.register({"push_to_talk": "right ctrl", "toggle": "ctrl+shift+d"})
    on_event = fake.hooks[0][0]

    assert on_event(FakeEvent("right ctrl", real_keyboard.KEY_DOWN)) is False  # suppressed
    assert on_event(FakeEvent("right ctrl", real_keyboard.KEY_UP)) is False
    assert done.wait(1.0), "release callback never fired"
    assert ("press", "paste") in events
    assert ("release", "paste") in events


def test_right_ctrl_hook_respects_suppress_false(monkeypatch):
    fake = register_with(monkeypatch, push_to_talk="right ctrl", suppress=False)
    on_event = fake.hooks[0][0]
    assert on_event(FakeEvent("right ctrl", real_keyboard.KEY_DOWN)) is True
    assert on_event(FakeEvent("right ctrl", real_keyboard.KEY_UP)) is True


def test_right_alt_fires_even_though_it_holds_alt_down(monkeypatch):
    # The default binding: "alt" reads as pressed, but it is the chord itself, not an extra.
    monkeypatch.setattr(hotkeys.keyboard, "is_pressed", fake_pressed({"alt", "right alt"}))
    assert hotkeys.exclusively_pressed("right alt")


def test_right_alt_tolerates_altgr_reporting_ctrl(monkeypatch):
    monkeypatch.setattr(hotkeys.keyboard, "is_pressed", fake_pressed({"ctrl", "alt", "right alt"}))
    assert hotkeys.exclusively_pressed("right alt")


def test_right_alt_still_rejects_unrelated_modifiers(monkeypatch):
    monkeypatch.setattr(hotkeys.keyboard, "is_pressed", fake_pressed({"alt", "right alt", "shift"}))
    assert not hotkeys.exclusively_pressed("right alt")


def test_extra_modifier_rejects_the_narrower_chord(monkeypatch):
    # Pressing ctrl+shift+space must not also fire the ctrl+space hotkey.
    monkeypatch.setattr(hotkeys.keyboard, "is_pressed", fake_pressed({"ctrl", "shift", "space"}))
    assert not hotkeys.exclusively_pressed("ctrl+space")
    assert hotkeys.exclusively_pressed("ctrl+shift+space")


class FakeEvent:
    def __init__(self, name, event_type):
        self.name = name
        self.event_type = event_type


class FakeKeyboard:
    """Records how each binding was registered."""

    KEY_DOWN = real_keyboard.KEY_DOWN
    KEY_UP = real_keyboard.KEY_UP

    def __init__(self):
        self.calls = []
        self.hooks = []

    def add_hotkey(self, chord, callback, suppress=False):  # noqa: ARG002 - keyboard's API
        self.calls.append((chord, suppress))
        return object()

    def remove_hotkey(self, handle):
        pass

    def key_to_scan_codes(self, name):
        return real_keyboard.key_to_scan_codes(name)

    def is_pressed(self, name):  # noqa: ARG002 - keyboard's API
        return False

    def hook(self, callback, suppress=False):
        self.hooks.append((callback, suppress))
        return callback

    def unhook(self, handle):
        pass


def register_with(monkeypatch, **config):
    fake = FakeKeyboard()
    monkeypatch.setattr(hotkeys, "keyboard", fake)
    manager = hotkeys.HotkeyManager(lambda m: None, lambda m: None, lambda: None, lambda: None)
    manager.register({"push_to_talk": "right alt", "toggle": "ctrl+shift+d", **config})
    return fake


def test_bindings_are_suppressed_by_default(monkeypatch):
    assert all(suppress for _chord, suppress in register_with(monkeypatch).calls)


def test_suppression_can_be_turned_off(monkeypatch):
    # A suppressed key is invisible to every other program for as long as Ghostwriter runs, so
    # there has to be a way to hand it back without unbinding it.
    fake = register_with(monkeypatch, suppress=False)
    assert not any(suppress for _chord, suppress in fake.calls)
