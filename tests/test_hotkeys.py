import ghostwriter.hotkeys as hotkeys


def fake_pressed(held: set[str]):
    return lambda key: key in held


def test_trigger_key_is_last_component():
    assert hotkeys.trigger_key("ctrl+space") == "space"
    assert hotkeys.trigger_key("ctrl+shift+enter") == "enter"


def test_chord_matches_when_only_its_modifiers_are_held(monkeypatch):
    monkeypatch.setattr(hotkeys.keyboard, "is_pressed", fake_pressed({"ctrl", "space"}))
    assert hotkeys.exclusively_pressed("ctrl+space")


def test_extra_modifier_rejects_the_narrower_chord(monkeypatch):
    # Pressing ctrl+shift+space must not also fire the ctrl+space hotkey.
    monkeypatch.setattr(hotkeys.keyboard, "is_pressed", fake_pressed({"ctrl", "shift", "space"}))
    assert not hotkeys.exclusively_pressed("ctrl+space")
    assert hotkeys.exclusively_pressed("ctrl+shift+space")
