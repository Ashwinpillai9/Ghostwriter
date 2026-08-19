"""The settings window and the running application, end to end.

The whole architecture rests on one claim: the window writes `config.toml` and the app picks it
up, with no channel between them. These tests exercise exactly that seam — a write through the
bridge, then a reload through `App` — because it is the part that would fail silently.
"""

import pytest

from ghostwriter import app as app_module
from ghostwriter import config as config_module
from ghostwriter.endpoint import SilenceEndpointer
from ghostwriter.settings.bridge import Bridge
from ghostwriter.settings.store import ConfigStore
from ghostwriter.watcher import ConfigWatcher

from test_reload import FakeHotkeys, FakeOverlay, FakeRecorder, FakeTranscriber, FakeWake


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A settings bridge and an App, both pointed at the same real config.toml."""
    path = tmp_path / "config.toml"
    path.write_text(
        config_module.default_config_path().read_text(encoding="utf-8"), encoding="utf-8"
    )

    application = app_module.App.__new__(app_module.App)
    application.cfg = config_module.load(path)
    application.sounds = True
    application.min_duration = 0.35
    application.recorder = FakeRecorder()
    application.overlay = FakeOverlay()
    application.hotkeys = FakeHotkeys()
    application.transcriber = FakeTranscriber()
    application.wake = FakeWake()
    application.watcher = None
    application.endpointer = SilenceEndpointer(level_source=lambda: 0.0)
    monkeypatch.setattr(app_module.App, "_build_wake", lambda self: FakeWake())
    monkeypatch.setattr(app_module.App, "start_listening", lambda self: None)

    return Bridge(ConfigStore(path)), application


def comments(path):
    return [line for line in path.read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("#")]


# --- a change made in the window reaches the running app ---------------------


def test_an_edit_reaches_the_app_without_a_restart(wired):
    bridge, app = wired
    before = comments(bridge.store.path)

    assert bridge.set("endpoint.silence_timeout_sec", 2.4)["ok"]
    deferred = app.reload_config()

    assert deferred == [], "this setting applies live"
    assert app.endpointer.silence_timeout == 2.4
    assert comments(bridge.store.path) == before, "documentation must survive the round trip"


def test_the_overlay_is_restyled_by_a_window_edit(wired):
    bridge, app = wired
    bridge.set("overlay.accent", "#22c55e")
    app.reload_config()
    assert app.overlay.styles[-1].accent == "#22c55e"


def test_a_wave_colour_follows_the_accent_through_the_window(wired):
    from ghostwriter.style import wave_colors

    bridge, app = wired
    bridge.set("overlay.accent", "#ef4444")
    app.reload_config()
    halo, _core = wave_colors("#ef4444")
    assert app.overlay.styles[-1].wave.halos[0] == halo


def test_hotkeys_are_rebound_by_a_window_edit(wired):
    bridge, app = wired
    bridge.set("hotkeys.push_to_talk", "right alt")
    app.reload_config()
    assert app.hotkeys.registered[-1]["push_to_talk"] == "right alt"


def test_several_edits_commit_as_one_write(wired):
    bridge, app = wired
    result = bridge.set_many({
        "endpoint.min_recording_sec": 8.0,
        "wakeword.phrase": "hey writer",
        "output.sounds": False,
    })
    assert result["ok"] and len(result["changed"]) == 3
    app.reload_config()
    assert app.endpointer.min_recording == 8.0
    assert app.wake.phrase == "hey writer"
    assert app.sounds is False


# --- restart-required is honest ----------------------------------------------


def test_a_model_change_is_named_and_not_applied(wired):
    bridge, app = wired
    before = app.transcriber

    result = bridge.set("model.name", "small.en")
    assert result["restartRequired"] == ["model.name"]

    deferred = app.reload_config()
    assert deferred == ["dictation model"]
    assert app.transcriber is before, "the loaded model must keep working until a restart"


def test_vocabulary_applies_live_even_though_the_model_does_not(wired):
    bridge, app = wired
    assert bridge.set("model.vocabulary", ["kubectl", "stdout"])["restartRequired"] == []
    assert app.reload_config() == []
    assert app.transcriber.initial_prompt == "kubectl, stdout"


# --- the watcher closes the loop ---------------------------------------------


def test_a_window_save_is_noticed_by_the_watcher(wired):
    """The real mechanism: nothing calls the app; the file changing is the whole signal."""
    bridge, app = wired
    reloads = []
    watcher = ConfigWatcher(
        bridge.store.path, lambda: reloads.append(app.reload_config()), poll=0.05, settle=0.1
    )

    # A colour the shipped config certainly does not already have, so the write is real.
    assert bridge.set("overlay.accent", "#123456")["changed"] == ["overlay.accent"]
    for _ in range(6):
        watcher.check(0.05)

    assert reloads, "the watcher must notice a save made by the settings window"
    assert app.overlay.styles[-1].accent == "#123456"


# --- two editors, one file ---------------------------------------------------


def test_an_external_edit_is_not_clobbered_by_the_window(wired):
    bridge, app = wired
    # Someone edits config.toml in a text editor while the window is open...
    text = bridge.store.path.read_text(encoding="utf-8")
    bridge.store.path.write_text(
        text.replace('phrase = "hey ghost"', 'phrase = "hey typed-by-hand"'), encoding="utf-8"
    )
    # ...and then the window commits something unrelated.
    bridge.set("overlay.accent", "#38bdf8")

    app.reload_config()
    assert app.wake.phrase == "hey typed-by-hand", "the hand edit was overwritten"


def test_the_window_reflects_an_external_edit_on_reload(wired):
    bridge, _app = wired
    text = bridge.store.path.read_text(encoding="utf-8")
    bridge.store.path.write_text(
        text.replace('accent = "#a855f7"', 'accent = "#111111"')
            .replace('accent = "#38bdf8"', 'accent = "#111111"'),
        encoding="utf-8",
    )
    assert bridge.external_change() is True
    assert bridge.reload()["values"]["overlay.accent"] == "#111111"


# --- the window cannot break the app -----------------------------------------


def test_a_failed_launch_does_not_take_the_tray_down(tmp_path, monkeypatch):
    """A settings window that will not start must report, not raise into pystray."""
    application = app_module.App.__new__(app_module.App)
    application.cfg = config_module.load(tmp_path / "missing.toml")
    application.overlay = FakeOverlay()
    application._settings = None

    def explode(*_args, **_kwargs):
        raise OSError("no interpreter")

    monkeypatch.setattr(app_module.subprocess, "Popen", explode)
    application.open_settings()  # must not raise
    assert application.overlay.states[-1] == ("error", "Could not open settings")


def test_a_second_open_focuses_rather_than_launching_again(tmp_path, monkeypatch):
    application = app_module.App.__new__(app_module.App)
    application.cfg = config_module.load(tmp_path / "missing.toml")
    application.overlay = FakeOverlay()

    launches = []

    class FakeProcess:
        def poll(self):
            return None  # still running

    monkeypatch.setattr(
        app_module.subprocess, "Popen", lambda *a, **k: (launches.append(1), FakeProcess())[1]
    )
    focused = []
    monkeypatch.setattr(app_module.App, "_focus_settings", lambda self: focused.append(1))

    application._settings = None
    application.open_settings()
    application.open_settings()

    assert len(launches) == 1, "a second open must not start another process"
    assert focused == [1]
