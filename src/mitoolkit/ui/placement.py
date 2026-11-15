"""Put windows where they fit: inside the part of the screen the system leaves free.

Every desktop reserves space (the Windows taskbar, the macOS menu bar and Dock, Linux panels),
and a window that overlaps it hides its own buttons or sits under the bar. We ask the system
for the free "work area" where it will tell us (Windows, and Linux window managers that publish
_NET_WORKAREA) and otherwise keep a safe margin. After the window is on screen we measure its
real outer frame (title bar, menu, borders) and shrink or move it if any of it is outside.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Tuple

Rect = Tuple[int, int, int, int]  # x, y, width, height

# Used when the system will not say. Generous, because covering the controls is worse than a
# window that is a little smaller.
MAC_MARGINS = (28, 90, 12, 12)      # top (menu bar), bottom (Dock), left, right
OTHER_MARGINS = (36, 64, 8, 8)      # top and bottom panels
FRAME_EXTRA = 12                    # window border below the client area


def _windows_work_area() -> Rect:
    import ctypes
    import ctypes.wintypes as wintypes
    rect = wintypes.RECT()
    if not ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
        raise OSError("no work area")
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _x11_work_area() -> Rect:
    out = subprocess.run(["xprop", "-root", "_NET_WORKAREA"], capture_output=True, text=True, timeout=2).stdout
    nums = [int(n) for n in out.split("=", 1)[1].replace(",", " ").split()[:4]]
    if len(nums) != 4 or nums[2] < 200 or nums[3] < 200:
        raise ValueError("bad work area")
    return nums[0], nums[1], nums[2], nums[3]


def work_area(win) -> Rect:
    """(x, y, width, height) of the screen not covered by the taskbar, menu bar, Dock or panels."""
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    try:
        if sys.platform == "win32":
            return _windows_work_area()
        if sys.platform != "darwin":
            return _x11_work_area()
    except Exception:
        # the system will not say where the taskbar is: a safe margin is used instead (below)
        pass
    top, bottom, left, right = MAC_MARGINS if sys.platform == "darwin" else OTHER_MARGINS
    return left, top, sw - left - right, sh - top - bottom


def fit_to_screen(win, width: int, height: int, parent=None) -> None:
    """Size a window to at most width x height, no larger than the work area, and centre it
    there. Windows are centred on the screen, not on the main window."""
    win.update_idletasks()
    ax, ay, aw, ah = work_area(win)
    frame = 90  # title bar, menu bar and borders, until we can measure them
    w, h = min(width, aw - 16), min(height, ah - frame)
    x, y = ax + (aw - w) // 2, ay + (ah - h - frame // 2) // 2
    win.geometry(f"{w}x{h}+{max(ax, x)}+{max(ay, y)}")
    win.after(80, lambda: keep_in_work_area(win))


def keep_in_work_area(win) -> None:
    """Once the window is on screen, measure its real frame and pull it fully inside."""
    try:
        if not win.winfo_exists() or not win.winfo_ismapped():
            return
        win.update_idletasks()
        ax, ay, aw, ah = work_area(win)
        top_frame = max(0, win.winfo_rooty() - win.winfo_y())       # title bar (and menu bar)
        w, h = win.winfo_width(), win.winfo_height()
        x, y = win.winfo_x(), win.winfo_y()
        outer_h = top_frame + h + FRAME_EXTRA
        if outer_h > ah:                                            # too tall: shrink the content
            h -= outer_h - ah
            outer_h = ah
        if w > aw:
            w = aw
        x = min(max(x, ax), ax + aw - w)
        y = min(max(y, ay), ay + ah - outer_h)
        win.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        pass  # placement is a courtesy; never break the window over it
