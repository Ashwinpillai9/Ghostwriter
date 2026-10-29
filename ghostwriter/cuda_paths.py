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


def _roots() -> list[Path]:
    """Every place the NVIDIA DLLs might be.

    `sys.path` covers a source install, where pip put them in site-packages. A frozen build has
    no site-packages: the runtime is fetched on first run into the per-user runtime directory,
    so that has to be searched too or GPU transcription silently never works in an installed
    copy.
    """
    roots = [Path(p) / "nvidia" for p in sys.path if p]
    try:
        from .paths import runtime_dir

        roots.insert(0, runtime_dir() / "nvidia")
    except Exception:  # noqa: BLE001 - paths unavailable is survivable; sys.path may still hit
        pass
    return roots


def ensure() -> list[Path]:
    """Register every NVIDIA DLL directory we can find. Safe to call more than once."""
    global _added
    if _added:
        return []
    _added = True

    roots = _roots()
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
