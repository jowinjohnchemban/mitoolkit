"""A read-only list of sections of "label  value" rows, drawn as ONE text widget.

Hundreds of separate labels are slow to build and to lay out (showing them took a fifth of a second),
while one text widget with two columns made of a tab stop is built in a few milliseconds. Wrapped
values line up under the value column (a hanging indent), the text can be selected and copied, and the
view sizes itself to its content so the page around it does the scrolling.

The height is worked out from font measurements instead of asking Tk to lay every line out (counting
display lines of a long wrapped text took most of a second).
"""
from __future__ import annotations

import math
import tkinter as tk
from typing import List, Optional, Sequence, Tuple

Section = Tuple[str, Sequence[Tuple[str, object]]]


class DetailsView(tk.Frame):
    def __init__(self, parent, fonts, muted: str, background: str, gap: int = 16):
        super().__init__(parent, background=background, height=40)
        self.pack_propagate(False)                       # our height is set from the content, below
        self.fonts, self.gap, self.background = fonts, gap, background
        self.text = tk.Text(self, wrap="word", borderwidth=0, highlightthickness=0, padx=0, pady=0, cursor="arrow",
                            background=background, font=fonts.base, takefocus=0, spacing1=1, spacing3=1, height=1)
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("heading", font=fonts.bold, spacing1=10, spacing3=3)
        self.text.tag_configure("label", foreground=muted)
        self._sections: List[Section] = []
        self._fit_job: Optional[str] = None
        self._tab = 0
        self.text.configure(state="disabled")
        self.bind("<Configure>", lambda _e: self._queue_fit())

    def set_sections(self, sections: Sequence[Section]) -> None:
        """Show these sections (title, [(label, value), ...])."""
        self._sections = list(sections)
        self._render()

    def refresh(self) -> None:
        """Lay out again (the text size changed)."""
        self._render()

    def _render(self) -> None:
        t, font = self.text, self.fonts.base
        widest = max((font.measure(str(label)) for _t, rows in self._sections for label, _v in rows), default=60)
        self._tab = widest + self.gap
        t.configure(state="normal", tabs=(self._tab,))
        t.delete("1.0", "end")
        t.tag_configure("row", lmargin1=0, lmargin2=self._tab)          # wrapped lines hang under the value
        for index, (title, rows) in enumerate(self._sections):
            if index:
                t.insert("end", "\n")
            t.insert("end", title + "\n", "heading")
            for label, value in rows:
                start = t.index("end-1c")
                t.insert("end", f"{label}\t{value}\n", "row")
                t.tag_add("label", start, f"{start}+{len(str(label))}c")
        t.configure(state="disabled")
        self._fit()

    def plain_text(self) -> str:
        return self.text.get("1.0", "end").rstrip("\n")

    def _queue_fit(self) -> None:
        if self._fit_job is None:
            self._fit_job = self.after(30, self._fit)    # after the first paint: opening shows at once, then settles

    def content_height(self, width: int) -> int:
        """Pixels needed for the text at this width, from font measurements."""
        base, bold = self.fonts.base, self.fonts.bold
        line, head = base.metrics("linespace") + 2, bold.metrics("linespace") + 13
        usable = max(width - self._tab - 4, 60)
        total = 0
        for index, (_title, rows) in enumerate(self._sections):
            total += head + (line if index else 0)                      # the blank line between sections
            for _label, value in rows:
                total += line * max(1, math.ceil(base.measure(str(value)) * 1.05 / usable))
        return total + 8

    def _fit(self) -> None:
        """Make the view exactly as tall as its text, so it never needs a scrollbar of its own."""
        self._fit_job = None
        width = self.winfo_width()
        if width < 80:                                                  # not laid out yet
            return
        wanted = self.content_height(width)
        if int(self.cget("height")) != wanted:
            self.configure(height=wanted)
