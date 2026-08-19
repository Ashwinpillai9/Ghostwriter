"""Run the settings window standalone: `python -m ghostwriter.settings`.

Deliberately usable without Ghostwriter running. The window edits `config.toml` and nothing
else, so there is nothing for it to connect to — a change made while the app is closed simply
takes effect the next time it starts.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .window import open_window


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    open_window(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
