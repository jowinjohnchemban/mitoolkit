"""A Windows 11 style selector bar (WinUI's SelectorBar / Pivot): plain text choices in a row, the
chosen one in dark text with a short accent bar under it that slides to the new choice. Used for
the time range and the tabs. On macOS the system's own toggle buttons are used instead (see
buttons.segmented).

One widget for the whole group and a single tab stop: Left and Right (also Home and End) change
the choice. The chosen option is also shown in darker, bolder text, so the accent bar is never
the only signal. With reduced motion (MITOOLKIT_REDUCED_MOTION=1) the bar jumps instead of sliding.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, List, Optional, Sequence, Tuple

from mitoolkit.ui.components.shapes import page_background, rounded
from mitoolkit.ui.components.skeleton import REDUCED
from mitoolkit.ui.theme import ACCENT

HEIGHT = 38
PAD_X = 16          # space either side of a label
BAR_H = 3           # the accent indicator
FRAMES, FRAME_MS = 8, 16
TEXT, MUTED_TEXT = "#1b1b1b", "#555555"
HOVER_FILL = "#e8e8e8"


class SelectorBar(tk.Canvas):
    def __init__(self, parent, choices: Sequence[Tuple[object, str]], variable: tk.Variable,
                 command: Optional[Callable[[], None]] = None, font: Optional[tkfont.Font] = None):
        self._bg = page_background(parent)
        super().__init__(parent, bg=self._bg, highlightthickness=0, borderwidth=0, takefocus=True, cursor="hand2")
        self.values: List[object] = [v for v, _l in choices]
        self.labels: List[str] = [l for _v, l in choices]
        self.variable, self.command = variable, command
        self._font = font or tkfont.nametofont("TkDefaultFont")
        self._bold = self._font.copy()
        self._bold.configure(weight="bold")
        self._bar_x: Optional[float] = None      # the indicator's left edge now (animated)
        self._anim: Optional[str] = None
        self._hover: Optional[int] = None
        self._focus = False
        self._mouse = False
        self._fit()
        self._bar_x = self._target_x()
        for seq, fn in (("<Configure>", lambda e: self.draw()), ("<Motion>", self._on_move), ("<Leave>", self._on_leave),
                        ("<ButtonRelease-1>", self._on_click), ("<FocusIn>", lambda e: self._focused(True)),
                        ("<FocusOut>", lambda e: self._focused(False)), ("<Left>", lambda e: self._step(-1)),
                        ("<Right>", lambda e: self._step(1)), ("<Home>", lambda e: self._select(0)),
                        ("<End>", lambda e: self._select(len(self.values) - 1)), ("<Destroy>", self._on_destroy)):
            self.bind(seq, fn)
        self._trace = variable.trace_add("write", lambda *_: self._slide())

    # ------------------------------------------------------------- geometry
    def _widths(self) -> List[int]:
        # each item is as wide as its label in bold (which the chosen one uses), so nothing shifts
        return [self._bold.measure(label) + 2 * PAD_X for label in self.labels]

    def _fit(self) -> None:
        self.configure(width=sum(self._widths()), height=HEIGHT)

    def refresh(self) -> None:
        self._fit()
        self._bar_x = self._target_x()
        self.draw()

    def set_label(self, value, text: str) -> None:
        self.labels[self.values.index(value)] = text
        self._fit()
        self._bar_x = self._target_x()
        self.draw()

    def _index(self) -> int:
        try:
            return self.values.index(self.variable.get())
        except ValueError:
            return 0

    def _target_x(self) -> float:
        return sum(self._widths()[:self._index()]) + PAD_X

    def _segment_at(self, x: float) -> Optional[int]:
        edge = 0
        for i, w in enumerate(self._widths()):
            if edge <= x < edge + w:
                return i
            edge += w
        return None

    # --------------------------------------------------------------- events
    def _on_move(self, e) -> None:
        hover = self._segment_at(e.x)
        if hover != self._hover:
            self._hover = hover
            self.draw()

    def _on_leave(self, _e) -> None:
        self._hover = None
        self.draw()

    def _on_click(self, e) -> None:
        i = self._segment_at(e.x)
        if i is not None:
            self._mouse = True      # focus given by a click needs no focus marker; keyboard focus does
            self.focus_set()
            self._select(i)

    def _focused(self, on: bool) -> None:
        self._focus = on and not self._mouse
        if not on:
            self._mouse = False
        self.draw()

    def _step(self, delta: int) -> str:
        self._select(max(0, min(len(self.values) - 1, self._index() + delta)))
        return "break"

    def _select(self, i: int) -> None:
        if self.values[i] != self.variable.get():
            self.variable.set(self.values[i])   # the trace slides the indicator
            if self.command:
                self.command()

    def _on_destroy(self, event) -> None:
        if event.widget is not self:
            return
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                pass
        try:  # the variable outlives this widget: take our callback off it, or it keeps us (and the window) alive
            self.variable.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass
        self.command = None

    # ------------------------------------------------------------ animation
    def _slide(self) -> None:
        """Ease the accent bar to the chosen item."""
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                return
            self._anim = None
        start = self._bar_x if self._bar_x is not None else self._target_x()
        end = self._target_x()
        if REDUCED or abs(end - start) < 1:
            self._bar_x = end
            self.draw()
            return

        def step(i: int) -> None:
            try:
                t = i / FRAMES
                self._bar_x = start + (end - start) * (1 - (1 - t) ** 3)   # ease-out
                self.draw()
                self._anim = self.after(FRAME_MS, step, i + 1) if i < FRAMES else None
            except tk.TclError:
                self._anim = None

        step(1)

    # ------------------------------------------------------------- drawing
    def draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return
        chosen = self._index()
        edge = 0
        for k, (label, width) in enumerate(zip(self.labels, self._widths())):
            # a soft fill marks the pointer's item, and the chosen item while the keyboard has focus
            # (no outline box: the fill plus the accent bar show where you are)
            if (k == self._hover and k != chosen) or (self._focus and k == chosen):
                rounded(self, edge + 2, 3, edge + width - 2, h - 5, 4, fill=HOVER_FILL, outline="")
            self.create_text(edge + width / 2, (h - BAR_H) / 2 + 1, text=label,
                             fill=TEXT if k == chosen else MUTED_TEXT, font=self._bold if k == chosen else self._font)
            edge += width
        label_w = self._bold.measure(self.labels[chosen])
        x0 = self._bar_x if self._bar_x is not None else self._target_x()
        rounded(self, x0, h - BAR_H - 2, x0 + label_w, h - 2, BAR_H / 2, fill=ACCENT, outline="")  # the indicator
