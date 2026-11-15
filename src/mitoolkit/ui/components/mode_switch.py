"""A two-way mode selector: a segmented pill, "USB | Wireless". Used for choosing how phones are reached.

Why not a toggle switch: a switch turns one thing on or off, so with a name on each side it is unclear which side is
"on" and what a click will do. Here both choices are always visible inside one pill, the chosen one rides on a white
thumb that slides to it, and each choice is clicked directly. The chosen name is dark and bold with a blue glyph (a
plug for USB, the Wi-Fi symbol for Wireless); the other is grey, so colour is never the only signal. A faint tint
shows the segment under the pointer.

Keyboard: Left and Right (also Home and End, Up and Down) choose; Space and Enter flip to the other one. It has one
tab stop and a blue focus ring with a gap, shown for the keyboard only, never after a mouse click. One variable holds
the chosen value, as with the selector bar. It is drawn anti-aliased at several times its size (Pillow, like the
charts) and scaled to the screen's DPI. With reduced motion (MITOOLKIT_REDUCED_MOTION=1) the thumb jumps. Without
Pillow a plainer canvas drawing is used.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, Optional, Tuple

from mitoolkit.ui.components import render, skeleton
from mitoolkit.ui.components.shapes import page_background

HEIGHT = 34                                 # the pill's height at 96 dpi; everything scales with the screen
PAD = 3                                     # between the pill's edge and the thumb
GLYPH = 16                                  # the width given to a glyph
SEG_PAD = 12                                # space either side of a segment's content
MARGIN = 7                                  # room around the pill for the focus ring
FRAMES, FRAME_MS = 12, 16
TEXT, MUTED_TEXT = "#1b1b1b", "#555555"
TRACK, BORDER = "#e5e7eb", "#6b7280"        # the pill and its outline (the outline is 3:1 or better on the page)
THUMB = "#ffffff"
ACTIVE, INACTIVE = "#2f5bff", "#6b7280"     # glyph colours: the chosen one blue, the other grey
RING = "#2f5bff"


class ModeSwitch(tk.Canvas):
    def __init__(self, parent, variable: tk.Variable, first: Tuple[object, str], second: Tuple[object, str],
                 command: Optional[Callable[[], None]] = None, font: Optional[tkfont.Font] = None):
        """``first`` and ``second`` are (value, name) for the left and right segment; ``variable`` holds the chosen value."""
        self._bg = page_background(parent)
        super().__init__(parent, bg=self._bg, highlightthickness=0, borderwidth=0, takefocus=True, cursor="hand2")
        self.choices = (first, second)
        self.variable, self.command = variable, command
        self._font = font or tkfont.nametofont("TkDefaultFont")
        self._bold = self._font.copy()
        self._bold.configure(weight="bold")
        self._pos = float(self._index())                # 0 = first, 1 = second (animated)
        self._anim: Optional[str] = None
        self._image = None                              # the picture of the pill (kept referenced while shown)
        self._focus = self._mouse = False
        self._hover = -1
        self._k = max(1.0, self.winfo_fpixels("1i") / 96.0)        # the screen's scale: 1.0 at 96 dpi, 1.5 at 150 %
        self._measure()
        for seq, fn in (("<Configure>", lambda e: self.draw()), ("<ButtonPress-1>", lambda e: self._press()),
                        ("<ButtonRelease-1>", self._release), ("<Motion>", self._motion), ("<Leave>", self._leave),
                        ("<FocusIn>", lambda e: self._focused(True)), ("<FocusOut>", lambda e: self._focused(False)),
                        ("<Left>", lambda e: self._step(-1)), ("<Up>", lambda e: self._step(-1)),
                        ("<Right>", lambda e: self._step(1)), ("<Down>", lambda e: self._step(1)),
                        ("<Home>", lambda e: self._step(-1)), ("<End>", lambda e: self._step(1)),
                        ("<space>", lambda e: self._flip()), ("<Return>", lambda e: self._flip()),
                        ("<Destroy>", self._on_destroy)):
            self.bind(seq, fn)
        self._trace = variable.trace_add("write", lambda *_: self._slide())
        self.draw()

    def _measure(self) -> None:
        k = self._k
        text_w = max(self._bold.measure(label) for _v, label in self.choices)
        self._pad, self._margin = round(PAD * k), round(MARGIN * k)
        self._glyph, self._seg_pad = round(GLYPH * k), round(SEG_PAD * k)
        self._seg_w = self._seg_pad + self._glyph + round(7 * k) + text_w + self._seg_pad
        self._pill_w = 2 * self._seg_w + 2 * self._pad
        self._pill_h = round(HEIGHT * k)
        self.configure(width=self._pill_w + 2 * self._margin, height=self._pill_h + 2 * self._margin)

    # ---------------------------------------------------------------------------------------------- state
    def _index(self) -> int:
        return 1 if self.variable.get() == self.choices[1][0] else 0

    def select(self, index: int) -> None:
        """Choose segment 0 or 1; nothing happens if it is already chosen."""
        if index != self._index():
            self.variable.set(self.choices[index][0])        # the trace slides the thumb
            if self.command:
                self.command()

    def _flip(self) -> str:
        self._mouse = False
        self.select(1 - self._index())
        return "break"

    def _step(self, delta: int) -> str:
        self._mouse = False
        self.select(max(0, min(1, self._index() + delta)))
        return "break"

    def _segment_at(self, x: int) -> int:
        return 0 if x < self._margin + self._pad + self._seg_w else 1

    def _press(self) -> None:
        self._mouse = True                                  # a click is not keyboard use: no focus ring

    def _release(self, event) -> None:
        if 0 <= event.x <= int(self.cget("width")) and 0 <= event.y <= int(self.cget("height")):
            self.select(self._segment_at(event.x))
        self.winfo_toplevel().focus_set()
        self.draw()

    def _motion(self, event) -> None:
        over = self._segment_at(event.x)
        hover = over if over != self._index() else -1       # the chosen one needs no hint
        if hover != self._hover:
            self._hover = hover
            self.draw()

    def _leave(self, _event) -> None:
        self._hover = -1
        self.draw()

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
        self._image = None

    # ------------------------------------------------------------------------------------------ animation
    def _slide(self) -> None:
        """Ease the thumb to the chosen segment (or jump, with reduced motion)."""
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                return
            self._anim = None
        end = float(self._index())
        if skeleton.REDUCED:
            self._pos = end
            self.draw()
            return
        start = self._pos

        def step(i: int) -> None:
            x = i / FRAMES
            self._pos = start + (end - start) * (x * x * (3 - 2 * x))             # ease in and out
            self.draw()
            self._anim = self.after(FRAME_MS, step, i + 1) if i < FRAMES else None
        step(1)

    # ---------------------------------------------------------------------------------------------- drawing
    def _glyph_centres(self):
        return [self._pad + i * self._seg_w + self._seg_pad + self._glyph / 2 for i in (0, 1)]

    def draw(self) -> None:
        c = self
        c.delete("all")
        chosen = self._index()
        mid = self._margin + self._pill_h // 2
        ring = RING if (self._focus and not self._mouse) else ""      # keyboard focus ring, with a gap
        centres = self._glyph_centres()
        glyphs = [(("usb", "wifi")[i], centres[i], ACTIVE if i == chosen else INACTIVE) for i in (0, 1)]   # plug, Wi-Fi
        if render.HAVE:
            self._image = render.segmented_photo(self._pill_w, self._pill_h, self._seg_w, self._pad, self._pos,
                                                 self._hover, TRACK, BORDER, THUMB, tuple(glyphs), ring, self._margin,
                                                 self._k)
            c.create_image(0, 0, image=self._image, anchor="nw")
            if ring:
                c.addtag_withtag("ring", c.find_all()[-1])
        else:
            self._plain(chosen, ring)
        for i, (_value, label) in enumerate(self.choices):
            x = self._margin + self._pad + i * self._seg_w + self._seg_pad + self._glyph + round(7 * self._k)
            c.create_text(x, mid, text=label, anchor="w", fill=TEXT if i == chosen else MUTED_TEXT,
                          font=self._bold if i == chosen else self._font)

    def _plain(self, chosen: int, ring: str) -> None:
        """Without Pillow: the same selector with plain canvas shapes (jagged edges, no glyphs)."""
        m, h = self._margin, self._pill_h
        if ring:
            self.create_rectangle(m // 2, m // 2, m + self._pill_w + m // 2, m + h + m // 2, outline=ring, width=2,
                                  tags="ring")
        self.create_rectangle(m, m, m + self._pill_w, m + h, fill=TRACK, outline=BORDER)
        left = m + self._pad + self._seg_w * self._pos
        self.create_rectangle(left, m + self._pad, left + self._seg_w, m + h - self._pad, fill=THUMB, outline=BORDER)
