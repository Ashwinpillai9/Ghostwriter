"""Always-on-top status pill. Owns the Tk main loop, so it must live on the main thread.

Tk provides the window, the event loop and the input handling; it does not draw anything. The
pill's rounded ends, glow and bloom need antialiasing and a real alpha channel, which a Tk
canvas cannot produce, so each frame is composed with Pillow in `pill.py` and pushed to the
window through Win32's UpdateLayeredWindow. Transparent pixels of that surface are
click-through, so the padding around the pill never swallows a click meant for the app behind.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import logging
import queue
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

import math

from .pill import (
    BARS,
    COLORS,
    HEIGHT,
    LABELS,
    PAD_X,
    PAD_Y,
    SURFACE_H,
    SURFACE_W,
    WAVE_CRESTS,
    WAVE_MS,
    WAVE_REACH,
    WAVE_STAGGER,
    WIDTH,
    Frame,
)

log = logging.getLogger(__name__)

BOTTOM_MARGIN = 120
POSITION_FILE = Path(__file__).resolve().parent.parent / "overlay_position.json"

FRAME_MS = 16  # ~60fps, so the activation morph is smooth.
ACTIVATE_MS = 560.0  # Idle dot -> full waveform. The design's budget, matched exactly.
RINGS_MS = 1200.0  # Expanding rings outlive the morph slightly.
WAVE_END_MS = WAVE_MS + WAVE_CRESTS * WAVE_STAGGER  # Last crest clears the surface.

# Keeps the pill from taking focus away from the app you're dictating into, and marks it as a
# layered window so UpdateLayeredWindow can paint it.
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080
_ULW_ALPHA = 2
_AC_SRC_OVER, _AC_SRC_ALPHA = 0x00, 0x01

# Tk's winfo_screenwidth/height only ever describe the *primary* monitor, so clamping to them
# pins the pill to one display. These report the whole virtual desktop instead.
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_MONITOR_DEFAULTTONEAREST = 2


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte),
    ]


def ease_out(progress: float) -> float:
    """Cubic ease-out, the curve the design animates the activation morph on."""
    return 1 - (1 - progress) ** 3


class Overlay:
    def __init__(self, level_source: Callable[[], float]):
        self.level_source = level_source
        self.events: queue.Queue[tuple] = queue.Queue()
        self.state = "idle"
        self.message = ""
        self._levels = [0.0] * BARS
        self._state_at = time.monotonic()
        self.position = (0, 0)  # Set by _place once the root window exists.
        self.moving = False  # "Move overlay" mode: stay visible and ignore status updates.
        self._drag_offset: tuple[int, int] | None = None
        self._dragged = False
        self._hwnd = None
        self._dib = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{SURFACE_W}x{SURFACE_H}")

        self.root.bind("<Button-1>", self._drag_start)
        self.root.bind("<B1-Motion>", self._drag_move)
        self.root.bind("<ButtonRelease-1>", self._drag_end)
        self.root.configure(cursor="fleur")
        self._place()
        self._make_layered()
        self.root.after(FRAME_MS, self._tick)

    # --- position --------------------------------------------------------

    def _default_position(self) -> tuple[int, int]:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        return (screen_w - WIDTH) // 2, screen_h - HEIGHT - BOTTOM_MARGIN

    def _place(self, position: tuple[int, int] | None = None) -> None:
        """Move the pill, tracking the position ourselves.

        `winfo_x`/`winfo_y` keep reporting the old spot while the window is withdrawn, which
        is exactly when the pill spends most of its life, so they cannot be trusted here.
        `position` is the pill's own top-left; the window around it is larger, so that the
        glow and the activation rings have somewhere to go.
        """
        self.position = position or self._load_position() or self._default_position()
        x, y = self.position
        self.root.geometry(f"{SURFACE_W}x{SURFACE_H}+{x - PAD_X}+{y - PAD_Y}")

    def _virtual_bounds(self) -> tuple[int, int, int, int]:
        """The whole virtual desktop as (left, top, right, bottom).

        The origin is negative when a monitor sits left of or above the primary one, so this
        cannot be simplified to a width and a height.
        """
        try:
            metrics = ctypes.windll.user32.GetSystemMetrics
            left = metrics(_SM_XVIRTUALSCREEN)
            top = metrics(_SM_YVIRTUALSCREEN)
            width = metrics(_SM_CXVIRTUALSCREEN)
            height = metrics(_SM_CYVIRTUALSCREEN)
            if width > 0 and height > 0:
                return left, top, left + width, top + height
        except Exception:  # noqa: BLE001 - not Windows, or the call is unavailable
            pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _work_area(self, x: int, y: int) -> tuple[int, int, int, int] | None:
        """The usable area of the monitor nearest the pill's centre, excluding the taskbar."""
        try:
            user32 = ctypes.windll.user32
            point = _POINT(int(x + WIDTH / 2), int(y + HEIGHT / 2))
            handle = user32.MonitorFromPoint(point, _MONITOR_DEFAULTTONEAREST)
            if not handle:
                return None
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                return None
            work = info.rcWork
            return work.left, work.top, work.right, work.bottom
        except Exception:  # noqa: BLE001 - not Windows, or the call is unavailable
            return None

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        """Keep the pill reachable; a window dragged off-screen cannot be dragged back.

        Clamping happens against the monitor the pill is nearest, not the primary one, so it
        can be parked on any display. The virtual-desktop pass first is what makes the nearest
        monitor meaningful for a position flung far past every edge.
        """
        left, top, right, bottom = self._virtual_bounds()
        x = max(left, min(x, right - WIDTH))
        y = max(top, min(y, bottom - HEIGHT))

        area = self._work_area(x, y)
        if area is None:
            return x, y
        # Monitors of different heights leave gaps in the virtual rectangle; snapping into the
        # nearest monitor's work area keeps the pill out of them, and off the taskbar.
        left, top, right, bottom = area
        x = max(left, min(x, right - WIDTH))
        y = max(top, min(y, bottom - HEIGHT))
        return x, y

    def _load_position(self) -> tuple[int, int] | None:
        try:
            saved = json.loads(POSITION_FILE.read_text(encoding="utf-8"))
            return self._clamp(int(saved["x"]), int(saved["y"]))
        except FileNotFoundError:
            return None
        except Exception:  # noqa: BLE001 - a corrupt file just means "use the default spot"
            log.warning("ignoring unreadable %s", POSITION_FILE.name)
            return None

    def _save_position(self) -> None:
        x, y = self.position
        try:
            POSITION_FILE.write_text(json.dumps({"x": x, "y": y}), encoding="utf-8")
        except Exception:  # noqa: BLE001 - not worth interrupting dictation over
            log.warning("could not save overlay position")

    # --- dragging --------------------------------------------------------

    def _drag_start(self, event) -> None:
        # Offsets within the pill, so it doesn't jump to the cursor on the first move.
        self._drag_offset = (event.x - PAD_X, event.y - PAD_Y)
        self._dragged = False

    def _drag_move(self, event) -> None:
        if self._drag_offset is None:
            return
        offset_x, offset_y = self._drag_offset
        self._place(self._clamp(event.x_root - offset_x, event.y_root - offset_y))
        self._dragged = True

    def _drag_end(self, event) -> None:  # noqa: ARG002 - Tk passes the event
        if self._drag_offset is None:
            return
        self._drag_offset = None
        if self._dragged:
            self._save_position()
        # A click with no drag is how you leave move mode; a drag ends it too.
        if self.moving:
            self.moving = False
            self.set_state("idle")

    def start_move(self) -> None:
        """Show the pill so it can be dragged even when there is nothing to report."""
        self.moving = True
        self.set_state("moving", LABELS["moving"])

    # --- window style ----------------------------------------------------

    def _make_layered(self) -> None:
        try:
            self.root.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd,
                _GWL_EXSTYLE,
                style | _WS_EX_LAYERED | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW,
            )
            self._hwnd = hwnd
        except Exception:  # noqa: BLE001 - without this the pill still works, just plainer
            log.warning("could not make the overlay a layered window", exc_info=True)

    def _paint(self, image) -> None:
        """Hand one RGBA frame to the compositor, alpha channel and all."""
        if self._hwnd is None:
            return
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        # "BGRa" is Pillow's premultiplied BGRA, which is exactly what ULW_ALPHA expects;
        # straight alpha here shows up as a bright halo around every antialiased edge.
        data = image.tobytes("raw", "BGRa")

        screen_dc = user32.GetDC(0)
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = SURFACE_W
        info.bmiHeader.biHeight = -SURFACE_H  # Negative: top-down, matching Pillow's order.
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(
            memory_dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0
        )
        try:
            ctypes.memmove(bits, data, len(data))
            previous = gdi32.SelectObject(memory_dc, bitmap)
            blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)
            user32.UpdateLayeredWindow(
                self._hwnd,
                screen_dc,
                None,  # Position is Tk's business; only the pixels are ours.
                ctypes.byref(_SIZE(SURFACE_W, SURFACE_H)),
                memory_dc,
                ctypes.byref(_POINT(0, 0)),
                0,
                ctypes.byref(blend),
                _ULW_ALPHA,
            )
            gdi32.SelectObject(memory_dc, previous)
        finally:
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(0, screen_dc)

    # --- thread-safe API -------------------------------------------------

    def set_state(self, state: str, message: str = "") -> None:
        self.events.put((state, message))

    def quit(self) -> None:
        self.events.put(("__quit__", ""))

    # --- frame composition -----------------------------------------------

    def _elapsed_ms(self) -> float:
        return (time.monotonic() - self._state_at) * 1000

    def build_frame(self) -> Frame:
        """Translate the current state and its age into the design's `live` values."""
        elapsed = self._elapsed_ms()
        state = self.state
        # The design plays "activating" and then hands over to "recording". Here that is one
        # state: the first 560ms of recording *is* the morph, so nothing else has to know.
        activating = state == "recording" and elapsed < ACTIVATE_MS
        ease = ease_out(min(1.0, elapsed / ACTIVATE_MS))
        color = COLORS.get(state, COLORS["idle"])

        if activating:
            glow = 20 + ease * 40
            bloom = 0.75 * (1 - ease) + 0.12
            scale = 0.94 + ease * 0.06
            orb = (16 + ease * 51, 10 + ease * 116, 10 - ease * 6, -5 + ease * 3)
            bars_opacity = max(0.0, ease - 0.6) * 2.5
        elif state == "recording":
            glow, bloom, scale = 34.0, 0.14, 1.0
            orb, bars_opacity = None, 1.0
        else:
            glow, bloom, scale = 24.0, 0.08, 1.0
            orb, bars_opacity = (16.0, 10.0, 10.0, -5.0), 0.0

        rings = []
        if state == "recording" and elapsed < RINGS_MS:
            for index in range(3):
                progress = (elapsed - index * 150) / 900
                if 0 < progress < 1:
                    rings.append(
                        (WIDTH + progress * 150, HEIGHT + progress * 120, (1 - progress) * 0.45)
                    )

        wave, flash = [], 0.0
        if state == "recording" and elapsed < WAVE_END_MS:
            # Surge then slack, so the train reads as swell rather than N concentric rings.
            flash = max(0.0, 0.26 * (1 - min(1.0, elapsed / 420)) ** 2)
            for index in range(WAVE_CRESTS):
                progress = (elapsed - index * WAVE_STAGGER) / WAVE_MS
                if not 0 < progress < 1:
                    continue
                swell = (1 - (1 - progress) ** 1.5) * (1 - 0.1 * math.sin(progress * math.tau))
                size = 120 + swell * (WAVE_REACH * 2 - 120)
                phase = elapsed / 190 + index * 1.1
                wobble = (1 - progress) * 0.22
                opacity = (
                    min(1.0, progress * 7)
                    * (1 - progress) ** 0.8
                    * (0.45 + 0.55 * abs(math.sin(phase * 0.5)))
                    * (1.0 if index < 3 else 0.6)
                )
                wave.append((size, size * (1 - wobble * 0.55 * math.sin(phase)), opacity))

        label = self.message or LABELS.get(state, "")
        return Frame(
            state=state,
            color=color,
            glow=glow,
            bloom=bloom,
            scale=scale,
            orb=orb,
            bars=list(self._levels),
            bars_opacity=bars_opacity,
            label=label,
            label_opacity=0.0 if state in ("recording", "idle") else 1.0,
            rings=rings,
            wave=wave,
            flash=flash,
        )

    def _animating(self) -> bool:
        return self.state == "recording" or self._elapsed_ms() < RINGS_MS

    # --- Tk loop ---------------------------------------------------------

    def _tick(self) -> None:
        changed = False
        while True:
            try:
                state, message = self.events.get_nowait()
            except queue.Empty:
                break
            if state == "__quit__":
                self.root.quit()
                return
            if self.moving and state != "moving":
                continue  # Don't let a status update hide the pill mid-drag.
            if state != self.state:
                self._state_at = time.monotonic()
                if state == "recording":
                    self._levels = [0.0] * BARS  # Start the morph from a flat line.
            self.state = state
            self.message = message
            changed = True
            if state == "idle":
                self.root.withdraw()
            else:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
            if state in ("done", "error"):
                self.root.after(1400, lambda: self.set_state("idle"))

        if self.state != "idle":
            if self.state == "recording":
                # Scale RMS into something visible; speech usually sits well under 0.2.
                self._levels = self._levels[1:] + [min(1.0, self.level_source() * 8.0)]
            if changed or self._animating():
                self._paint(self.build_frame().render())
        self.root.after(FRAME_MS, self._tick)

    def run(self) -> None:
        self.root.mainloop()
