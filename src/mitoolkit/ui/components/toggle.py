"""A toggle switch for a choice between two things such as USB and Wireless: a vivid blue pill with a white thumb.

A clean gray pill with a white thumb that has a soft shadow and a small glyph of what is chosen: a USB plug for
the first choice, the Wi-Fi symbol for the second. Switched on, the pill turns blue and the thumb slides right;
pressing it stretches the thumb a little, as on a phone. The two names sit either side, the chosen one dark and
bold, so colour is never the only signal. A hover darkens the pill.

It is drawn anti-aliased at several times its size (Pillow, like the charts) and scaled to the screen's DPI, so it is
sharp on a high-DPI display. Without Pillow a plainer canvas drawing is used.

Click anywhere on it, or press Space or Enter when it has the keyboard focus (a blue ring with a gap around the pill
shows for the keyboard, never after a mouse click). One variable holds the chosen value, as with the selector bar.
With reduced motion (MITOOLKIT_REDUCED_MOTION=1) the thumb jumps instead of sliding.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, Optional, Tuple

from mitoolkit.ui.components import render, skeleton
from mitoolkit.ui.components.shapes import mix, page_background

TRACK_W, TRACK_H = 50, 30                   # design sizes in pixels at 96 dpi; everything scales with the screen
THUMB = 24
PAD = 3                                     # the gap between the thumb and the track's edge
STRETCH = 4                                 # the thumb gets this much wider while pressed
GAP = 12                                    # between a name and the switch
HEIGHT = 46
MARGIN = 8                                  # room around the pill for the focus ring
FRAMES, FRAME_MS = 12, 16
TEXT, MUTED_TEXT = "#1b1b1b", "#555555"
OFF_TRACK, OFF_HOVER = "#d1d5db", "#c3c8d0"  # gray-300, a touch darker on hover
OFF_BORDER = "#6b7280"                      # gray-500: the off pill's outline and glyph (3:1 or better on the page)
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
        self._image = None                              # the picture of the switch (kept referenced while shown)
        self._focus = self._mouse = self._hover = self._pressed = False
        self._k = max(1.0, self.winfo_fpixels("1i") / 96.0)        # the screen's scale: 1.0 at 96 dpi, 1.5 at 150 %
        self._measure()
        for seq, fn in (("<Configure>", lambda e: self.draw()), ("<ButtonPress-1>", self._on_press),
                        ("<ButtonRelease-1>", self._on_release), ("<Enter>", lambda e: self._set(hover=True)),
                        ("<Leave>", lambda e: self._set(hover=False)), ("<FocusIn>", lambda e: self._focused(True)),
                        ("<FocusOut>", lambda e: self._focused(False)), ("<space>", self._key), ("<Return>", self._key),
                        ("<Destroy>", self._on_destroy)):
            self.bind(seq, fn)
        self._trace = variable.trace_add("write", lambda *_: self._slide())
        self.draw()

    def _measure(self) -> None:
        """Sizes in device pixels for this screen, and the control's own size."""
        k = self._k
        self._tw, self._th = round(TRACK_W * k), round(TRACK_H * k)
        self._thumb, self._pad, self._stretch = round(THUMB * k), round(PAD * k), round(STRETCH * k)
        self._gap, self._height, self._margin = round(GAP * k), round(HEIGHT * k), round(MARGIN * k)
        self._left_w = self._bold.measure(self.off[1])
        self._right_w = self._bold.measure(self.on[1])
        self.configure(width=round(5 * k) + self._left_w + self._gap + self._tw + self._gap + self._right_w + round(10 * k),
                       height=self._height)

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
        if 0 <= event.x <= int(self.cget("width")) and 0 <= event.y <= self._height:
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
        self._image = None

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
            self._pos = start + (end - start) * (x * x * (3 - 2 * x))             # ease in and out
            self.draw()
            self._anim = self.after(FRAME_MS, step, i + 1) if i < FRAMES else None
        step(1)

    # ---------------------------------------------------------------------------------------------- drawing
    def draw(self) -> None:
        c = self
        c.delete("all")
        on = self._is_on()
        t = self._pos
        mid = self._height // 2
        k = self._k
        x0 = round(5 * k) + self._left_w + self._gap
        # the two names: the chosen one dark and bold
        c.create_text(round(5 * k), mid, text=self.off[1], anchor="w", fill=MUTED_TEXT if on else TEXT,
                      font=self._font if on else self._bold)
        c.create_text(x0 + self._tw + self._gap, mid, text=self.on[1], anchor="w", fill=TEXT if on else MUTED_TEXT,
                      font=self._bold if on else self._font)
        # the pill: gray, blue when on (blending as the thumb moves), a touch darker under the pointer
        off_fill, on_fill = (OFF_HOVER, ON_HOVER) if self._hover else (OFF_TRACK, ON_TRACK)
        fill, border = mix(off_fill, on_fill, t), mix(OFF_BORDER, on_fill, t)
        ring = ON_TRACK if (self._focus and not self._mouse) else ""      # keyboard focus ring, with a gap
        stretch = self._stretch if self._pressed else 0
        top = mid - self._th // 2
        if render.HAVE:
            self._image = render.toggle_photo(self._tw, self._th, t, fill, border, KNOB_ON, self._thumb, self._pad,
                                              stretch, "usb" if t < 0.5 else "wifi", OFF_BORDER if t < 0.5 else ON_TRACK,
                                              ring, self._margin, k)
            c.create_image(x0 - self._margin, top - self._margin, image=self._image, anchor="nw")
            if ring:
                c.addtag_withtag("ring", c.find_all()[-1])
            return
        self._plain(x0, top, fill, border, ring, stretch, t)

    def _plain(self, x0: int, top: int, fill: str, border: str, ring: str, stretch: int, t: float) -> None:
        """Without Pillow: the same switch with plain canvas shapes (they have jagged edges and no glyph)."""
        c, h = self, self._th
        if ring:
            gap = self._margin // 2
            c.create_rectangle(x0 - gap, top - gap, x0 + self._tw + gap, top + h + gap, outline=ring, width=2, tags="ring")
        for colour, inset in ((border, 0), (fill, 1)):
            c.create_oval(x0 + inset, top + inset, x0 + h - inset, top + h - inset, fill=colour, outline=colour)
            c.create_oval(x0 + self._tw - h + inset, top + inset, x0 + self._tw - inset, top + h - inset, fill=colour, outline=colour)
            c.create_rectangle(x0 + h / 2, top + inset, x0 + self._tw - h / 2, top + h - inset, fill=colour, outline=colour)
        left = x0 + self._pad + (self._tw - self._thumb - 2 * self._pad) * t - stretch * t
        c.create_oval(left, top + (h - self._thumb) / 2, left + self._thumb + stretch, top + (h + self._thumb) / 2,
                      fill=KNOB_ON, outline=mix(fill, "#000000", 0.12))
