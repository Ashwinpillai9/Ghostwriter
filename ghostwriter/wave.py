"""The activation wave: a bioluminescent train that rolls from the pill to the screen edges.

Drawing this at display resolution in Pillow costs ~119ms a frame. Drawing it into a small
buffer and letting GDI's StretchBlt scale it across the display costs ~5ms, because the
expensive part was never the pixels — it was doing per-pixel work in Python.

Nothing here is blurred. A Gaussian blur is priced by area, so it cost ~6.7ms whatever the
radius and put a hard ceiling on the buffer resolution; the crests draw their own falloff as
concentric bands instead, which is priced by perimeter. That bought a bigger buffer, a cleaner
core, and a cheaper frame all at once.

The window is click-through and covers one whole monitor, so the wave sweeps over other
applications without interrupting anything you are doing.
"""

from __future__ import annotations

import logging
import math
import tkinter as tk

from PIL import Image, ImageDraw

from . import win32

log = logging.getLogger(__name__)

BUFFER_W = 960  # Height follows the monitor's aspect, so the scale stays uniform.
CRESTS = 8
DURATION_MS = 1700.0
STAGGER_MS = 140.0
END_MS = DURATION_MS + CRESTS * STAGGER_MS
START_RADIUS = 20  # Buffer pixels. Crests are born just outside the pill.
FLASH_MS = 420.0

# Each crest is a bright core fading into a deep-blue halo. The falloff is drawn directly, as
# concentric bands of decreasing alpha, rather than by blurring a hard band afterwards: a
# Gaussian blur costs ~6.7ms because it is priced by *area*, which caps the buffer resolution,
# while these bands cost perimeter and stay cheap however big the buffer gets. Drawing the
# gradient also gives a cleaner core than smearing one, which is what makes it read as
# luminous instead of smudged.
BAND_STEPS = 14  # Bands either side of the crest line.
BAND_STEP_PX = 4
FALLOFF = 3.4  # Higher concentrates the light into the core.
# Peak alpha at the crest line. Sampled off the reference, whose brightest ring pixels sit near
# 50% over the desktop; pushing this to clipping turns the light into flat painted rings.
INTENSITY = 1.15
# Deep blues from the design's conic gradient, with brighter cores sampled off the reference.
HALOS = [(12, 56, 232), (16, 68, 255), (36, 100, 255), (24, 82, 246)]
CORES = [(150, 224, 255), (56, 189, 248), (110, 200, 255), (86, 205, 252)]

# (offset from the crest line, weight) — precomputed once; the shape never changes. Sorted
# dimmest-first so the bright core is painted last and nothing overwrites it.
PROFILE = sorted(
    (
        (step * BAND_STEP_PX, math.exp(-((step / BAND_STEPS) ** 2) * FALLOFF))
        for step in range(-BAND_STEPS, BAND_STEPS + 1)
    ),
    key=lambda band: band[1],
)
# The bloom under the pill as the wave departs, as filled ellipses fading outward — same
# reason as the crests: no full-surface blur.
FLASH_RINGS = 14


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
        # `limit` is the distance to the farthest corner, so it *is* the radius a crest needs
        # to clear the screen. Halving it here is what used to stop the wave halfway out.
        radius = START_RADIUS + swell * (limit - START_RADIUS)
        phase = elapsed / 190 + index * 1.1
        wobble = (1 - progress) * 0.22
        opacity = (
            min(1.0, progress * 7)
            # Fades gently rather than steeply, so a crest still reads as light when it
            # arrives at the edge instead of dying in the middle of the screen.
            * (1 - progress) ** 0.5
            * (0.6 + 0.4 * abs(math.sin(phase * 0.5)))
            * (1.0 if index < 3 else 0.75)
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

        # The bloom goes down first: ImageDraw replaces pixels rather than blending them, so
        # drawing it afterwards would punch a hole through the crests leaving the pill.
        flash = flash_at(elapsed)
        if flash > 0:
            outer = size[0] * 0.22
            for ring in range(FLASH_RINGS, 0, -1):
                span = outer * ring / FLASH_RINGS
                alpha = int(255 * flash * (1 - ring / FLASH_RINGS) ** 1.6 * 0.5)
                if alpha <= 0:
                    continue
                draw.ellipse(
                    (cx - span, cy - span * 0.62, cx + span, cy + span * 0.62),
                    fill=(*self._color, alpha),
                )

        train = crests(elapsed, self._center, size)
        # Widest, dimmest bands first so the bright core lands on top of its own halo.
        for offset, weight in PROFILE:
            for index, (rx, ry, opacity) in enumerate(train):
                alpha = int(255 * min(1.0, opacity * weight * INTENSITY))
                if alpha <= 0:
                    continue
                halo = HALOS[index % len(HALOS)]
                core = CORES[index % len(CORES)]
                tint = tuple(
                    int(halo[c] + (core[c] - halo[c]) * weight) for c in range(3)
                )
                left, top = cx - rx - offset, cy - ry - offset
                right, bottom = cx + rx + offset, cy + ry + offset
                if right - left < 2 or bottom - top < 2:
                    continue
                draw.ellipse((left, top, right, bottom), outline=(*tint, alpha), width=BAND_STEP_PX + 1)

        self._buffer.load(image)
        self._screen.stretch_from(self._buffer)
        self._screen.push(self._hwnd)

    def destroy(self) -> None:
        self._release()
        try:
            self.window.destroy()
        except Exception:  # noqa: BLE001 - already gone during shutdown
            pass
