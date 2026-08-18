"""Live config reload.

`App.reload_config` is the single apply path for a settings change — the tray item and any
settings UI both go through it — so these tests pin down what actually takes effect at runtime
and what is deliberately left for a restart. No UI, no microphone, no GPU.
"""

import pytest

from ghostwriter import app as app_module
from ghostwriter import config as config_module
from ghostwriter.endpoint import SilenceEndpointer


class FakeRecorder:
    def __init__(self):
        self.sample_rate = 16000
        self.device = None
        self.max_frames = 16000 * 300
        self.level = 0.0
        self.recording = False


class FakeOverlay:
    def __init__(self):
        self.styles = []
        self.states = []

    def apply_style(self, style):
        self.styles.append(style)

    def set_state(self, state, message=""):
        self.states.append((state, message))


class FakeHotkeys:
    def __init__(self):
        self.registered = []

    def reregister(self, hotkeys):
        self.registered.append(hotkeys)


class FakeTranscriber:
    def __init__(self):
        self.initial_prompt = None
        self.vad = True


class FakeWake:
    def __init__(self, **kwargs):
        self.phrase = kwargs.get("phrase", "hey ghost")
        self.aliases = []
        self.threshold = 0.8
        self.vad_threshold = 0.5
        self.cooldown_sec = 2.0
        self.device = None
        self.model_name = "hey_ghost"
        self.listening = True
        self.stopped = 0
        self.paused = 0
        self.resumed = 0

    def stop(self):
        self.stopped += 1
        self.listening = False

    def pause(self):
        self.paused += 1

    def resume(self):
        self.resumed += 1


BASE = """
[hotkeys]
push_to_talk = "right ctrl"
toggle = "ctrl+shift+d"

[endpoint]
silence_timeout_sec = 1.2
min_recording_sec = 4.0
lead_in_sec = 2.0

[model]
name = "large-v3-turbo"
vocabulary = ["kubectl"]

[audio]
device = ""
max_duration_sec = 300.0

[overlay]
accent = "#38bdf8"

[output]
sounds = true

[wakeword]
enabled = true
phrase = "hey ghost"
"""


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A minimally wired App: real config and endpointer, fakes for anything with hardware."""
    path = tmp_path / "config.toml"
    path.write_text(BASE, encoding="utf-8")

    application = app_module.App.__new__(app_module.App)
    application.cfg = config_module.load(path)
    application.sounds = True
    application.min_duration = 0.35
    application.recorder = FakeRecorder()
    application.overlay = FakeOverlay()
    application.hotkeys = FakeHotkeys()
    application.transcriber = FakeTranscriber()
    application.wake = FakeWake()
    application.endpointer = SilenceEndpointer(level_source=lambda: 0.0)

    # Rebuilding the wake listener would load a model and open the microphone.
    monkeypatch.setattr(app_module.App, "_build_wake", lambda self: FakeWake())
    monkeypatch.setattr(app_module.App, "start_listening", lambda self: None)
    return application


def rewrite(application, old, new):
    """Edit the config file in place and reload, returning the restart-required labels."""
    text = application.cfg.path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not found in the config under test"
    application.cfg.path.write_text(text.replace(old, new), encoding="utf-8")
    return application.reload_config()


# --- applied live ------------------------------------------------------------


def test_endpoint_values_apply_without_a_restart(app):
    assert rewrite(app, "min_recording_sec = 4.0", "min_recording_sec = 12.0") == []
    assert app.endpointer.min_recording == 12.0


def test_hotkeys_are_rebound(app):
    rewrite(app, 'push_to_talk = "right ctrl"', 'push_to_talk = "right alt"')
    assert app.hotkeys.registered[-1]["push_to_talk"] == "right alt"


def test_vocabulary_applies_live_even_though_the_model_does_not(app):
    deferred = rewrite(app, 'vocabulary = ["kubectl"]', 'vocabulary = ["kubectl", "stdout"]')
    assert deferred == []
    assert app.transcriber.initial_prompt == "kubectl, stdout"


def test_overlay_is_restyled(app):
    rewrite(app, 'accent = "#38bdf8"', 'accent = "#a855f7"')
    assert app.overlay.styles[-1].accent == "#a855f7"


def test_cached_scalars_are_refreshed(app):
    rewrite(app, "sounds = true", "sounds = false")
    assert app.sounds is False


def test_recorder_cap_follows_audio_max_duration(app):
    rewrite(app, "max_duration_sec = 300.0", "max_duration_sec = 60.0")
    assert app.recorder.max_frames == 60 * 16000


# --- deliberately deferred ---------------------------------------------------


def test_changing_the_model_is_reported_not_applied(app):
    before = app.transcriber
    deferred = rewrite(app, 'name = "large-v3-turbo"', 'name = "small.en"')
    assert deferred == ["dictation model"]
    assert app.transcriber is before, "the model must not be swapped under a running app"


def test_sample_rate_is_deferred(app):
    text = app.cfg.path.read_text(encoding="utf-8").replace(
        "[audio]", "[audio]\nsample_rate = 22050"
    )
    app.cfg.path.write_text(text, encoding="utf-8")
    assert app.reload_config() == ["sample rate"]


def test_an_unchanged_file_defers_nothing(app):
    assert app.reload_config() == []


# --- wake word ---------------------------------------------------------------


def test_wake_phrase_applies_without_rebuilding(app):
    original = app.wake
    rewrite(app, 'phrase = "hey ghost"', 'phrase = "hey writer"')
    assert app.wake is original, "a phrase change must not reload the wake model"
    assert app.wake.phrase == "hey writer"
    assert app.wake.model_name == "hey_writer"


def test_wake_model_change_rebuilds_the_listener(app):
    original = app.wake
    text = app.cfg.path.read_text(encoding="utf-8").replace(
        "[wakeword]", '[wakeword]\nmodel = "base.en"'
    )
    app.cfg.path.write_text(text, encoding="utf-8")
    app.reload_config()
    assert app.wake is not original
    assert original.stopped == 1


def test_disabling_the_wake_word_stops_and_drops_it(app):
    original = app.wake
    rewrite(app, "enabled = true", "enabled = false")
    assert app.wake is None
    assert original.stopped == 1


def test_enabling_the_wake_word_builds_one(app):
    rewrite(app, "enabled = true", "enabled = false")
    assert app.wake is None
    rewrite(app, "enabled = false", "enabled = true")
    assert app.wake is not None


def test_audio_device_change_cycles_an_active_listener(app, monkeypatch):
    monkeypatch.setattr(app_module, "resolve_device", lambda name: 7 if name else None)
    rewrite(app, 'device = ""', 'device = "Yeti"')
    assert app.recorder.device == 7
    assert app.wake.device == 7
    assert app.wake.paused == 1 and app.wake.resumed == 1


# --- tray entry point --------------------------------------------------------


def test_tray_reload_reports_success_on_the_pill(app):
    app.reload_from_tray()
    assert app.overlay.states[-1] == ("done", "Config reloaded")


def test_tray_reload_names_what_needs_a_restart(app):
    app.cfg.path.write_text(
        app.cfg.path.read_text(encoding="utf-8").replace(
            'name = "large-v3-turbo"', 'name = "small.en"'
        ),
        encoding="utf-8",
    )
    app.reload_from_tray()
    state, message = app.overlay.states[-1]
    assert state == "done"
    assert "dictation model" in message


def test_tray_reload_survives_a_broken_config(app):
    app.cfg.path.write_text("this is not [valid toml", encoding="utf-8")
    app.reload_from_tray()
    assert app.overlay.states[-1] == ("error", "Config reload failed")


# --- guards against phantom attributes ---------------------------------------
#
# _apply_* assigns by name. A typo would quietly create a new attribute instead of updating the
# real one, and a fake would never notice, so these check the names against the real classes.


def test_every_endpoint_key_lands_on_the_real_endpointer(app):
    fresh = SilenceEndpointer(level_source=lambda: 0.0)
    body = """
[endpoint]
silence_timeout_sec = 3.5
silence_threshold = 0.05
min_speech_sec = 0.9
lead_in_sec = 7.0
max_duration_sec = 45.0
min_recording_sec = 11.0
vad_threshold = 0.65
"""
    app.cfg.path.write_text(body, encoding="utf-8")
    app.reload_config()

    expected = {
        "silence_timeout": 3.5,
        "threshold": 0.05,
        "min_speech": 0.9,
        "lead_in": 7.0,
        "max_duration": 45.0,
        "min_recording": 11.0,
        "vad_threshold": 0.65,
    }
    for name, value in expected.items():
        assert hasattr(fresh, name), f"SilenceEndpointer has no attribute {name!r}"
        assert getattr(app.endpointer, name) == value, name


def test_wakeword_attribute_names_exist_on_the_real_listener():
    from ghostwriter.wakeword_whisper import WhisperWakeWordListener

    listener = WhisperWakeWordListener(on_detect=lambda: None)  # no model load until start()
    for name in ("phrase", "aliases", "threshold", "vad_threshold", "cooldown_sec",
                 "model_name", "device", "listening"):
        assert hasattr(listener, name), f"WhisperWakeWordListener has no attribute {name!r}"


def test_transcriber_reads_prompt_and_vad_per_call():
    # Reloading these by assignment only works because transcribe() reads them on every call
    # rather than snapshotting them at construction. If that ever changes, the vocabulary and
    # audio.vad settings would silently stop applying until a restart.
    import inspect

    from ghostwriter.transcribe import Transcriber

    source = inspect.getsource(Transcriber.transcribe)
    assert "self.initial_prompt" in source
    assert "self.vad" in source


def test_reload_applies_the_real_shipped_config(app):
    """The synthetic config above is minimal; this runs the same path over the real file.

    Catches a key name that exists in the tests but not in config.toml (or vice versa), and
    proves the shipped file survives a reload rather than only a hand-written subset.
    """
    real = config_module.default_config_path()
    if not real.exists():  # pragma: no cover - only if the repo layout moves
        pytest.skip("no config.toml in the repo")

    app.cfg.path.write_text(real.read_text(encoding="utf-8"), encoding="utf-8")
    deferred = app.reload_config()

    # Whatever the file happens to say, the live objects must now agree with it.
    assert app.endpointer.min_recording == app.cfg.get("endpoint.min_recording_sec")
    assert app.endpointer.silence_timeout == app.cfg.get("endpoint.silence_timeout_sec")
    assert app.endpointer.vad_threshold == app.cfg.get("endpoint.vad_threshold")
    assert app.overlay.styles[-1].accent == app.cfg.get("overlay.accent")
    assert app.sounds == app.cfg.get("output.sounds")
    assert app.hotkeys.registered[-1] == app.cfg.get("hotkeys")
    # The fixture starts from a different model name, so that one difference is expected.
    assert deferred in ([], ["dictation model"])
