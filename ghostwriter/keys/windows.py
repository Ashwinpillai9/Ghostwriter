"""Windows keyboard backend: a low-level hook, key state, and synthetic input.

Replaces the `keyboard` package. The reason is Right Ctrl. That library matches bindings on
*scan codes*, and a real Right Ctrl press reports scan code 29 — identical to Left Ctrl, since
only the hook's extended-key flag separates them and the library folds that into `event.name`
rather than into the integer it matches on. So no scan-code spec could ever bind Right Ctrl
alone, and the previous implementation worked around it with a raw hook matched on the name
string.

`WH_KEYBOARD_LL` hands us `KBDLLHOOKSTRUCT.vkCode` directly, and that field *is* sided:
Right Ctrl arrives as `VK_RCONTROL` (163), Left Ctrl as `VK_LCONTROL` (162). Matching on it
makes the side distinction ordinary rather than a special case.

Two constraints this file is shaped by:

- **The hook callback must return fast.** Windows gives a low-level hook about 300 ms
  (`HKEY_CURRENT_USER\\Control Panel\\Desktop\\LowLevelHooksTimeout`) before it silently
  unhooks you, and a dead hook looks exactly like a broken keyboard. Callbacks here do
  comparisons only; anything slower belongs on another thread.
- **A hook belongs to the thread that set it, and that thread must pump messages.** Hence the
  dedicated daemon thread with a `GetMessageW` loop rather than installing from the caller.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from . import codes

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_QUIT = 0x0012
_DOWN_MESSAGES = (WM_KEYDOWN, WM_SYSKEYDOWN)

LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Stamped on everything we synthesise so our own hook can tell our keystrokes from the user's.
# Without it, the Ctrl+V we send to paste would be seen as a real keypress by our own binding.
SIGNATURE = 0x47484F53  # "GHOS"

# Keys that carry the extended-key flag. Sending Right Ctrl or an arrow without it produces the
# left-hand or numpad key instead.
_EXTENDED = frozenset(
    {
        codes.VK_RCONTROL, codes.VK_RMENU, codes.VK_UP, codes.VK_DOWN, codes.VK_LEFT,
        codes.VK_RIGHT, codes.VK_HOME, codes.VK_END, codes.VK_PRIOR, codes.VK_NEXT,
        codes.VK_INSERT, codes.VK_DELETE, codes.VK_LWIN, codes.VK_RWIN,
    }
)

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    # Never used, but it is the largest arm of the INPUT union and therefore what sets
    # sizeof(INPUT). Declaring it for real is what makes that size correct on both 32- and
    # 64-bit; a hand-guessed pad silently produced a 32-byte INPUT where Windows wants 40, and
    # SendInput then rejected every call with ERROR_INVALID_PARAMETER.
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


HOOKPROC = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD)
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = (wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = (wt.HHOOK,)
user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
user32.GetMessageW.restype = wt.BOOL
user32.PostThreadMessageW.argtypes = (wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM)


@dataclass(frozen=True)
class KeyEvent:
    """One keystroke as the low-level hook saw it."""

    vk: int
    scan: int
    down: bool
    extended: bool
    injected: bool

    def matches(self, name: str) -> bool:
        return codes.matches(self.vk, name)


def is_pressed(name: str) -> bool:
    """True while the key is physically held.

    A generic name is true for either side, because `GetAsyncKeyState(VK_CONTROL)` reports the
    state of both.
    """
    try:
        return bool(user32.GetAsyncKeyState(codes.vk(name)) & 0x8000)
    except codes.UnknownKey:
        return False


class Hook:
    """A low-level keyboard hook running on its own message-pumping thread.

    `callback(event) -> bool` returns True to let the keystroke reach the focused application
    and False to swallow it. It runs on the hook thread, so it must be quick — see the module
    docstring on the 300 ms timeout.
    """

    def __init__(self, callback: Callable[[KeyEvent], bool]):
        self.callback = callback
        self._handle = None
        self._thread_id = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        # Held so ctypes doesn't collect the trampoline while Windows still points at it.
        self._proc = HOOKPROC(self._dispatch)

    def _dispatch(self, code: int, wparam: int, lparam: int) -> int:
        if code < 0:
            return user32.CallNextHookEx(None, code, wparam, lparam)
        info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        # Our own synthetic keystrokes must never feed back into our bindings.
        if info.dwExtraInfo == SIGNATURE:
            return user32.CallNextHookEx(None, code, wparam, lparam)
        event = KeyEvent(
            vk=info.vkCode,
            scan=info.scanCode,
            down=wparam in _DOWN_MESSAGES,
            extended=bool(info.flags & LLKHF_EXTENDED),
            injected=bool(info.flags & LLKHF_INJECTED),
        )
        try:
            passthrough = self.callback(event)
        except Exception:  # noqa: BLE001 - a raising callback must not kill the hook
            log.exception("keyboard hook callback failed")
            passthrough = True
        if not passthrough:
            return 1  # Swallowed: the focused application never sees this key.
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="ghostwriter-hook")
        self._thread.start()
        if not self._ready.wait(5.0):
            log.warning("keyboard hook did not start within 5s")

    def _run(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        if not self._handle:
            log.error("SetWindowsHookExW failed (%s)", ctypes.get_last_error())
            self._ready.set()
            return
        self._ready.set()
        message = wt.MSG()
        # Blocks until PostThreadMessageW(WM_QUIT) arrives from stop(). The loop exists purely
        # to keep this thread pumping; the hook itself is called by Windows, not from here.
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def stop(self) -> None:
        if self._handle:
            user32.UnhookWindowsHookEx(self._handle)
            self._handle = None
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread_id = None
        self._thread = None
        self._ready.clear()


def _key_input(vk: int, up: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=SIGNATURE),
    )


def _char_inputs(char: str) -> list[INPUT]:
    """Down/up pair for one character, typed as Unicode rather than as a virtual key.

    KEYEVENTF_UNICODE bypasses the keyboard layout entirely, so text lands the same on a Dvorak
    or non-US layout. Characters outside the BMP need their two UTF-16 units sent in order.
    """
    out = []
    for code_unit in _utf16_units(char):
        for up in (False, True):
            flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
            out.append(
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(
                        wVk=0, wScan=code_unit, dwFlags=flags, time=0, dwExtraInfo=SIGNATURE
                    ),
                )
            )
    return out


def _utf16_units(char: str) -> list[int]:
    encoded = char.encode("utf-16-le")
    return [int.from_bytes(encoded[i : i + 2], "little") for i in range(0, len(encoded), 2)]


def _send(events: list[INPUT]) -> None:
    if not events:
        return
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        log.warning("SendInput sent %d of %d events (%s)", sent, len(events), ctypes.get_last_error())


def send(chord: str) -> None:
    """Press a chord and release it, modifiers outermost."""
    keys = [codes.vk(part) for part in codes.chord_parts(chord)]
    events = [_key_input(vk, up=False) for vk in keys]
    events += [_key_input(vk, up=True) for vk in reversed(keys)]
    _send(events)


def write(text: str) -> None:
    """Type text character by character as Unicode."""
    events: list[INPUT] = []
    for char in text:
        events.extend(_char_inputs(char))
    _send(events)


def release(name: str) -> None:
    """Force a key up, whether or not we pressed it."""
    try:
        target = codes.vk(name)
    except codes.UnknownKey:
        return
    # Release both sides for a generic modifier: the user may be holding either, and a stuck
    # Shift would corrupt the paste that follows.
    targets = {
        codes.VK_CONTROL: (codes.VK_CONTROL, codes.VK_LCONTROL, codes.VK_RCONTROL),
        codes.VK_SHIFT: (codes.VK_SHIFT, codes.VK_LSHIFT, codes.VK_RSHIFT),
        codes.VK_MENU: (codes.VK_MENU, codes.VK_LMENU, codes.VK_RMENU),
    }.get(target, (target,))
    _send([_key_input(vk, up=True) for vk in targets])
