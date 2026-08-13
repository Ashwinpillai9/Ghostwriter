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
