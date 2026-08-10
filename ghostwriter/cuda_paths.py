"""Makes the pip-installed CUDA runtime DLLs visible to CTranslate2.

The `nvidia-*-cu12` wheels drop their DLLs under `site-packages/nvidia/<lib>/bin`, which is
not on the Windows DLL search path. Without this, loading a CUDA model fails with
"Library cublas64_12.dll is not found or cannot be loaded".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_added = False


def ensure() -> list[Path]:
    """Register every bundled NVIDIA DLL directory. Safe to call more than once."""
    global _added
    if _added:
        return []
    _added = True

    roots = [Path(p) / "nvidia" for p in sys.path if p]
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for sub in sorted(root.iterdir()):
            for name in ("bin", "lib"):
                dll_dir = sub / name
                if dll_dir.is_dir() and any(dll_dir.glob("*.dll")):
                    os.add_dll_directory(str(dll_dir))
                    os.environ["PATH"] = f"{dll_dir}{os.pathsep}{os.environ.get('PATH', '')}"
                    found.append(dll_dir)
    return found
