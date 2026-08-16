"""Per-pixel-alpha windows via UpdateLayeredWindow.

Tk gives us a window, an event loop and input handling but cannot draw a soft edge. These
helpers let Pillow supply the pixels — alpha channel included — for a window Tk still owns.

The one non-obvious rule: the bitmap must be *premultiplied* BGRA (Pillow's "BGRa" raw mode).
Straight alpha puts a bright halo around every antialiased edge.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020  # Click-through: the window never sees the mouse at all.
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

ULW_ALPHA = 2
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
SRCCOPY = 0x00CC0020
# Nearest-neighbour. HALFTONE interpolates, but measures 6.8ms against 0.9ms per fullscreen
# stretch, and the source is a heavily blurred image where the difference does not show.
STRETCH_FAST = 3


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte),
    ]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long), ("top", ctypes.c_long),
        ("right", ctypes.c_long), ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)
    ]


def window_handle(widget) -> int:
    """The real top-level HWND for a Tk widget."""
    return user32.GetParent(widget.winfo_id()) or widget.winfo_id()


def make_layered(hwnd: int, click_through: bool = False) -> None:
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    if click_through:
        style |= WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


class Surface:
    """A reusable 32-bit DIB you can push to a layered window.

    Reused rather than rebuilt per frame: allocating a fullscreen DIB every tick is pure waste
    during an animation.
    """

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._screen_dc = user32.GetDC(0)
        self.dc = gdi32.CreateCompatibleDC(self._screen_dc)
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # Negative: top-down, matching Pillow's row order.
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        self._bits = ctypes.c_void_p()
        self._bitmap = gdi32.CreateDIBSection(
            self.dc, ctypes.byref(info), 0, ctypes.byref(self._bits), None, 0
        )
        self._previous = gdi32.SelectObject(self.dc, self._bitmap)
        gdi32.SetStretchBltMode(self.dc, STRETCH_FAST)

    def load(self, image) -> None:
        """Copy a Pillow RGBA image into the bitmap. Dimensions must match."""
        raw = image.tobytes("raw", "BGRa")
        ctypes.memmove(self._bits, raw, len(raw))

    def stretch_from(self, other: "Surface") -> None:
        """Scale another surface across this one — the cheap way to fill a display."""
        gdi32.StretchBlt(
            self.dc, 0, 0, self.width, self.height,
            other.dc, 0, 0, other.width, other.height, SRCCOPY,
        )

    def push(self, hwnd: int) -> None:
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(
            hwnd,
            self._screen_dc,
            None,  # Position stays Tk's business; only the pixels are ours.
            ctypes.byref(SIZE(self.width, self.height)),
            self.dc,
            ctypes.byref(POINT(0, 0)),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )

    def close(self) -> None:
        gdi32.SelectObject(self.dc, self._previous)
        gdi32.DeleteObject(self._bitmap)
        gdi32.DeleteDC(self.dc)
        user32.ReleaseDC(0, self._screen_dc)
