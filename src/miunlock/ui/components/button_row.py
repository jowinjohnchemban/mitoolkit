"""A row of buttons that line up: equal width, equal gaps, and wrapping onto more rows when the
window is narrow or the text is enlarged (so nothing is cut off)."""
from __future__ import annotations

from tkinter import ttk
from typing import List

GAP = 8


class ButtonRow(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._buttons: List[ttk.Button] = []
        self._columns = 0
        self.bind("<Configure>", lambda _e: self._layout())

    def set(self, buttons: List[ttk.Button]) -> None:
        """Show exactly these buttons (children of this row), in this order."""
        for b in self._buttons:
            b.grid_forget()
        self._buttons = list(buttons)
        self._columns = 0
        self._layout()

    def relayout(self) -> None:
        """Lay out again, for when a button's label (and so its width) changed."""
        self._columns = 0
        self._layout()

    def _layout(self) -> None:
        if not self._buttons:
            return
        cell = max(b.winfo_reqwidth() for b in self._buttons) + GAP
        width = self.winfo_width()
        room = width if width > 1 else 10_000           # before the first layout the width is 1: no limit yet
        columns = max(1, min(len(self._buttons), room // cell))
        columns = -(-len(self._buttons) // -(-len(self._buttons) // columns))  # balance the rows (3+2, not 4+1)
        if columns == self._columns:
            return
        self._columns = columns
        for i in range(len(self._buttons) + 1):
            self.columnconfigure(i, weight=0, uniform="")
        for c in range(columns):
            self.columnconfigure(c, uniform="btn")
        for i, b in enumerate(self._buttons):
            b.grid(row=i // columns, column=i % columns, sticky="ew",
                   padx=(0, GAP if i % columns < columns - 1 else 0), pady=(0, GAP // 2))
