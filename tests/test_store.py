"""The config store.

The point of this module is that `config.toml` survives being edited by a program. These tests
mostly assert absence of damage: comments still there, ordering unchanged, untouched lines
byte-identical. That is hard to eyeball and easy to regress, which is why it is pinned here.
"""

import os
from pathlib import Path

import pytest

from ghostwriter import config as config_module
from ghostwriter.settings.store import ConfigStore

SAMPLE = """\
# Ghostwriter configuration. Save this file and it applies straight away.

[hotkeys]
# Hold this to record; release to transcribe and paste.
push_to_talk = "right ctrl"
# Press once to start, press again to stop.
toggle = "ctrl+shift+d"

[overlay]
# Colour of the recording pill.
accent = "#38bdf8"
frame_ms = 16

[overlay.wave]
enabled = true
# Crest colours follow the accent when unset.
"""


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(SAMPLE, encoding="utf-8")
    return ConfigStore(path)


# --- reading -----------------------------------------------------------------


def test_reads_a_dotted_path(store):
    assert store.get("hotkeys.push_to_talk") == "right ctrl"
    assert store.get("overlay.frame_ms") == 16
    assert store.get("overlay.wave.enabled") is True


def test_a_missing_key_reads_as_the_given_default(store):
    assert store.get("overlay.nonexistent") is None
    assert store.get("overlay.nonexistent", "fallback") == "fallback"
    assert store.get("nope.nothing.here") is None


def test_has_distinguishes_unset_from_falsy(store):
    assert store.has("overlay.wave.enabled")
    assert not store.has("overlay.wave.halos")


def test_values_come_back_as_plain_python(store):
    # tomlkit returns str/int subclasses carrying formatting. Letting those escape means every
    # consumer has to know about them.
    accent = store.get("overlay.accent")
    assert type(accent) is str
    assert type(store.get("overlay.frame_ms")) is int
    assert type(store.get("overlay.wave.enabled")) is bool


def test_a_missing_file_reads_as_empty(tmp_path):
    store = ConfigStore(tmp_path / "absent.toml")
    assert store.get("anything") is None


# --- writing preserves the file ----------------------------------------------


def test_comments_survive_a_write(store):
    store.set("overlay.accent", "#a855f7")
    store.save()
    text = store.path.read_text(encoding="utf-8")
    assert "# Colour of the recording pill." in text
    assert "# Hold this to record; release to transcribe and paste." in text
    assert "# Crest colours follow the accent when unset." in text


def test_only_the_changed_line_differs(store):
    before = store.path.read_text(encoding="utf-8").splitlines()
    store.set("overlay.accent", "#a855f7")
    store.save()
    after = store.path.read_text(encoding="utf-8").splitlines()

    assert len(before) == len(after), "no lines added or removed"
    differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(differing) == 1, f"expected exactly one changed line, got {differing}"
    assert after[differing[0]].strip() == 'accent = "#a855f7"'


def test_section_and_key_ordering_is_unchanged(store):
    store.set("overlay.frame_ms", 33)
    store.save()
    text = store.path.read_text(encoding="utf-8")
    assert text.index("[hotkeys]") < text.index("[overlay]") < text.index("[overlay.wave]")
    assert text.index("push_to_talk") < text.index("toggle")


def test_writing_nothing_leaves_the_file_byte_identical(store):
    before = store.path.read_bytes()
    store.save()
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_line_endings_are_preserved(tmp_path, newline):
    # Saving must not convert the file's line endings. It stays valid TOML either way, but
    # rewriting every line turns a one-key edit into a whole-file diff.
    path = tmp_path / "config.toml"
    path.write_bytes(SAMPLE.replace("\n", newline.decode()).encode("utf-8"))

    store = ConfigStore(path)
    store.set("overlay.accent", "#a855f7")
    store.save()

    raw = path.read_bytes()
    assert raw.count(newline) == SAMPLE.count("\n")
    if newline == b"\n":
        assert b"\r\n" not in raw
    changed = [line for line in raw.split(newline) if b"accent" in line and b"#" in line]
    assert any(b"#a855f7" in line for line in changed)


# --- creating what is missing ------------------------------------------------


def test_setting_a_new_key_in_an_existing_section(store):
    store.set("overlay.hold_ms", 1400)
    store.save()
    assert ConfigStore(store.path).get("overlay.hold_ms") == 1400
    assert "# Colour of the recording pill." in store.path.read_text(encoding="utf-8")


def test_setting_a_key_in_a_section_that_does_not_exist(store):
    store.set("postprocess.remove_fillers", True)
    store.save()
    reloaded = ConfigStore(store.path)
    assert reloaded.get("postprocess.remove_fillers") is True
    assert "[postprocess]" in store.path.read_text(encoding="utf-8")


def test_setting_a_deeply_nested_missing_path(store):
    store.set("overlay.colors.idle", "#6b7280")
    store.save()
    assert ConfigStore(store.path).get("overlay.colors.idle") == "#6b7280"


def test_set_reports_whether_anything_changed(store):
    assert store.set("overlay.accent", "#a855f7") is True
    assert store.set("overlay.accent", "#a855f7") is False, "an identical value is not a change"
    assert store.set("overlay.brand_new", 1) is True


def test_an_empty_or_malformed_path_is_rejected(store):
    for bad in ("", "overlay.", ".accent", "a..b"):
        with pytest.raises(ValueError):
            store.set(bad, 1)


def test_setting_through_a_non_table_is_rejected(store):
    with pytest.raises(ValueError):
        store.set("overlay.accent.deeper", 1)


# --- unset -------------------------------------------------------------------


def test_unset_removes_a_key(store):
    assert store.unset("overlay.frame_ms") is True
    store.save()
    assert not ConfigStore(store.path).has("overlay.frame_ms")


def test_unsetting_something_absent_is_not_an_error(store):
    assert store.unset("overlay.never_existed") is False
    assert store.unset("nope.nothing") is False


# --- atomicity ---------------------------------------------------------------


def test_save_leaves_no_temporary_files_behind(store):
    store.set("overlay.accent", "#22c55e")
    store.save()
    strays = [p.name for p in store.path.parent.iterdir() if p.name != store.path.name]
    assert strays == [], f"temporary files left behind: {strays}"


def test_a_failed_save_leaves_the_original_intact(store, monkeypatch):
    before = store.path.read_bytes()
    store.set("overlay.accent", "#22c55e")

    def explode(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        store.save()

    assert store.path.read_bytes() == before, "a failed save must not damage the file"
    strays = [p.name for p in store.path.parent.iterdir() if p.name != store.path.name]
    assert strays == [], "a failed save must not leave a temporary file"


# --- external edits ----------------------------------------------------------


def test_an_untouched_file_is_not_reported_as_changed(store):
    assert store.changed_on_disk() is False


def test_our_own_save_does_not_count_as_an_external_change(store):
    store.set("overlay.accent", "#22c55e")
    store.save()
    assert store.changed_on_disk() is False


def test_an_edit_by_someone_else_is_detected(store):
    store.path.write_text(SAMPLE + '\nextra = "written by an editor"\n', encoding="utf-8")
    assert store.changed_on_disk() is True


def test_reloading_picks_up_an_external_edit(store):
    store.set("overlay.accent", "#000000")  # uncommitted, must be discarded by load()
    store.path.write_text(
        SAMPLE.replace('accent = "#38bdf8"', 'accent = "#ef4444"'), encoding="utf-8"
    )
    store.load()
    assert store.get("overlay.accent") == "#ef4444"
    assert store.changed_on_disk() is False


# --- against the real config -------------------------------------------------


def test_the_real_config_round_trips_untouched():
    """Load and save the repo's own config.toml and require it byte-identical.

    The synthetic sample above is a handful of sections. The real file has arrays, floats,
    nested tables, a dotted `[postprocess.replacements]` with quoted keys, and non-ASCII in its
    comments — the parts most likely to be mangled by a round trip.
    """
    real = config_module.default_config_path()
    if not real.exists():  # pragma: no cover - only if the repo layout moves
        pytest.skip("no config.toml in the repo")
    original = real.read_text(encoding="utf-8")
    assert ConfigStore(real).dumps() == original


def test_editing_the_real_config_changes_only_that_key(tmp_path):
    real = config_module.default_config_path()
    if not real.exists():  # pragma: no cover
        pytest.skip("no config.toml in the repo")
    copy = tmp_path / "config.toml"
    copy.write_text(real.read_text(encoding="utf-8"), encoding="utf-8")

    before = copy.read_text(encoding="utf-8").splitlines()
    store = ConfigStore(copy)
    store.set("endpoint.silence_timeout_sec", 2.5)
    store.save()
    after = copy.read_text(encoding="utf-8").splitlines()

    differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(differing) == 1
    assert "2.5" in after[differing[0]]
    # Every comment in the real file is documentation; none may be lost.
    assert sum(1 for line in after if line.lstrip().startswith("#")) == sum(
        1 for line in before if line.lstrip().startswith("#")
    )


def test_the_app_can_still_read_what_the_store_wrote(tmp_path):
    """The store's output has to satisfy the reader the application actually uses."""
    real = config_module.default_config_path()
    if not real.exists():  # pragma: no cover
        pytest.skip("no config.toml in the repo")
    copy = tmp_path / "config.toml"
    copy.write_text(real.read_text(encoding="utf-8"), encoding="utf-8")

    store = ConfigStore(copy)
    store.set("overlay.accent", "#a855f7")
    store.set("endpoint.min_recording_sec", 9.0)
    store.set("model.vocabulary", ["kubectl", "stdout"])
    store.save()

    cfg = config_module.load(copy)
    assert cfg.get("overlay.accent") == "#a855f7"
    assert cfg.get("endpoint.min_recording_sec") == 9.0
    assert cfg.get("model.vocabulary") == ["kubectl", "stdout"]
    # and a key nobody touched still reads
    assert cfg.get("hotkeys.push_to_talk") == "right ctrl"


def test_unsetting_a_key_restores_the_application_default(tmp_path):
    copy = tmp_path / "config.toml"
    copy.write_text('[overlay]\naccent = "#000000"\n', encoding="utf-8")
    store = ConfigStore(copy)
    store.unset("overlay.accent")
    store.save()
    assert config_module.load(copy).get("overlay.accent") == "#38bdf8"
