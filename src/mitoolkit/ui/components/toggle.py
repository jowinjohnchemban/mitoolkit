"""A toggle switch in the style of Tailwind UI's switches, for a choice between two things such as USB and Wireless.

A clean gray pill with a plain white thumb that has a soft shadow. Switched on, the pill turns a vivid blue and the
thumb slides right; pressing it stretches the thumb a little, as on a phone. The two names sit either side, the
chosen one dark and bold, so colour is never the only signal. A hover darkens the pill.

Click anywhere on it, or press Space or Enter when it has the keyboard focus (a blue ring with a gap around the pill
shows for the keyboard, never after a mouse click). One variable holds the chosen value, as with the selector bar.
With reduced motion (MITOOLKIT_REDUCED_MOTION=1) the thumb jumps instead of sliding.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, Optional, Tuple

from mitoolkit.ui.components import skeleton
from mitoolkit.ui.components.shapes import mix, page_background, rounded

TRACK_W, TRACK_H = 50, 30
THUMB = 24
PAD = 3                                     # the gap between the thumb and the track's edge
STRETCH = 4                                 # the thumb gets this much wider while pressed
GAP = 12                                    # between a name and the switch
HEIGHT = 44
FRAMES, FRAME_MS = 12, 16
TEXT, MUTED_TEXT = "#1b1b1b", "#555555"
OFF_TRACK, OFF_HOVER = "#d1d5db", "#c3c8d0"  # gray-300, a touch darker on hover
OFF_BORDER = "#6b7280"                      # gray-500: the off pill's outline (3:1 or better on the page)
ON_TRACK, ON_HOVER = "#2f5bff", "#2449d9"    # a vivid blue, a touch deeper on hover
KNOB_ON = "#ffffff"                         # the thumb


class ToggleSwitch(tk.Canvas):
    def __init__(self, parent, variable: tk.Variable, off: Tuple[object, str], on: Tuple[object, str],
                 command: Optional[Callable[[], None]] = None, font: Optional[tkfont.Font] = None):
        """``off`` and ``on`` are (value, name): the value the variable has when the thumb is left or right."""
        self._bg = page_background(parent)
        super().__init__(parent, bg=self._bg, highlightthickness=0, borderwidth=0, takefocus=True, cursor="hand2")
        self.off, self.on = off, on
        self.variable, self.command = variable, command
        self._font = font or tkfont.nametofont("TkDefaultFont")
        self._bold = self._font.copy()
        self._bold.configure(weight="bold")
        self._pos = 1.0 if self._is_on() else 0.0       # 0 = thumb left, 1 = thumb right (animated)
        self._anim: Optional[str] = None
        self._focus = self._mouse = self._hover = self._pressed = False
        self._left_w = self._bold.measure(off[1])
        self._right_w = self._bold.measure(on[1])
        self.configure(width=self._left_w + GAP + TRACK_W + GAP + self._right_w + 10, height=HEIGHT)
        for seq, fn in (("<Configure>", lambda e: self.draw()), ("<ButtonPress-1>", self._on_press),
                        ("<ButtonRelease-1>", self._on_release), ("<Enter>", lambda e: self._set(hover=True)),
                        ("<Leave>", lambda e: self._set(hover=False)), ("<FocusIn>", lambda e: self._focused(True)),
                        ("<FocusOut>", lambda e: self._focused(False)), ("<space>", self._key), ("<Return>", self._key),
                        ("<Destroy>", self._on_destroy)):
            self.bind(seq, fn)
        self._trace = variable.trace_add("write", lambda *_: self._slide())
        self.draw()

    # ---------------------------------------------------------------------------------------------- state
    def _is_on(self) -> bool:
        return self.variable.get() == self.on[0]

    def toggle(self) -> None:
        """Flip to the other choice (what a click or a key does)."""
        self.variable.set(self.off[0] if self._is_on() else self.on[0])     # the trace slides the thumb
        if self.command:
            self.command()

    def _set(self, hover: Optional[bool] = None, pressed: Optional[bool] = None) -> None:
        if hover is not None:
            self._hover = hover
        if pressed is not None:
            self._pressed = pressed
        self.draw()

    def _on_press(self, _event) -> None:
        self._mouse = True                                  # a click is not keyboard use: no focus ring
        self._set(pressed=True)

    def _on_release(self, event) -> None:
        self._pressed = False
        if 0 <= event.x <= int(self.cget("width")) and 0 <= event.y <= HEIGHT:
            self.toggle()
        self.winfo_toplevel().focus_set()
        self.draw()

    def _key(self, _event) -> str:
        self._mouse = False
        self.toggle()
        return "break"

    def _focused(self, on: bool) -> None:
        self._focus = on
        if not on:
            self._mouse = False
        self.draw()

    def _on_destroy(self, event) -> None:
        if event.widget is not self:
            return
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                # the timer already fired or the window is gone
                pass
        try:  # the variable outlives this widget: take our callback off it, or it keeps us (and the window) alive
            self.variable.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            # the trace is already off the variable
            pass
        self.command = None

    # ------------------------------------------------------------------------------------------ animation
    def _slide(self) -> None:
        """Ease the thumb to the chosen side (or jump, with reduced motion)."""
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                return
            self._anim = None
        end = 1.0 if self._is_on() else 0.0
        if skeleton.REDUCED:
            self._pos = end
            self.draw()
            return
        start = self._pos

        def step(i: int) -> None:
            x = i / FRAMES
            self._pos = start + (end - start) * (x * x * (3 - 2 * x))             # ease in and out, like Tailwind's
            self.draw()
            self._anim = self.after(FRAME_MS, step, i + 1) if i < FRAMES else None
        step(1)

    # ---------------------------------------------------------------------------------------------- drawing
    def draw(self) -> None:
        c = self
        c.delete("all")
        on = self._is_on()
        t = self._pos
        mid = HEIGHT // 2
        x0 = 5 + self._left_w + GAP
        # the two names: the chosen one dark and bold
        c.create_text(5, mid, text=self.off[1], anchor="w", fill=MUTED_TEXT if on else TEXT,
                      font=self._font if on else self._bold)
        c.create_text(x0 + TRACK_W + GAP, mid, text=self.on[1], anchor="w", fill=TEXT if on else MUTED_TEXT,
                      font=self._bold if on else self._font)
        # the pill: gray, blue when on (blending as the thumb moves), a touch darker under the pointer
        off_fill, on_fill = (OFF_HOVER, ON_HOVER) if self._hover else (OFF_TRACK, ON_TRACK)
        fill = mix(off_fill, on_fill, t)
        top, bottom = mid - TRACK_H // 2, mid + TRACK_H // 2
        if self._focus and not self._mouse:                 # ring with a gap, like Tailwind's ring-2 ring-offset-2
            rounded(c, x0 - 4, top - 4, x0 + TRACK_W + 4, bottom + 4, TRACK_H // 2 + 4, fill="", outline=ON_TRACK,
                    width=2, tags="ring")
        self._capsule(x0, top, x0 + TRACK_W, bottom, mix(OFF_BORDER, on_fill, t))          # outline, then the fill
        self._capsule(x0 + 1, top + 1, x0 + TRACK_W - 1, bottom - 1, fill)
        # the white thumb with a soft shadow; pressed, it stretches towards the side it is moving to
        stretch = STRETCH if self._pressed else 0
        left = x0 + PAD + (TRACK_W - THUMB - 2 * PAD) * t - (stretch * t)
        right = left + THUMB + stretch
        ty = mid - THUMB // 2
        c.create_oval(left, ty + 1.5, right, ty + THUMB + 1.5, fill=mix(fill, "#000000", 0.22), outline="")   # shadow
        c.create_oval(left, ty, right, ty + THUMB, fill=KNOB_ON, outline=mix(fill, "#000000", 0.08))

    def _capsule(self, x0: float, y0: float, x1: float, y1: float, colour: str) -> None:
        """A true pill: two half circles and a bar between them (a smoothed polygon looks chamfered when small)."""
        h = y1 - y0
        self.create_oval(x0, y0, x0 + h, y1, fill=colour, outline=colour)
        self.create_oval(x1 - h, y0, x1, y1, fill=colour, outline=colour)
        self.create_rectangle(x0 + h / 2, y0, x1 - h / 2, y1 + 0.5, fill=colour, outline=colour)
