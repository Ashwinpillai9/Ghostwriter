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

import logging
import subprocess
import sys
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

TASK_NAME = "Ghostwriter"

# Windows returns this from schtasks when the user dismisses the elevation prompt.
_ACCESS_DENIED = 740


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """Run schtasks without flashing a console window in the user's face."""
    return subprocess.run(  # noqa: S603 - fixed executable, no shell
        ["schtasks", *args],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )


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
        result = _run([
            "/create", "/tn", TASK_NAME,
            "/tr", target,
            "/sc", "onlogon",
            "/rl", "highest",   # what makes hotkeys work over elevated windows
            "/f",               # replace an existing task rather than failing
        ])
    except OSError as exc:
        log.exception("could not run schtasks")
        return False, str(exc)

    if result.returncode == 0:
        log.info("auto-start enabled")
        return True, ""

    message = (result.stderr or result.stdout or "").strip()
    if result.returncode == _ACCESS_DENIED or "denied" in message.lower():
        return False, "Auto-start needs administrator permission, which was not granted."
    log.warning("could not enable auto-start: %s", message)
    return False, message or "Windows refused to create the logon task."


def disable() -> tuple[bool, str]:
    """Remove the logon task. Succeeds quietly when there is nothing to remove."""
    if sys.platform != "win32":
        return False, reason_unavailable()
    if not is_enabled():
        return True, ""
    try:
        result = _run(["/delete", "/tn", TASK_NAME, "/f"])
    except OSError as exc:
        log.exception("could not run schtasks")
        return False, str(exc)

    if result.returncode == 0:
        log.info("auto-start disabled")
        return True, ""
    message = (result.stderr or result.stdout or "").strip()
    if result.returncode == _ACCESS_DENIED or "denied" in message.lower():
        return False, "Removing auto-start needs administrator permission."
    return False, message or "Windows refused to remove the logon task."


def state() -> dict:
    """Everything a caller needs to render the control, in one call."""
    return {
        "available": available(),
        "enabled": is_enabled(),
        "reason": reason_unavailable(),
        "target": str(Path(sys.executable)) if available() else "",
    }
