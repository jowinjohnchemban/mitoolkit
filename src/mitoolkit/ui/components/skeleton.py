"""Skeleton loading placeholders, like React skeleton libraries and Tailwind's animate-pulse: grey
shapes in the layout of the content to come, with a soft light wave sweeping across them and a slow
pulse, so a waiting screen looks alive and the page doesn't jump when the data arrives.

One shared clock drives every skeleton on screen (about 25 frames a second) and stops by itself
when none is left. Skeletons (and the selector bar's slide) stand still when the user prefers reduced
motion: MITOOLKIT_REDUCED_MOTION=1, or Windows' "Show animations" setting turned off.
Anything that shows a skeleton also says in words what it is waiting for.
"""
from __future__ import annotations

import math
import os
import sys
import time
import tkinter as tk
import weakref
from typing import Optional, Sequence

from mitoolkit.ui.components.shapes import mix, page_background, rounded

BASE = "#e6e8ec"       # Tailwind gray-200-ish
HIGHLIGHT = "#f6f7f9"  # the wave
PERIOD = 1.6           # seconds for one sweep
FRAME_MS = 40


def prefers_reduced_motion() -> bool:
    """True if the user turned animation off: MITOOLKIT_REDUCED_MOTION=1, or (on Windows) the system
    setting "Show animations in Windows" is off. WCAG 2.3.3 asks us to respect that."""
    if os.environ.get("MITOOLKIT_REDUCED_MOTION", "") not in ("", "0"):
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            enabled = ctypes.c_int(1)
            SPI_GETCLIENTAREAANIMATION = 0x1042
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0):
                return not enabled.value
        except Exception:
            pass
    return False


REDUCED = prefers_reduced_motion()


def sweep() -> float:
    """Where the light wave is, 0 to 1 across the element (repeats every PERIOD seconds)."""
    return 0.0 if REDUCED else (time.monotonic() % PERIOD) / PERIOD


def pulse() -> float:
    """0 to 1 and back, smoothly (Tailwind's animate-pulse)."""
    return 0.0 if REDUCED else 0.5 - 0.5 * math.cos(2 * math.pi * (time.monotonic() % (PERIOD * 1.25)) / (PERIOD * 1.25))


def bar_colour(position: float, strength: float = 1.0) -> str:
    """Colour of a skeleton bar at `position` (0 to 1 across the element): grey, lightened by the
    passing wave and breathing slightly with the pulse."""
    centre = -0.25 + 1.5 * sweep()
    wave = math.exp(-((position - centre) ** 2) / 0.018) * strength
    return mix(mix(BASE, HIGHLIGHT, 0.35 * pulse()), HIGHLIGHT, min(1.0, wave))


class _Clock:
    """One timer for all the skeletons: it calls draw() on each watcher that is still loading."""

    def __init__(self) -> None:
        # weak references: the clock must never keep a closed window's charts alive
        self._watching: "weakref.WeakSet[tk.Misc]" = weakref.WeakSet()
        self._job: Optional[str] = None
        self._root: Optional[tk.Misc] = None

    def watch(self, widget: tk.Misc) -> None:
        self._watching.add(widget)
        if self._job is None and not REDUCED:
            self._root = widget.winfo_toplevel()
            self._job = self._root.after(FRAME_MS, self._tick)

    def _tick(self) -> None:
        # Mark "a tick is running" for the whole tick. A widget's draw() calls watch() again; if that
        # saw no timer it would start a second one, and every tick would double the number of timers
        # until the window did nothing but animate (the freeze this guards against).
        self._job = "running"
        started = time.perf_counter()
        for widget in list(self._watching):
            try:
                if not widget.winfo_exists() or not getattr(widget, "loading", True):
                    self._watching.discard(widget)
                elif widget.winfo_ismapped():
                    widget.draw()
            except tk.TclError:
                self._watching.discard(widget)
            except Exception:  # an animation must never take the window down: stop animating that one
                self._watching.discard(widget)
        if self._watching and self._root is not None:
            # Animate for at most about a quarter of the time: if a frame was slow (many placeholders
            # on a slow machine), wait longer before the next, so the window stays responsive.
            spent_ms = (time.perf_counter() - started) * 1000
            delay = int(min(250, max(FRAME_MS, spent_ms * 3)))
            try:
                self._job = self._root.after(delay, self._tick)
            except tk.TclError:
                self._watching.clear()
                self._job = None
        else:
            self._job = None                    # nothing left to animate: the timer stops


clock = _Clock()


class Skeleton(tk.Canvas):
    """Rows of rounded grey bars that shimmer: the placeholder for lines of text or a list.

    rows: how many bars; widths: each bar's width as a fraction of the space (repeats);
    heights: bar height in pixels."""

    def __init__(self, parent, rows: int = 4, widths: Sequence[float] = (0.92, 0.7, 0.84, 0.5), bar: int = 12,
                 gap: int = 12, label: str = "Loading..."):
        super().__init__(parent, bg=page_background(parent), highlightthickness=0, borderwidth=0,
                         height=rows * (bar + gap) - gap + 4, width=200)
        self.rows, self.widths, self.bar, self.gap = rows, tuple(widths), bar, gap
        self.loading = True
        self.label = label  # for screen readers and tests: what we are waiting for
        self.bind("<Configure>", lambda _e: self.draw())
        clock.watch(self)

    def start(self) -> None:
        self.loading = True
        clock.watch(self)

    def stop(self) -> None:
        self.loading = False

    def draw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        if w < 20:
            return
        for i in range(self.rows):
            y0 = 2 + i * (self.bar + self.gap)
            x1 = max(24, w * self.widths[i % len(self.widths)] - 4)
            self._bar(2, y0, x1, y0 + self.bar, w)

    def _bar(self, x0: float, y0: float, x1: float, y1: float, total: float) -> None:
        """One rounded bar: grey, with the wave drawn as a few lighter slices over it."""
        r = (y1 - y0) / 2
        rounded(self, x0, y0, x1, y1, r, fill=bar_colour(-1), outline="")
        slices = 12
        left, right = x0 + r, x1 - r
        if right <= left:
            return
        width = (right - left) / slices
        for k in range(slices):
            sx = left + k * width
            centre = (sx + width / 2) / max(total, 1)
            self.create_rectangle(sx, y0, sx + width + 1, y1, fill=bar_colour(centre), outline="")
