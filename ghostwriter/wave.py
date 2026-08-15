"""The activation wave: a bioluminescent train that rolls from the pill to the screen edges.

Drawing this at display resolution in Pillow costs ~119ms a frame. Drawing it into a small
buffer and letting GDI's StretchBlt scale it across the display costs ~9ms, because the
expensive part was never the pixels — it was doing per-pixel work in Python. The image is
heavily blurred, so scaling it up loses nothing.

The window is click-through and covers one whole monitor, so the wave sweeps over other
applications without interrupting anything you are doing.
"""

from __future__ import annotations

import logging
import math
import tkinter as tk

from PIL import Image, ImageDraw, ImageFilter

from . import win32

log = logging.getLogger(__name__)

BUFFER_W = 640  # Height follows the monitor's aspect, so the scale stays uniform.
CRESTS = 8
DURATION_MS = 1700.0
STAGGER_MS = 140.0
END_MS = DURATION_MS + CRESTS * STAGGER_MS
BAND = 9  # Crest thickness in buffer pixels; ~24 on a 1707px-wide display.
BLUR = 6
FLASH_MS = 420.0
# Sampled from the design's conic gradient: #0f3ce0 -> #3b86ff -> #1246ff -> #2b6bff.
BLUES = [(15, 60, 224), (59, 134, 255), (18, 70, 255), (43, 107, 255)]


def reach(center: tuple[float, float], size: tuple[float, float]) -> float:
    """Distance to the farthest corner, so the last crest is still on screen as it leaves."""
    cx, cy = center
    width, height = size
    return math.hypot(max(cx, width - cx), max(cy, height - cy)) + 40


def crests(elapsed: float, center: tuple[float, float], size: tuple[float, float]):
    """The crest train at `elapsed` ms, as (radius_x, radius_y, opacity) in buffer pixels.

    Straight from the design: a surge-then-slack easing so the train reads as swell rather
    than as N concentric rings, with each crest breathing as it travels.
    """
    limit = reach(center, size)
    out = []
    for index in range(CRESTS):
        progress = (elapsed - index * STAGGER_MS) / DURATION_MS
        if not 0 < progress < 1:
            continue
        swell = (1 - (1 - progress) ** 1.5) * (1 - 0.1 * math.sin(progress * math.tau))
        radius = (30 + swell * (limit - 30)) / 2
        phase = elapsed / 190 + index * 1.1
        wobble = (1 - progress) * 0.22
        opacity = (
            min(1.0, progress * 7)
            * (1 - progress) ** 0.8
            * (0.45 + 0.55 * abs(math.sin(phase * 0.5)))
            * (1.0 if index < 3 else 0.6)
        )
        out.append((radius, radius * (1 - wobble * 0.55 * math.sin(phase)), opacity))
    return out


def flash_at(elapsed: float) -> float:
    """The bloom under the pill as the wave leaves it."""
    return max(0.0, 0.26 * (1 - min(1.0, elapsed / FLASH_MS)) ** 2)


class ScreenWave:
    """A click-through, monitor-filling window that plays the wave and then hides."""

    def __init__(self, parent: tk.Misc):
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self._hwnd = None
        self._monitor: tuple[int, int, int, int] | None = None
        self._screen: win32.Surface | None = None
        self._buffer: win32.Surface | None = None
        self._buffer_size = (0, 0)
        self.playing = False
        try:
            self.window.update_idletasks()
            self._hwnd = win32.window_handle(self.window)
            win32.make_layered(self._hwnd, click_through=True)
        except Exception:  # noqa: BLE001 - the pill still works without the flourish
            log.warning("wave overlay unavailable", exc_info=True)

    # --- surfaces --------------------------------------------------------

    def _prepare(self, monitor: tuple[int, int, int, int]) -> bool:
        """Size the window and its buffers to a monitor, reusing them when it hasn't changed."""
        if self._hwnd is None:
            return False
        left, top, right, bottom = monitor
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return False
        if monitor != self._monitor:
            self._release()
            buffer_h = max(1, round(BUFFER_W * height / width))
            self._buffer_size = (BUFFER_W, buffer_h)
            self._buffer = win32.Surface(BUFFER_W, buffer_h)
            self._screen = win32.Surface(width, height)
            self._monitor = monitor
            self.window.geometry(f"{width}x{height}+{left}+{top}")
        return True

    def _release(self) -> None:
        for surface in (self._buffer, self._screen):
            if surface is not None:
                surface.close()
        self._buffer = self._screen = None
        self._monitor = None

    # --- playback --------------------------------------------------------

    def start(self, monitor: tuple[int, int, int, int], center: tuple[int, int], color) -> None:
        if not self._prepare(monitor):
            return
        left, top, right, bottom = monitor
        width, height = right - left, bottom - top
        scale = self._buffer_size[0] / width
        self._center = ((center[0] - left) * scale, (center[1] - top) * scale)
        self._color = color
        self.playing = True
        self.window.deiconify()
        self.window.attributes("-topmost", True)

    def stop(self) -> None:
        if not self.playing:
            return
        self.playing = False
        self.window.withdraw()

    def render(self, elapsed: float) -> None:
        """Draw one frame. Caller drives the clock, so it shares the overlay's tick."""
        if not self.playing or self._buffer is None or self._screen is None:
            return
        if elapsed >= END_MS:
            self.stop()
            return

        size = self._buffer_size
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        cx, cy = self._center
        for index, (rx, ry, opacity) in enumerate(crests(elapsed, self._center, size)):
            tint = BLUES[index % len(BLUES)]
            draw.ellipse(
                (cx - rx, cy - ry, cx + rx, cy + ry),
                outline=(*tint, int(255 * min(1.0, opacity))),
                width=BAND,
            )
        image = image.filter(ImageFilter.GaussianBlur(BLUR))

        flash = flash_at(elapsed)
        if flash > 0:
            glow = Image.new("RGBA", size, (0, 0, 0, 0))
            radius = size[0] * 0.16
            ImageDraw.Draw(glow).ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill=(*self._color, int(255 * flash)),
            )
            image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(24)))

        self._buffer.load(image)
        self._screen.stretch_from(self._buffer)
        self._screen.push(self._hwnd)

    def destroy(self) -> None:
        self._release()
        try:
            self.window.destroy()
        except Exception:  # noqa: BLE001 - already gone during shutdown
            pass
