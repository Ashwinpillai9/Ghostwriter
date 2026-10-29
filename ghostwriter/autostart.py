"""Starting Ghostwriter when the user logs in.

A Task Scheduler logon task rather than a `Run` key or a Startup shortcut, because it fixes
something rather than merely launching the app. Windows does not deliver input to a
lower-privilege process, so a normally-launched Ghostwriter goes deaf whenever an elevated
window has focus — an admin terminal, Task Manager. A task registered with *highest
privileges* does not, so the hotkeys work everywhere.

The cost is one elevation prompt when auto-start is switched on, and that Ghostwriter then runs
elevated for the rest of the session.

**The state is never cached.** Every query asks Windows, because the user can delete the task in
Windows' own tools and a remembered preference would then be a lie. That is also why auto-start
is the one setting that does not live in `config.toml`: it is a property of the machine, and
`config.toml` is copied between machines and edited by hand.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import subprocess
import sys
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

TASK_NAME = "Ghostwriter"

_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_HIDE = 0
# Windows reports this from GetLastError when the user dismisses the UAC prompt itself, rather
# than the launched process failing.
_ERROR_CANCELLED = 1223
_INFINITE = 0xFFFFFFFF


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """Run schtasks without flashing a console window in the user's face.

    For a plain query, which needs no privilege. Creating or deleting the task goes through
    `_run_elevated` instead.
    """
    return subprocess.run(  # noqa: S603 - fixed executable, no shell
        ["schtasks", *args],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wt.HWND),
        ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR),
        ("lpDirectory", wt.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY),
        ("dwHotKey", wt.DWORD), ("hIconOrMonitor", wt.HANDLE), ("hProcess", wt.HANDLE),
    ]


class _ElevatedResult:
    """What a `ShellExecute("runas", ...)` launch can tell us — no pipes, so no captured text."""

    def __init__(self, declined: bool, returncode: int | None):
        self.declined = declined
        self.returncode = returncode


def _run_elevated(args: list[str]) -> _ElevatedResult:
    """Run schtasks with an administrator token, through Windows' own UAC prompt.

    `schtasks.exe` carries no manifest asking to be elevated, so a plain `subprocess.run` just
    inherits the settings window's ordinary token and is refused outright — the user never even
    sees a prompt to say yes to. `ShellExecuteExW` with the `"runas"` verb is what actually raises
    one, and `SEE_MASK_NOCLOSEPROCESS` is what lets us wait for it and read a real exit code
    instead of guessing from whether the call launched at all.
    """
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = "schtasks.exe"
    info.lpParameters = subprocess.list2cmdline(args)
    info.nShow = _SW_HIDE

    # ctypes.pointer rather than byref: the latter is a write-only argument optimisation that
    # tests cannot introspect or fake a write through.
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.pointer(info)):
        error = ctypes.windll.kernel32.GetLastError()
        return _ElevatedResult(declined=(error == _ERROR_CANCELLED), returncode=None)

    exit_code = wt.DWORD()
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, _INFINITE)
    ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.pointer(exit_code))
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return _ElevatedResult(declined=False, returncode=exit_code.value)


def available() -> bool:
    """Whether auto-start can be registered at all.

    False from a source checkout: the command would point at a `python.exe` inside a virtual
    environment that only exists on this machine, which is not something to write into the
    user's logon tasks. The settings window says so rather than offering a switch that would
    not work.
    """
    return paths.frozen() and sys.platform == "win32"


def reason_unavailable() -> str:
    if sys.platform != "win32":
        return "Auto-start is only implemented on Windows."
    if not paths.frozen():
        return "Auto-start is available in an installed build, not when running from source."
    return ""


def is_enabled() -> bool:
    """Whether Windows will actually start Ghostwriter at the next logon.

    Read from the system every time. If the user removes the task themselves, this reports
    false, because that is the truth.
    """
    if sys.platform != "win32":
        return False
    try:
        result = _run(["/query", "/tn", TASK_NAME])
    except OSError:  # schtasks missing; not a Windows install we can work with
        log.debug("schtasks unavailable", exc_info=True)
        return False
    return result.returncode == 0


def enable() -> tuple[bool, str]:
    """Register the logon task. Returns (succeeded, message).

    Never raises: a refused elevation is an ordinary answer, and failing to set up auto-start
    must not stop Ghostwriter running.
    """
    if not available():
        return False, reason_unavailable()

    target = f'"{sys.executable}"'
    try:
        result = _run_elevated([
            "/create", "/tn", TASK_NAME,
            "/tr", target,
            "/sc", "onlogon",
            "/rl", "highest",   # what makes hotkeys work over elevated windows
            "/f",               # replace an existing task rather than failing
        ])
    except OSError as exc:
        log.exception("could not run schtasks")
        return False, str(exc)

    if result.declined:
        return False, "Auto-start needs administrator permission, which was not granted."
    if result.returncode == 0:
        log.info("auto-start enabled")
        return True, ""
    log.warning("could not enable auto-start: schtasks exited %s", result.returncode)
    return False, "Windows refused to create the logon task."


def disable() -> tuple[bool, str]:
    """Remove the logon task. Succeeds quietly when there is nothing to remove."""
    if sys.platform != "win32":
        return False, reason_unavailable()
    if not is_enabled():
        return True, ""
    try:
        result = _run_elevated(["/delete", "/tn", TASK_NAME, "/f"])
    except OSError as exc:
        log.exception("could not run schtasks")
        return False, str(exc)

    if result.declined:
        return False, "Removing auto-start needs administrator permission."
    if result.returncode == 0:
        log.info("auto-start disabled")
        return True, ""
    return False, "Windows refused to remove the logon task."


def state() -> dict:
    """Everything a caller needs to render the control, in one call."""
    return {
        "available": available(),
        "enabled": is_enabled(),
        "reason": reason_unavailable(),
        "target": str(Path(sys.executable)) if available() else "",
    }
