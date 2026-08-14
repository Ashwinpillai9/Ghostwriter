"""Always-on-top status pill. Owns the Tk main loop, so it must live on the main thread."""

from __future__ import annotations

import ctypes
import json
import logging
import queue
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

BARS = 21
WIDTH = 260
HEIGHT = 46
BOTTOM_MARGIN = 120
POSITION_FILE = Path(__file__).resolve().parent.parent / "overlay_position.json"

COLORS = {
    "idle": "#6b7280",
    "recording": "#ef4444",
    "transcribing": "#f59e0b",
    "done": "#22c55e",
    "error": "#ef4444",
    "moving": "#38bdf8",
}

# Keeps the pill from taking focus away from the app you're dictating into.
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080


class Overlay:
    def __init__(self, level_source: Callable[[], float]):
        self.level_source = level_source
        self.events: queue.Queue[tuple] = queue.Queue()
        self.state = "idle"
        self.message = ""
        self._levels = [0.0] * BARS
        self.position = (0, 0)  # Set by _place once the root window exists.
        self.moving = False  # "Move overlay" mode: stay visible and ignore status updates.
        self._drag_offset: tuple[int, int] | None = None
        self._dragged = False

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        self.root.configure(bg="#0b0f19")

        self.canvas = tk.Canvas(
            self.root, width=WIDTH, height=HEIGHT, bg="#0b0f19", highlightthickness=0
        )
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.configure(cursor="fleur")
        self._place()
        self._make_non_activating()
        self.root.after(33, self._tick)

    # --- position --------------------------------------------------------

    def _default_position(self) -> tuple[int, int]:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        return (screen_w - WIDTH) // 2, screen_h - HEIGHT - BOTTOM_MARGIN

    def _place(self, position: tuple[int, int] | None = None) -> None:
        """Move the pill, tracking the position ourselves.

        `winfo_x`/`winfo_y` keep reporting the old spot while the window is withdrawn, which
        is exactly when the pill spends most of its life, so they cannot be trusted here.
        """
        self.position = position or self._load_position() or self._default_position()
        x, y = self.position
        self.root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        """Keep the pill reachable; a window dragged off-screen cannot be dragged back."""
        max_x = self.root.winfo_screenwidth() - WIDTH
        max_y = self.root.winfo_screenheight() - HEIGHT
        return max(0, min(x, max_x)), max(0, min(y, max_y))

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
        # Offsets within the window, so the pill doesn't jump to the cursor on the first move.
        self._drag_offset = (event.x, event.y)
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
        self.set_state("moving", "Drag me, then let go")

    # --- window style ----------------------------------------------------

    def _make_non_activating(self) -> None:
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, _GWL_EXSTYLE, style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW
            )
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    # --- thread-safe API -------------------------------------------------

    def set_state(self, state: str, message: str = "") -> None:
        self.events.put((state, message))

    def quit(self) -> None:
        self.events.put(("__quit__", ""))

    # --- Tk loop ---------------------------------------------------------

    def _tick(self) -> None:
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
            self.state = state
            self.message = message
            if state == "idle":
                self.root.withdraw()
            else:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
            if state in ("done", "error"):
                self.root.after(1200, lambda: self.set_state("idle"))

        if self.state != "idle":
            self._draw()
        self.root.after(33, self._tick)

    def _draw(self) -> None:
        self.canvas.delete("all")
        color = COLORS.get(self.state, COLORS["idle"])

        if self.state == "recording":
            # Scale RMS into something visible; speech usually sits well under 0.2.
            self._levels = self._levels[1:] + [min(1.0, self.level_source() * 8.0)]
            bar_w, gap = 4, 6
            total = BARS * gap
            x0 = (WIDTH - total) // 2
            mid = HEIGHT / 2
            for i, level in enumerate(self._levels):
                h = max(3.0, level * (HEIGHT - 14))
                x = x0 + i * gap
                self.canvas.create_rectangle(
                    x, mid - h / 2, x + bar_w, mid + h / 2, fill=color, outline=""
                )
        else:
            label = self.message or {"transcribing": "Transcribing...", "done": "Pasted"}.get(
                self.state, ""
            )
            self.canvas.create_oval(16, HEIGHT / 2 - 5, 26, HEIGHT / 2 + 5, fill=color, outline="")
            self.canvas.create_text(
                38,
                HEIGHT / 2,
                text=label[:38],
                anchor="w",
                fill="#e5e7eb",
                font=("Segoe UI", 10),
            )

    def run(self) -> None:
        self.root.mainloop()
