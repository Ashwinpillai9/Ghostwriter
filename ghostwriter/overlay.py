"""Always-on-top status pill. Owns the Tk main loop, so it must live on the main thread."""

from __future__ import annotations

import ctypes
import queue
import tkinter as tk
from collections.abc import Callable

BARS = 21
WIDTH = 260
HEIGHT = 46
BOTTOM_MARGIN = 120

COLORS = {
    "idle": "#6b7280",
    "recording": "#ef4444",
    "transcribing": "#f59e0b",
    "done": "#22c55e",
    "error": "#ef4444",
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
        self._place()
        self._make_click_through()
        self.root.after(33, self._tick)

    def _place(self) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - WIDTH) // 2
        y = screen_h - HEIGHT - BOTTOM_MARGIN
        self.root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

    def _make_click_through(self) -> None:
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
