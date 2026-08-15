"""Draws the status pill exactly as designed, as an RGBA image.

Tk's canvas has no antialiasing, no rounded windows, no blur and no per-element opacity, so
the design's rounded ends, outer glow and inner bloom cannot be drawn with it at all. Instead
every frame is composed here with Pillow and handed to Win32's UpdateLayeredWindow, which
takes a full alpha channel — see `overlay.py`.

Layer order matches the CSS it came from: drop shadow, coloured glow, body, inner bloom,
border, then the contents (orb, waveform, label).
"""

from __future__ import annotations

import functools

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 260, 46
RADIUS = 23
BARS = 21
BAR_W, BAR_GAP = 4, 2
BARS_LEFT = 67  # Where the waveform starts inside the pill, per the design.
LABEL_LEFT = 38
LABEL_SIZE = 13

# The surface is bigger than the pill so the glow and the activation wave have room; the pill
# sits in the middle and the rest stays transparent (and therefore click-through). The size is
# a performance ceiling as much as a design choice — see WAVE_REACH.
SURFACE_W, SURFACE_H = 700, 360
PAD_X = (SURFACE_W - WIDTH) // 2
PAD_Y = (SURFACE_H - HEIGHT) // 2
CENTER = (SURFACE_W / 2, SURFACE_H / 2)

# The pill and its glow are drawn on their own small tile and pasted in. Blurring is priced by
# area, and doing it across the full wave-sized surface costs ~44ms a frame — three times the
# entire frame budget — for pixels that are transparent anyway.
CHROME_MARGIN = 60
CHROME_W, CHROME_H = WIDTH + 2 * CHROME_MARGIN, HEIGHT + 2 * CHROME_MARGIN
CHROME_AT = (PAD_X - CHROME_MARGIN, PAD_Y - CHROME_MARGIN)

BODY = (11, 15, 25, 235)  # rgba(11,15,25,0.92)
TEXT = (229, 231, 235, 255)  # #e5e7eb
IDLE_BORDER = (31, 41, 55, 255)  # #1f2937

COLORS = {
    "idle": "#6b7280",
    "recording": "#ef4444",
    "transcribing": "#f59e0b",
    "done": "#22c55e",
    "error": "#ef4444",
    "moving": "#38bdf8",
}

LABELS = {
    "transcribing": "Transcribing…",
    "done": "Pasted",
    "error": "Transcription failed",
    "moving": "Drag me, then let go",
}

# The activation wave. The design sends it to the edges of the display; that is a GPU effect,
# and compositing it full-screen in Pillow measures at 119 ms a frame (8fps), so it runs to the
# edge of this surface instead. Blues sampled from the design's conic gradient.
WAVE_REACH = ((SURFACE_W / 2) ** 2 + (SURFACE_H / 2) ** 2) ** 0.5
WAVE_CRESTS = 8
WAVE_MS = 1700.0
WAVE_STAGGER = 140.0
WAVE_BAND = 20  # Crests stay this thick in pixels however far they travel.
# The design masks and blurs each crest separately, which keeps them distinct where they
# overlap. Blurring the stack in one pass is far cheaper but pools the alpha, so the crests are
# drawn thinner and dimmer to compensate; without this the train reads as one solid donut.
WAVE_ALPHA = 0.5
WAVE_BLUES = [(15, 60, 224), (59, 134, 255), (18, 70, 255), (43, 107, 255)]


def rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


@functools.lru_cache(maxsize=4)
def _font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


@functools.lru_cache(maxsize=64)
def _shadow(scale: int) -> Image.Image:
    """box-shadow: 0 10px 30px rgba(0,0,0,0.55). Independent of colour, so cached apart."""
    factor = scale / 1000
    dx = (WIDTH * (1 - factor)) / 2
    dy = (HEIGHT * (1 - factor)) / 2
    img = Image.new("RGBA", (CHROME_W, CHROME_H), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        (
            CHROME_MARGIN + dx, CHROME_MARGIN + dy + 10,
            CHROME_MARGIN + WIDTH - dx, CHROME_MARGIN + HEIGHT - dy + 10,
        ),
        radius=RADIUS * factor,
        fill=(0, 0, 0, 140),
    )
    return img.filter(ImageFilter.GaussianBlur(15))


@functools.lru_cache(maxsize=256)
def _chrome(color: str, glow: int, bloom: int, scale: int) -> Image.Image:
    """Everything that doesn't change between frames of the same state, cached.

    `glow`, `bloom` and `scale` arrive pre-quantised (see `Frame`) so that the cache actually
    hits during an animation instead of holding a near-unique entry per frame.
    """
    tint = rgb(color)
    bloom_alpha = bloom / 100
    factor = scale / 1000
    size = (CHROME_W, CHROME_H)
    img = Image.new("RGBA", size, (0, 0, 0, 0))

    left, top = CHROME_MARGIN, CHROME_MARGIN
    right, bottom = CHROME_MARGIN + WIDTH, CHROME_MARGIN + HEIGHT
    if factor != 1.0:
        # transform: scale() about the pill's centre.
        dx = (WIDTH * (1 - factor)) / 2
        dy = (HEIGHT * (1 - factor)) / 2
        left, top, right, bottom = left + dx, top + dy, right - dx, bottom - dy
    box = (left, top, right, bottom)
    radius = RADIUS * factor

    img.alpha_composite(_shadow(scale))

    # box-shadow: 0 0 {glow}px {color}
    if glow > 0:
        halo = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(halo).rounded_rectangle(box, radius=radius, fill=(*tint, 165))
        img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(glow / 2)))

    body = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(body)
    draw.rounded_rectangle(box, radius=radius, fill=BODY)

    # background: radial-gradient(60% 140% at 50% 50%, color, transparent 70%)
    if bloom_alpha > 0:
        glowing = Image.new("RGBA", size, (0, 0, 0, 0))
        cx, cy = (left + right) / 2, (top + bottom) / 2
        rx, ry = WIDTH * 0.30 * factor, HEIGHT * 0.70 * factor
        ImageDraw.Draw(glowing).ellipse(
            (cx - rx, cy - ry, cx + rx, cy + ry), fill=(*tint, int(255 * bloom_alpha))
        )
        glowing = glowing.filter(ImageFilter.GaussianBlur(22))
        body.alpha_composite(glowing)

    # inset 0 1px 0 rgba(255,255,255,0.05) — a hairline catching light along the top edge.
    draw.rounded_rectangle(
        (left, top + 1, right, bottom), radius=radius, outline=(255, 255, 255, 13), width=1
    )
    border = (*tint, 115) if color != COLORS["idle"] else IDLE_BORDER
    draw.rounded_rectangle(box, radius=radius, outline=border, width=1)

    # Keep the bloom and the highlight inside the rounded shape.
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    img.alpha_composite(Image.composite(body, Image.new("RGBA", body.size, (0, 0, 0, 0)), mask))
    return img


class Frame:
    """One rendered frame. Values mirror the design's `live` object."""

    def __init__(
        self,
        state: str,
        color: str,
        glow: float,
        bloom: float,
        scale: float = 1.0,
        opacity: float = 1.0,
        orb: tuple[float, float, float, float] | None = None,
        bars: list[float] | None = None,
        bars_opacity: float = 0.0,
        label: str = "",
        label_opacity: float = 0.0,
        rings: list[tuple[float, float, float]] | None = None,
        wave: list[tuple[float, float, float]] | None = None,
        flash: float = 0.0,
    ):
        self.state = state
        self.color = color
        self.glow = glow
        self.bloom = bloom
        self.scale = scale
        self.opacity = opacity
        self.orb = orb
        self.bars = bars or []
        self.bars_opacity = bars_opacity
        self.label = label
        self.label_opacity = label_opacity
        self.rings = rings or []
        self.wave = wave or []
        self.flash = flash

    def _render_wave(self) -> Image.Image:
        """The bioluminescent crests, drawn as one layer and blurred once.

        The design blurs every crest separately; blurring the stack once is visually close and
        eight times cheaper, which is what keeps the whole effect inside a frame budget.
        """
        layer = Image.new("RGBA", (SURFACE_W, SURFACE_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for index, (size, size_y, opacity) in enumerate(self.wave):
            if opacity <= 0:
                continue
            tint = WAVE_BLUES[index % len(WAVE_BLUES)]
            draw.ellipse(
                (
                    CENTER[0] - size / 2, CENTER[1] - size_y / 2,
                    CENTER[0] + size / 2, CENTER[1] + size_y / 2,
                ),
                outline=(*tint, int(255 * min(1.0, opacity) * WAVE_ALPHA)),
                width=WAVE_BAND,
            )
        layer = layer.filter(ImageFilter.GaussianBlur(13))

        if self.flash > 0:
            tint = rgb(self.color)
            flash = Image.new("RGBA", (SURFACE_W, SURFACE_H), (0, 0, 0, 0))
            radius = SURFACE_W * 0.30
            ImageDraw.Draw(flash).ellipse(
                (
                    CENTER[0] - radius, CENTER[1] - radius,
                    CENTER[0] + radius, CENTER[1] + radius,
                ),
                fill=(*tint, int(255 * min(1.0, self.flash))),
            )
            layer.alpha_composite(flash.filter(ImageFilter.GaussianBlur(40)))
        return layer

    def render(self) -> Image.Image:
        tint = rgb(self.color)
        # Quantise so the chrome cache hits across frames instead of missing every time.
        chrome = _chrome(
            self.color, int(round(self.glow)), int(round(self.bloom * 100)),
            int(round(self.scale * 1000)),
        )
        if self.wave or self.flash:
            img = self._render_wave()  # Behind the pill, as in the design's DOM order.
        else:
            img = Image.new("RGBA", (SURFACE_W, SURFACE_H), (0, 0, 0, 0))
        img.alpha_composite(chrome, CHROME_AT)
        draw = ImageDraw.Draw(img)

        for width, height, opacity in self.rings:
            if opacity <= 0:
                continue
            draw.rounded_rectangle(
                (
                    CENTER[0] - width / 2, CENTER[1] - height / 2,
                    CENTER[0] + width / 2, CENTER[1] + height / 2,
                ),
                radius=height / 2,
                outline=(*tint, int(255 * min(1.0, opacity))),
                width=1,
            )

        if self.orb is not None:
            x, width, height, offset = self.orb
            top = PAD_Y + HEIGHT / 2 + offset
            box = (PAD_X + x, top, PAD_X + x + width, top + height)
            # The orb carries its own halo (box-shadow: 0 0 12px), so it reads as a light
            # source rather than a dot, and stays visible as it stretches into the waveform.
            halo = Image.new("RGBA", (SURFACE_W, SURFACE_H), (0, 0, 0, 0))
            ImageDraw.Draw(halo).rounded_rectangle(box, radius=height / 2, fill=(*tint, 200))
            img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(5)))
            draw.rounded_rectangle(box, radius=height / 2, fill=(*tint, 255))

        if self.bars and self.bars_opacity > 0:
            alpha = int(255 * min(1.0, self.bars_opacity))
            middle = PAD_Y + HEIGHT / 2
            for index, level in enumerate(self.bars):
                height = max(3.0, level * (HEIGHT - 14))
                x = PAD_X + BARS_LEFT + index * (BAR_W + BAR_GAP)
                draw.rounded_rectangle(
                    (x, middle - height / 2, x + BAR_W, middle + height / 2),
                    radius=BAR_W / 2,
                    fill=(*tint, alpha),
                )

        if self.label and self.label_opacity > 0:
            draw.text(
                (PAD_X + LABEL_LEFT, PAD_Y + HEIGHT / 2),
                self.label,
                font=_font(LABEL_SIZE),
                fill=(*TEXT[:3], int(255 * min(1.0, self.label_opacity))),
                anchor="lm",
            )

        if self.opacity < 1.0:
            img.putalpha(img.getchannel("A").point(lambda a: int(a * self.opacity)))
        return img
