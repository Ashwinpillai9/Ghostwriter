"""Everything about how the overlay looks, in one place, built from config.toml.

These used to be constants scattered through `pill.py`, `overlay.py` and `wave.py`. Tuning the
animation meant editing Python, which is the wrong place for a taste decision.

Every value is validated on the way in and falls back to its default if it is missing, the
wrong type or out of range — a typo in config.toml should cost you one warning at startup, not
an exception inside the render loop several hundred times a second.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

DEFAULT_ACCENT = "#38bdf8"
# The design exposes the accent as a switchable prop with exactly these four choices.
ACCENTS = ("#38bdf8", "#ef4444", "#22c55e", "#a855f7")

# Per-state colours. "recording" is not here: it wears the accent.
DEFAULT_COLORS = {
    "idle": "#6b7280",
    "transcribing": "#f59e0b",
    "done": "#22c55e",
    "error": "#ef4444",
    "moving": "#38bdf8",
}

# Deep blues from the design's conic gradient, with brighter cores sampled off the reference.
DEFAULT_HALOS = ("#0c38e8", "#1044ff", "#2464ff", "#1852f6")
DEFAULT_CORES = ("#96e0ff", "#38bdf8", "#6ec8ff", "#56cdfc")


def rgb(hex_color: str) -> tuple[int, int, int]:
    value = str(hex_color).lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected #rrggbb, got {hex_color!r}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _color(value, default: str, where: str) -> str:
    try:
        rgb(value)
    except Exception:  # noqa: BLE001 - any unparseable value falls back
        if value is not None:
            log.warning("%s: %r is not a #rrggbb colour, using %s", where, value, default)
        return default
    return str(value)


def _colors(value, default: tuple[str, ...], where: str) -> tuple[tuple[int, int, int], ...]:
    if value is None:
        return tuple(rgb(c) for c in default)
    if not isinstance(value, (list, tuple)) or not value:
        log.warning("%s: expected a list of #rrggbb colours, using defaults", where)
        return tuple(rgb(c) for c in default)
    return tuple(rgb(_color(c, default[i % len(default)], where)) for i, c in enumerate(value))


def _number(value, default, low, high, where: str, whole: bool = False):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        log.warning("%s: %r is not a number, using %s", where, value, default)
        return default
    if not low <= value <= high:
        log.warning("%s: %r is outside %s..%s, using %s", where, value, low, high, default)
        return default
    return int(value) if whole else float(value)


def _flag(value, default: bool, where: str) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        log.warning("%s: %r is not true/false, using %s", where, value, default)
        return default
    return value


@dataclass
class WaveStyle:
    """The activation wave that sweeps the display."""

    enabled: bool = True
    crests: int = 6
    duration_ms: float = 1700.0
    stagger_ms: float = 200.0
    start_radius: int = 20
    overshoot: int = 40  # How far past the farthest corner a crest travels before expiring.
    flash_ms: float = 420.0
    flash_rings: int = 14
    # Buffer the wave is drawn into before GDI scales it to the display. Bigger is crisper and
    # costs more; the cost is roughly linear in the pixel count.
    buffer_width: int = 960
    band_steps: int = 8  # Bands either side of the crest line, forming its falloff.
    band_step_px: int = 3
    falloff: float = 4.2  # Higher concentrates the light into the core.
    # Peak alpha at the crest line. Kept well under 1 so the crests stay as light passing over
    # the desktop, with dark space between them, rather than covering it.
    intensity: float = 0.72
    halos: tuple[tuple[int, int, int], ...] = field(
        default_factory=lambda: tuple(rgb(c) for c in DEFAULT_HALOS)
    )
    cores: tuple[tuple[int, int, int], ...] = field(
        default_factory=lambda: tuple(rgb(c) for c in DEFAULT_CORES)
    )

    def __post_init__(self) -> None:
        self.end_ms = self.duration_ms + self.crests * self.stagger_ms
        # (offset from the crest line, weight), dimmest first so the bright core is painted
        # last and nothing overwrites it.
        self.profile = sorted(
            (
                (step * self.band_step_px, math.exp(-((step / self.band_steps) ** 2) * self.falloff))
                for step in range(-self.band_steps, self.band_steps + 1)
            ),
            key=lambda band: band[1],
        )

    @classmethod
    def from_config(cls, cfg) -> "WaveStyle":
        at = "overlay.wave"
        default = cls()
        return cls(
            enabled=_flag(cfg.get(f"{at}.enabled"), default.enabled, f"{at}.enabled"),
            crests=_number(cfg.get(f"{at}.crests"), default.crests, 1, 24, f"{at}.crests", True),
            duration_ms=_number(
                cfg.get(f"{at}.duration_ms"), default.duration_ms, 100, 10000, f"{at}.duration_ms"
            ),
            stagger_ms=_number(
                cfg.get(f"{at}.stagger_ms"), default.stagger_ms, 0, 2000, f"{at}.stagger_ms"
            ),
            start_radius=_number(
                cfg.get(f"{at}.start_radius"), default.start_radius, 0, 400, f"{at}.start_radius", True
            ),
            overshoot=_number(
                cfg.get(f"{at}.overshoot"), default.overshoot, 0, 2000, f"{at}.overshoot", True
            ),
            flash_ms=_number(cfg.get(f"{at}.flash_ms"), default.flash_ms, 0, 5000, f"{at}.flash_ms"),
            flash_rings=_number(
                cfg.get(f"{at}.flash_rings"), default.flash_rings, 1, 64, f"{at}.flash_rings", True
            ),
            buffer_width=_number(
                cfg.get(f"{at}.buffer_width"), default.buffer_width, 160, 2560, f"{at}.buffer_width", True
            ),
            band_steps=_number(
                cfg.get(f"{at}.band_steps"), default.band_steps, 1, 64, f"{at}.band_steps", True
            ),
            band_step_px=_number(
                cfg.get(f"{at}.band_step_px"), default.band_step_px, 1, 32, f"{at}.band_step_px", True
            ),
            falloff=_number(cfg.get(f"{at}.falloff"), default.falloff, 0.1, 20, f"{at}.falloff"),
            intensity=_number(
                cfg.get(f"{at}.intensity"), default.intensity, 0, 4, f"{at}.intensity"
            ),
            halos=_colors(cfg.get(f"{at}.halos"), DEFAULT_HALOS, f"{at}.halos"),
            cores=_colors(cfg.get(f"{at}.cores"), DEFAULT_CORES, f"{at}.cores"),
        )


@dataclass
class OverlayStyle:
    """The pill itself, and the wave it launches."""

    accent: str = DEFAULT_ACCENT
    colors: dict = field(default_factory=lambda: dict(DEFAULT_COLORS))
    frame_ms: int = 16  # ~60fps.
    activate_ms: float = 560.0  # Idle dot -> full waveform. The design's budget.
    rings_ms: float = 1200.0  # The rings hugging the pill outlive the morph slightly.
    hold_ms: float = 1400.0  # How long "Pasted" and errors stay up before the pill hides.
    wave: WaveStyle = field(default_factory=WaveStyle)

    def color_for(self, state: str) -> str:
        """Recording wears the accent; every other state keeps its own meaning."""
        if state == "recording":
            return self.accent
        return self.colors.get(state, self.colors["idle"])

    @classmethod
    def from_config(cls, cfg) -> "OverlayStyle":
        default = cls()
        colors = {
            state: _color(cfg.get(f"overlay.colors.{state}"), fallback, f"overlay.colors.{state}")
            for state, fallback in DEFAULT_COLORS.items()
        }
        return cls(
            accent=_color(cfg.get("overlay.accent"), DEFAULT_ACCENT, "overlay.accent"),
            colors=colors,
            frame_ms=_number(
                cfg.get("overlay.frame_ms"), default.frame_ms, 4, 200, "overlay.frame_ms", True
            ),
            activate_ms=_number(
                cfg.get("overlay.activate_ms"), default.activate_ms, 0, 5000, "overlay.activate_ms"
            ),
            rings_ms=_number(
                cfg.get("overlay.rings_ms"), default.rings_ms, 0, 10000, "overlay.rings_ms"
            ),
            hold_ms=_number(cfg.get("overlay.hold_ms"), default.hold_ms, 0, 20000, "overlay.hold_ms"),
            wave=WaveStyle.from_config(cfg),
        )
