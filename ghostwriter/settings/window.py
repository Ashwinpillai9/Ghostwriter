"""The settings window itself.

Runs in its own process. It renders through the operating system's webview — WebView2 on
Windows — so it does not carry a browser with it, and it does not share a thread with the
overlay's Tk loop, which owns the main thread of the application process and cannot share it
with a second event loop.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .. import config as config_module
from .bridge import Bridge
from .store import ConfigStore

log = logging.getLogger(__name__)

TITLE = "Ghostwriter Settings"
WIDTH, HEIGHT = 900, 640
MIN_SIZE = (760, 520)
BACKGROUND = "#141519"

UI_DIR = Path(__file__).resolve().parent / "ui"


def open_window(config_path: Path | None = None) -> None:
    """Open the settings window and block until it closes."""
    import webview

    # The window may be opened before Ghostwriter has ever run, so it cannot assume the file
    # is there — and an empty editor over a missing file would be a poor first impression.
    path = config_module.ensure_exists(config_path or config_module.default_config_path())
    bridge = Bridge(ConfigStore(path))

    webview.create_window(
        TITLE,
        str(UI_DIR / "index.html"),
        js_api=bridge,
        width=WIDTH,
        height=HEIGHT,
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
        # A standard OS title bar rather than the mockup's custom chrome: it brings snapping,
        # Alt-Tab and the system menu with it, none of which are worth reimplementing for a
        # window opened occasionally. See design.md.
        frameless=False,
        easy_drag=False,
    )
    log.info("settings window open on %s", path)
    webview.start()
