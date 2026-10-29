"""`python -m ghostwriter`, and the entry point the frozen build is built from.

One executable serves both windows: `Ghostwriter.exe` starts the app, `Ghostwriter.exe
--settings` opens the settings window. A frozen build has no `python -m`, so the second window
cannot be reached by naming a module the way it is from source.
"""

from __future__ import annotations

import multiprocessing

# Absolute, not relative: PyInstaller runs this file as a top-level `__main__` rather than as
# part of the package, so `from .app import ...` raises "attempted relative import with no known
# parent package" — at launch, in the built copy only. The absolute form works both ways.
from ghostwriter.app import main

if __name__ == "__main__":
    # PyInstaller + multiprocessing: without this, any child process re-runs the bootloader and
    # starts a second copy of the application instead of the worker it was asked for.
    multiprocessing.freeze_support()
    raise SystemExit(main())
