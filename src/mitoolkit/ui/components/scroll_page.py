"""A page that scrolls vertically and keeps its content a readable, centred column.

The scrollbar is always shown: hiding it when not needed makes the page narrower and wider in
turn, which re-wraps the text and flickers. Resizes are debounced, so dragging a window edge
re-lays the page out once, after the drag, instead of dozens of times.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class ScrollPage(ttk.Frame):
    MAX_WIDTH = 880

    def __init__(self, parent, bg: str, on_width: Callable[[int], None]):
        super().__init__(parent)
        self._on_width = on_width
        self._pending: Optional[str] = None
        self._last_width = 0
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, bg=bg)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self.canvas, padding=(20, 16, 20, 16))
        self._item = self.canvas.create_window((0, 0), window=self.content, anchor="n")
        self.content.bind("<Configure>", lambda _e: self._update_region())
        self.canvas.bind("<Configure>", self._on_resize)

    def width(self) -> int:
        return min(max(self.canvas.winfo_width(), 1), self.MAX_WIDTH)

    def _on_resize(self, _event) -> None:
        if self._pending is not None:
            self.after_cancel(self._pending)
        self._pending = self.after(60, self._apply)

    def _apply(self) -> None:
        self._pending = None
        total = self.canvas.winfo_width()
        width = min(total, self.MAX_WIDTH)
        self.canvas.coords(self._item, total // 2, 0)
        self.canvas.itemconfigure(self._item, width=width)
        if width != self._last_width:
            self._last_width = width
            self._on_width(width)
        self._update_region()

    def _update_region(self) -> None:
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=(0, 0, bbox[2], max(bbox[3], self.canvas.winfo_height())))

    def refit(self) -> None:
        """Re-measure after content was added or removed: update the scroll area, and repaint, so a page that
        got shorter shows no blank space or leftover pixels."""
        self.update_idletasks()
        self._update_region()
        first, last = self.canvas.yview()
        if last >= 1.0 and first > 0:                         # scrolled past the new end: come back to it
            self.canvas.yview_moveto(max(0.0, 1.0 - (last - first)))
        self.canvas.update_idletasks()

    def scroll(self, units: int) -> None:
        if self.content.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(units, "units")

    def to_top(self) -> None:
        self.canvas.yview_moveto(0)
