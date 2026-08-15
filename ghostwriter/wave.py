"""The activation ripple: a droplet landing on the display and spreading to its edges.

Modelled as a real travelling wave rather than as expanding rings — see `ripples()` for why
that distinction is the whole difference between "water" and "concentric circles".

Drawing this at display resolution in Pillow costs ~119ms a frame. Drawing it into a small
buffer and letting GDI's StretchBlt scale it across the display costs ~3ms, because the
expensive part was never the pixels — it was doing per-pixel work in Python.

Nothing here is blurred. A Gaussian blur is priced by area, so it cost ~6.7ms whatever the
radius and put a hard ceiling on the buffer resolution. Sampling the wave radially and drawing
one thin ring per sample is priced by perimeter instead, which bought a bigger buffer and a
cheaper frame at once — and it is the only way to draw a waveform rather than a shape.

The window is click-through and covers one whole monitor, so the ripple sweeps over other
applications without interrupting anything you are doing.
"""

from __future__ import annotations

import logging
import math
import tkinter as tk

from PIL import Image, ImageDraw

from . import win32
from .style import WaveStyle

log = logging.getLogger(__name__)

def reach(center: tuple[float, float], size: tuple[float, float], style: WaveStyle) -> float:
    """Distance to the farthest corner, so the last crest is still on screen as it leaves."""
    cx, cy = center
    width, height = size
    return math.hypot(max(cx, width - cx), max(cy, height - cy)) + style.overshoot


def ripples(
    elapsed: float, center: tuple[float, float], size: tuple[float, float], style: WaveStyle
):
    """The ripple train at `elapsed` ms, sampled radially.

    Returns (radius_x, radius_y, intensity) per sampled radius, in buffer pixels.

    This is a travelling wave, not a set of expanding rings. A droplet puts a packet of energy
    into the surface at one point; the crests inside it stay a fixed wavelength apart and all
    move outward together at one speed, so what you see spreading is the *packet*, with the
    individual crests marching through it. Rings that each expand on their own easing curve
    bunch up as they decelerate and read as concentric circles, which is what this replaces.

    Amplitude falls as the ring grows — the same energy spread around an ever-longer
    circumference — and the whole disturbance fades over the animation's life.
    """
    limit = reach(center, size, style)
    lead = style.start_radius + style.speed(limit) * elapsed
    if lead <= style.start_radius:
        return []

    # The train lengthens as it travels: the slower waves fall behind the fast leading edge.
    packet = style.packet_px * (0.55 + 0.45 * min(1.0, elapsed / style.duration_ms))
    life = max(0.0, 1 - elapsed / style.end_ms) ** 0.65
    if life <= 0:
        return []

    out = []
    first = max(style.start_radius, lead - packet)
    steps = int((min(lead, limit) - first) / style.sample_px)
    for step in range(max(0, steps) + 1):
        radius = first + step * style.sample_px
        depth = (lead - radius) / packet  # 0 at the leading edge, 1 at the tail
        if not 0 <= depth <= 1:
            continue
        # Crests sit a fixed wavelength apart behind the leading edge. Only the positive lobe
        # is lit, so the troughs between them stay dark.
        lobe = math.cos(math.tau * (lead - radius) / style.wavelength)
        if lobe <= 0:
            continue
        # A soft nose stops the front of the packet arriving as a hard edge.
        nose = min(1.0, depth / 0.06)
        spread = 1 / math.sqrt(1 + radius / (limit * style.damping))
        intensity = life * nose * (1 - depth) ** 1.1 * spread * lobe**style.sharpness
        if intensity <= 0.004:
            continue
        # A touch of squash so the ring is not a perfect circle frame after frame.
        wobble = 1 - 0.03 * math.sin(radius / 90 + elapsed / 400)
        out.append((radius, radius * wobble, intensity))
    return out


def flash_at(elapsed: float, style: WaveStyle) -> float:
    """The bloom under the pill as the wave leaves it."""
    if style.flash_ms <= 0:
        return 0.0
    return max(0.0, 0.26 * (1 - min(1.0, elapsed / style.flash_ms)) ** 2)


def draw_frame(
    elapsed: float,
    center: tuple[float, float],
    size: tuple[int, int],
    style: WaveStyle,
    color: tuple[int, int, int],
) -> Image.Image:
    """One buffer-sized frame of the wave. Pure, so it can be previewed and tested offline."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cx, cy = center

    # The bloom goes down first: ImageDraw replaces pixels rather than blending them, so
    # drawing it afterwards would punch a hole through the crests leaving the pill.
    flash = flash_at(elapsed, style)
    if flash > 0:
        rings = style.flash_rings
        outer = size[0] * 0.22
        for ring in range(rings, 0, -1):
            span = outer * ring / rings
            alpha = int(255 * flash * (1 - ring / rings) ** 1.6 * 0.5)
            if alpha > 0:
                draw.ellipse(
                    (cx - span, cy - span * 0.62, cx + span, cy + span * 0.62),
                    fill=(*color, alpha),
                )

    # Dimmest first, so the bright centre of a crest is painted over its own shoulders.
    for rx, ry, intensity in sorted(ripples(elapsed, center, size, style), key=lambda r: r[2]):
        alpha = int(255 * min(1.0, intensity * style.intensity))
        if alpha <= 0:
            continue
        # The brightest part of a crest is near-white; its shoulders sink into deep blue.
        halo, core = style.halos[0], style.cores[0]
        lit = min(1.0, intensity * 1.6)
        tint = tuple(int(halo[c] + (core[c] - halo[c]) * lit) for c in range(3))
        if rx < 2 or ry < 2:
            continue
        draw.ellipse(
            (cx - rx, cy - ry, cx + rx, cy + ry),
            outline=(*tint, alpha),
            width=style.sample_px + 1,
        )
    return image


class ScreenWave:
    """A click-through, monitor-filling window that plays the wave and then hides."""

    def __init__(self, parent: tk.Misc, style: WaveStyle | None = None):
        self.style = style or WaveStyle()
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
            buffer_w = self.style.buffer_width
            buffer_h = max(1, round(buffer_w * height / width))
            self._buffer_size = (buffer_w, buffer_h)
            self._buffer = win32.Surface(buffer_w, buffer_h)
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
        if elapsed >= self.style.end_ms:
            self.stop()
            return

        image = draw_frame(elapsed, self._center, self._buffer_size, self.style, self._color)
        self._buffer.load(image)
        self._screen.stretch_from(self._buffer)
        self._screen.push(self._hwnd)

    def destroy(self) -> None:
        self._release()
        try:
            self.window.destroy()
        except Exception:  # noqa: BLE001 - already gone during shutdown
            pass
