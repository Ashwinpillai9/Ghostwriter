"""The settings window: a visual editor for `config.toml`.

Runs as its own process. It writes the config file and nothing else — `ConfigWatcher` in the
running application notices the save and `App.reload_config` applies it, so there is no channel
between the two beyond the file. That also means the window works with the app closed.
"""

from __future__ import annotations

from .store import ConfigStore

__all__ = ["ConfigStore"]
