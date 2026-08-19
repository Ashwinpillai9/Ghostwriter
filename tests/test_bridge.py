"""The settings window's Python API.

This is the whole surface the page can reach, so it is where "the UI cannot write somewhere
unexpected" has to be enforced and tested. No webview is started here — the bridge is a plain
object, which is most of the point of keeping it one.
"""

import pytest

from ghostwriter import config as config_module
from ghostwriter.settings.bridge import ALL_KEYS, EDITABLE, Bridge
from ghostwriter.settings.store import ConfigStore

SAMPLE = """\
[hotkeys]
# Hold to record.
push_to_talk = "right ctrl"

[overlay]
accent = "#38bdf8"

[model]
name = "large-v3-turbo"
"""


@pytest.fixture
def bridge(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(SAMPLE, encoding="utf-8")
    return Bridge(ConfigStore(path))


# --- reading -----------------------------------------------------------------


def test_load_reports_effective_values(bridge):
    data = bridge.load()
    # Present in the file...
    assert data["values"]["overlay.accent"] == "#38bdf8"
    # ...and absent from it, but still what the app would use.
    assert data["values"]["endpoint.silence_timeout_sec"] == 1.2
    assert data["values"]["postprocess.remove_fillers"] is True


def test_load_distinguishes_explicit_from_inherited(bridge):
    data = bridge.load()
    assert data["explicit"]["overlay.accent"] is True
    assert data["explicit"]["endpoint.silence_timeout_sec"] is False


def test_an_inherited_value_can_equal_the_default_and_still_be_explicit(tmp_path):
    # The distinction the UI needs: "#38bdf8 because I chose it" is not the same as
    # "#38bdf8 because nobody chose anything".
    path = tmp_path / "config.toml"
    path.write_text('[overlay]\naccent = "#38bdf8"\n', encoding="utf-8")
    explicit = Bridge(ConfigStore(path)).load()

    path.write_text("", encoding="utf-8")
    inherited = Bridge(ConfigStore(path)).load()

    assert explicit["values"]["overlay.accent"] == inherited["values"]["overlay.accent"]
    assert explicit["explicit"]["overlay.accent"] is True
    assert inherited["explicit"]["overlay.accent"] is False


def test_load_exposes_the_tab_groups_and_restart_keys(bridge):
    data = bridge.load()
    assert set(data["groups"]) == set(EDITABLE)
    assert "model.name" in data["restartOnly"]
    assert "overlay.accent" not in data["restartOnly"]


# --- writing -----------------------------------------------------------------


def test_set_writes_and_reports_the_change(bridge):
    result = bridge.set("overlay.accent", "#a855f7")
    assert result["ok"] is True
    assert result["changed"] == ["overlay.accent"]
    assert result["restartRequired"] == []
    assert config_module.load(bridge.store.path).get("overlay.accent") == "#a855f7"


def test_setting_an_unchanged_value_writes_nothing(bridge):
    before = bridge.store.path.read_bytes()
    result = bridge.set("overlay.accent", "#38bdf8")
    assert result["ok"] is True
    assert result["changed"] == []
    assert bridge.store.path.read_bytes() == before, "an identical value must not touch the file"


def test_a_restart_only_key_is_reported_as_such(bridge):
    result = bridge.set("model.name", "small.en")
    assert result["ok"] is True
    assert result["restartRequired"] == ["model.name"]


def test_set_many_saves_once_for_several_keys(bridge):
    result = bridge.set_many(
        {"overlay.accent": "#22c55e", "endpoint.silence_timeout_sec": 2.0}
    )
    assert result["ok"] is True
    assert set(result["changed"]) == {"overlay.accent", "endpoint.silence_timeout_sec"}
    cfg = config_module.load(bridge.store.path)
    assert cfg.get("overlay.accent") == "#22c55e"
    assert cfg.get("endpoint.silence_timeout_sec") == 2.0


def test_comments_survive_a_write_through_the_bridge(bridge):
    bridge.set("overlay.accent", "#a855f7")
    assert "# Hold to record." in bridge.store.path.read_text(encoding="utf-8")


# --- the page cannot write anywhere it likes ---------------------------------


def test_an_unknown_path_is_refused(bridge):
    before = bridge.store.path.read_bytes()
    result = bridge.set("something.invented", 1)
    assert result["ok"] is False
    assert "not editable" in result["error"]
    assert bridge.store.path.read_bytes() == before


def test_a_batch_containing_an_unknown_path_writes_nothing(bridge):
    # All-or-nothing: a typo in one key must not half-apply the rest.
    before = bridge.store.path.read_bytes()
    result = bridge.set_many({"overlay.accent": "#000000", "not.a.key": 1})
    assert result["ok"] is False
    assert bridge.store.path.read_bytes() == before


def test_keys_outside_the_declared_groups_are_not_writable(bridge):
    # audio.sample_rate is restart-only *and* structural; it is deliberately not editable here.
    assert "audio.sample_rate" not in ALL_KEYS
    assert bridge.set("audio.sample_rate", 22050)["ok"] is False


def test_every_editable_key_is_known_to_the_config_defaults(bridge):
    # A typo in EDITABLE would silently offer a key the application never reads.
    effective = config_module.load(bridge.store.path)
    sentinel = object()
    unknown = [key for key in ALL_KEYS if effective.get(key, sentinel) is sentinel]
    # Keys whose absence is meaningful have no default and are legitimately unset.
    allowed_missing = {"overlay.wave.halos", "overlay.wave.cores"}
    assert set(unknown) <= allowed_missing, f"unknown config keys offered: {unknown}"


# --- unset -------------------------------------------------------------------


def test_unset_returns_a_key_to_its_default(bridge):
    bridge.unset("overlay.accent")
    assert config_module.load(bridge.store.path).get("overlay.accent") == "#38bdf8"
    assert bridge.load()["explicit"]["overlay.accent"] is False


def test_unsetting_something_absent_is_harmless(bridge):
    assert bridge.unset("overlay.hold_ms") == {"ok": True, "changed": []}


def test_unsetting_an_unknown_key_is_refused(bridge):
    assert bridge.unset("not.a.key")["ok"] is False


# --- external edits ----------------------------------------------------------


def test_an_external_edit_is_detected(bridge):
    assert bridge.external_change() is False
    bridge.store.path.write_text(SAMPLE + '\nextra = "x"\n', encoding="utf-8")
    assert bridge.external_change() is True


def test_a_write_does_not_clobber_an_external_edit(bridge):
    # Someone edits config.toml in a text editor while the window is open, then the window
    # commits an unrelated key. Their edit must survive.
    bridge.store.path.write_text(
        SAMPLE.replace('name = "large-v3-turbo"', 'name = "small.en"'), encoding="utf-8"
    )
    bridge.set("overlay.accent", "#a855f7")

    cfg = config_module.load(bridge.store.path)
    assert cfg.get("model.name") == "small.en", "the external edit was overwritten"
    assert cfg.get("overlay.accent") == "#a855f7"


def test_reload_picks_up_external_values(bridge):
    bridge.store.path.write_text('[overlay]\naccent = "#ef4444"\n', encoding="utf-8")
    data = bridge.reload()
    assert data["values"]["overlay.accent"] == "#ef4444"
    assert bridge.external_change() is False
