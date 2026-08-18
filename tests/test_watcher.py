"""The config file watcher.

`check(elapsed)` is driven directly rather than by sleeping, so the settle window is tested
deterministically instead of by racing a real clock.
"""

import pytest

from ghostwriter.watcher import ConfigWatcher, signature


@pytest.fixture
def watched(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("accent = 1\n", encoding="utf-8")
    fired = []
    watcher = ConfigWatcher(path, lambda: fired.append(1), poll=0.1, settle=0.4)
    return watcher, path, fired


def touch(path, text):
    """Rewrite the file with a distinct size so the change is unambiguous."""
    path.write_text(text, encoding="utf-8")


def test_an_untouched_file_never_fires(watched):
    watcher, _path, fired = watched
    for _ in range(20):
        assert watcher.check(0.1) is False
    assert fired == []


def test_a_save_fires_once_it_settles(watched):
    watcher, path, fired = watched
    touch(path, "accent = 22\n")

    assert watcher.check(0.1) is False, "first sighting only starts the settle window"
    assert fired == []
    watcher.check(0.1)
    watcher.check(0.1)
    assert fired == [], "still inside the settle window"
    watcher.check(0.2)  # now past settle=0.4
    assert fired == [1]


def test_it_fires_only_once_per_save(watched):
    watcher, path, fired = watched
    touch(path, "accent = 22\n")
    for _ in range(10):
        watcher.check(0.2)
    assert fired == [1], "a single save must not reload repeatedly"


def test_a_file_still_being_written_does_not_fire(watched):
    watcher, path, fired = watched
    # Each poll sees a different size: an editor mid-write, or one that autosaves per keystroke.
    for n in range(8):
        touch(path, "accent = " + "2" * (n + 1) + "\n")
        watcher.check(0.2)
    assert fired == [], "the settle window must swallow a file that keeps changing"

    # Once it holds still, it fires.
    watcher.check(0.2)
    watcher.check(0.3)
    assert fired == [1]


def test_a_second_save_fires_again(watched):
    watcher, path, fired = watched
    touch(path, "accent = 22\n")
    for _ in range(4):
        watcher.check(0.2)
    assert fired == [1]

    touch(path, "accent = 333\n")
    for _ in range(4):
        watcher.check(0.2)
    assert fired == [1, 1]


def test_a_missing_file_is_not_an_error(watched):
    # Some editors write to a temp file and rename over the original, so the path briefly
    # does not exist. That must not fire a reload or raise.
    watcher, path, fired = watched
    path.unlink()
    assert watcher.check(0.2) is False
    assert watcher.check(0.2) is False
    assert fired == []


def test_a_rename_over_the_original_still_fires(watched):
    watcher, path, fired = watched
    path.unlink()
    watcher.check(0.2)
    touch(path, "accent = 999\n")
    for _ in range(4):
        watcher.check(0.2)
    assert fired == [1]


def test_a_raising_callback_is_not_retried_every_poll(tmp_path):
    # A config with a syntax error should report once, not once a second until it is fixed.
    path = tmp_path / "config.toml"
    path.write_text("ok = 1\n", encoding="utf-8")
    calls = []

    def boom():
        calls.append(1)
        raise ValueError("bad toml")

    watcher = ConfigWatcher(path, boom, poll=0.1, settle=0.2)
    path.write_text("broken [\n", encoding="utf-8")
    with pytest.raises(ValueError):
        for _ in range(5):
            watcher.check(0.2)
    for _ in range(10):
        watcher.check(0.2)
    assert calls == [1], "a failing reload must not repeat until the file changes again"


def test_signature_reports_none_for_a_missing_file(tmp_path):
    assert signature(tmp_path / "nope.toml") is None


def test_signature_changes_when_the_content_does(tmp_path):
    # mtime alone can miss a rewrite inside a filesystem's timestamp resolution; pairing it
    # with size is what makes a same-instant edit visible.
    path = tmp_path / "config.toml"
    path.write_text("a = 1\n", encoding="utf-8")
    first = signature(path)
    path.write_text("a = 1000000\n", encoding="utf-8")
    second = signature(path)
    assert first is not None and second is not None
    assert first != second
    assert second[1] > first[1], "the size component tracks the file's real length"


def test_start_and_stop_are_idempotent(watched):
    watcher, _path, _fired = watched
    watcher.start()
    watcher.start()  # must not spawn a second thread
    watcher.stop()
    watcher.stop()
