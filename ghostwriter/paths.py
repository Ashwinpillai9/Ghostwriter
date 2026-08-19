"""Where things live, which depends on how Ghostwriter was started.

Two ways to run, and they disagree about almost every path:

- **From a source checkout** — `config.toml` sits next to the code and is the file the developer
  edits. Everything is where the repository put it.
- **From an installed build** — the program files are read-only-ish under `%LOCALAPPDATA%` and
  get replaced wholesale by the next update, so nothing the user owns may live among them.

Keeping that distinction in one module is deliberate. It is the seam the two builds are most
likely to drift across, and a path decided inline somewhere else is how "works on my machine"
starts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Ghostwriter"


def frozen() -> bool:
    """True when running from a PyInstaller build rather than a source checkout."""
    return bool(getattr(sys, "frozen", False))


def program_dir() -> Path:
    """The directory holding the executable. Read-only in spirit: an update replaces it."""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Where bundled data files ended up, which is not where the executable is.

    PyInstaller unpacks data into `_internal/` beside the executable and points `sys._MEIPASS`
    at it. Reading a shipped file relative to `sys.executable` therefore looks in the wrong
    directory — a mistake that only shows up in a built copy, never while running from source.
    """
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    return program_dir()


def data_dir() -> Path:
    """Per-user, and survives an update. Config and anything fetched at runtime live here."""
    if not frozen():
        # From source, keep everything in the checkout so a developer can see and edit it.
        return program_dir()
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / APP_NAME


def config_path() -> Path:
    return data_dir() / "config.toml"


def runtime_dir() -> Path:
    """Where the first-run bootstrap unpacks the CUDA runtime.

    Beside the config rather than beside the program files: it is ~2 GB fetched for this
    machine, and an update replacing the program directory must not throw it away.
    """
    return data_dir() / "runtime"


def launch_settings_command(config: Path) -> list[str]:
    """The command that opens the settings window in a second process.

    A frozen build has no `python -m`: `sys.executable` is `Ghostwriter.exe`, so the same
    executable is re-launched with a flag and dispatches on it in `app.main`.
    """
    if frozen():
        return [sys.executable, "--settings", str(config)]
    return [sys.executable, "-m", "ghostwriter.settings", str(config)]
