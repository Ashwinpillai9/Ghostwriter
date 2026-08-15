"""Always-on-top status pill. Owns the Tk main loop, so it must live on the main thread.

Tk provides the window, the event loop and the input handling; it does not draw anything. The
pill's rounded ends, glow and bloom need antialiasing and a real alpha channel, which a Tk
canvas cannot produce, so each frame is composed with Pillow in `pill.py` and pushed to the
window through Win32's UpdateLayeredWindow. Transparent pixels of that surface are
click-through, so the padding around the pill never swallows a click meant for the app behind.
"""

from __future__ import annotations

import ctypes
import json
import logging
import queue
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

from . import win32
from .pill import (
    BARS,
    COLORS,
    HEIGHT,
    LABELS,
    PAD_X,
    PAD_Y,
    SURFACE_H,
    SURFACE_W,
    WIDTH,
    DEFAULT_ACCENT,
    Frame,
    chrome,
    rgb,
    valid_accent,
)
from .wave import ScreenWave

log = logging.getLogger(__name__)

BOTTOM_MARGIN = 120
POSITION_FILE = Path(__file__).resolve().parent.parent / "overlay_position.json"

FRAME_MS = 16  # ~60fps, so the activation morph is smooth.
ACTIVATE_MS = 560.0  # Idle dot -> full waveform. The design's budget, matched exactly.
RINGS_MS = 1200.0  # Expanding rings outlive the morph slightly.

# Tk's winfo_screenwidth/height only ever describe the *primary* monitor, so clamping to them
# pins the pill to one display. These report the whole virtual desktop instead.
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_MONITOR_DEFAULTTONEAREST = 2


def ease_out(progress: float) -> float:
    """Cubic ease-out, the curve the design animates the activation morph on."""
    return 1 - (1 - progress) ** 3


class Overlay:
    def __init__(self, level_source: Callable[[], float], accent: str = DEFAULT_ACCENT):
        self.level_source = level_source
        self.accent = valid_accent(accent)
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
        self._surface: win32.Surface | None = None
        self._tick_id = None
        self._warm_todo: list | None = None

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
        try:
            self.wave: ScreenWave | None = ScreenWave(self.root)
        except Exception:  # noqa: BLE001 - the pill is the feature; the wave is decoration
            log.warning("wave overlay unavailable", exc_info=True)
            self.wave = None
        self._tick_id = self.root.after(FRAME_MS, self._tick)

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

    def _monitor_info(self, x: int, y: int, whole: bool = False):
        """The monitor nearest the pill's centre, as (left, top, right, bottom).

        `whole` returns the full display; otherwise the work area, which excludes the taskbar.
        """
        try:
            user32 = ctypes.windll.user32
            point = win32.POINT(int(x + WIDTH / 2), int(y + HEIGHT / 2))
            handle = user32.MonitorFromPoint(point, _MONITOR_DEFAULTTONEAREST)
            if not handle:
                return None
            info = win32.MONITORINFO()
            info.cbSize = ctypes.sizeof(win32.MONITORINFO)
            if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                return None
            rect = info.rcMonitor if whole else info.rcWork
            return rect.left, rect.top, rect.right, rect.bottom
        except Exception:  # noqa: BLE001 - not Windows, or the call is unavailable
            return None

    def _work_area(self, x: int, y: int) -> tuple[int, int, int, int] | None:
        """The usable area of the monitor nearest the pill's centre, excluding the taskbar."""
        return self._monitor_info(x, y)

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
            self._hwnd = win32.window_handle(self.root)
            # Not click-through: the pill has to receive the drag.
            win32.make_layered(self._hwnd, click_through=False)
            self._surface = win32.Surface(SURFACE_W, SURFACE_H)
        except Exception:  # noqa: BLE001 - without this the pill still works, just plainer
            log.warning("could not make the overlay a layered window", exc_info=True)

    def _paint(self, image) -> None:
        """Hand one RGBA frame to the compositor, alpha channel and all."""
        if self._hwnd is None or self._surface is None:
            return
        self._surface.load(image)
        self._surface.push(self._hwnd)

    # --- thread-safe API -------------------------------------------------

    def set_state(self, state: str, message: str = "") -> None:
        self.events.put((state, message))

    def quit(self) -> None:
        self.events.put(("__quit__", ""))

    def shutdown(self) -> None:
        """Release the timer, the second window and the GDI surfaces.

        The tick reschedules itself forever, so without cancelling it the callback outlives the
        window it draws into.
        """
        if self._tick_id is not None:
            try:
                self.root.after_cancel(self._tick_id)
            except Exception:  # noqa: BLE001 - already torn down
                pass
            self._tick_id = None
        if self.wave is not None:
            self.wave.destroy()
            self.wave = None
        if self._surface is not None:
            self._surface.close()
            self._surface = None

    # --- frame composition -----------------------------------------------

    def _elapsed_ms(self) -> float:
        return (time.monotonic() - self._state_at) * 1000

    def _look(self, state: str, elapsed: float):
        """The design's `live` values for a state at a given age.

        Split out from `build_frame` so the cache warmer can walk the same curve without
        touching any live state.
        """
        # The design plays "activating" and then hands over to "recording". Here that is one
        # state: the first 560ms of recording *is* the morph, so nothing else has to know.
        activating = state == "recording" and elapsed < ACTIVATE_MS
        ease = ease_out(min(1.0, elapsed / ACTIVATE_MS))
        # Recording (and the morph into it) wears the accent; the other states keep their own
        # meaning — amber is "working", green is "done", red is "failed".
        color = self.accent if state == "recording" else COLORS.get(state, COLORS["idle"])

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
        return color, glow, bloom, scale, orb, bars_opacity

    def _warm_plan(self) -> list[tuple[str, int, int, int]]:
        """Every chrome variant the animation will ask for.

        Each costs ~25ms to build and the morph needs a fresh one every frame, which is what
        made the first activation stutter through the animation that most needs to be smooth.
        """
        plan = []
        for state in ("recording", "transcribing", "done", "error", "moving"):
            steps = int(ACTIVATE_MS / FRAME_MS) + 2 if state == "recording" else 1
            for step in range(steps):
                _, glow, bloom, scale, _, _ = self._look(state, step * FRAME_MS)
                color = self.accent if state == "recording" else COLORS[state]
                plan.append((color, round(glow), round(bloom * 100), round(scale * 1000)))
        return plan

    def warm(self, budget: int = 1) -> None:
        """Build a few cached frames. Driven from the tick while idle, so it costs nothing.

        Deliberately on the Tk thread rather than a worker: Pillow filling this cache
        concurrently with the draw loop crashed the interpreter outright, and while idle there
        is no frame being drawn for it to compete with anyway.
        """
        if self._warm_todo is None:
            self._warm_todo = self._warm_plan()
        for _ in range(budget):
            if not self._warm_todo:
                return
            try:
                chrome(*self._warm_todo.pop())
            except Exception:  # noqa: BLE001 - a cold cache only costs a stutter
                log.debug("chrome warm-up failed", exc_info=True)
                self._warm_todo = []
                return

    def build_frame(self) -> Frame:
        """Translate the current state and its age into the design's `live` values."""
        elapsed = self._elapsed_ms()
        state = self.state
        color, glow, bloom, scale, orb, bars_opacity = self._look(state, elapsed)

        rings = []
        if state == "recording" and elapsed < RINGS_MS:
            for index in range(3):
                progress = (elapsed - index * 150) / 900
                if 0 < progress < 1:
                    rings.append(
                        (WIDTH + progress * 150, HEIGHT + progress * 120, (1 - progress) * 0.45)
                    )

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
        )

    def _animating(self) -> bool:
        return self.state == "recording" or self._elapsed_ms() < RINGS_MS

    # --- Tk loop ---------------------------------------------------------

    def _tick(self) -> None:
        self._tick_once()
        self._tick_id = self.root.after(FRAME_MS, self._tick)

    def _tick_once(self) -> None:
        """One frame of work. Split out from the scheduling so it can be driven in tests."""
        changed = False
        while True:
            try:
                state, message = self.events.get_nowait()
            except queue.Empty:
                break
            if state == "__quit__":
                self.shutdown()
                self.root.quit()
                return
            if self.moving and state != "moving":
                continue  # Don't let a status update hide the pill mid-drag.
            entering = state != self.state
            if entering:
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
            if entering:
                self._sync_wave(state)
            if state in ("done", "error"):
                self.root.after(1400, lambda: self.set_state("idle"))

        if self.wave is not None and self.wave.playing:
            self.wave.render(self._elapsed_ms())

        if self.state == "idle":
            self.warm()  # Nothing on screen to draw, so the blur is invisible work.
        else:
            if self.state == "recording":
                # Scale RMS into something visible; speech usually sits well under 0.2.
                self._levels = self._levels[1:] + [min(1.0, self.level_source() * 8.0)]
            if changed or self._animating():
                self._paint(self.build_frame().render())

    def _sync_wave(self, state: str) -> None:
        """Launch the screen-filling wave when recording starts; pull it if that is cut short."""
        if self.wave is None:
            return
        if state != "recording":
            self.wave.stop()
            return
        x, y = self.position
        monitor = self._monitor_info(x, y, whole=True)
        if monitor is None:
            return
        self.wave.start(monitor, (x + WIDTH // 2, y + HEIGHT // 2), rgb(self.accent))
        # Both windows are topmost, and the wave was shown last; put the pill back on top so
        # the crests sweep behind it, as in the design.
        self.root.lift()

    def run(self) -> None:
        self.root.mainloop()
