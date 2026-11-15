"""The offline step-by-step guide (Help > Step-by-step guide, F1)."""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from miunlock import guide
from miunlock.ui.base import Dialog
from miunlock.ui.theme import BORDER, DOCS, WARN_BG, WARN_FG


class GuideWindow(Dialog):
    title = "miunlock guide"
    size = "760x520"
    min_size = (520, 340)
    padding = 10

    def build(self) -> None:
        self.side = tk.Listbox(self.body, width=30, exportselection=False, activestyle="none",
                               borderwidth=0, highlightthickness=1, highlightbackground=BORDER)
        self.side.pack(side="left", fill="y")
        right = ttk.Frame(self.body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        sbar = ttk.Scrollbar(right)
        sbar.pack(side="right", fill="y")
        self.text = tk.Text(right, wrap="word", padx=14, pady=10, borderwidth=0, highlightthickness=0,
                            font=self.fonts.base, yscrollcommand=sbar.set, cursor="arrow", spacing3=6)
        self.text.pack(side="left", fill="both", expand=True)
        sbar.configure(command=self.text.yview)
        self.text.tag_configure("h", font=self.fonts.title, spacing3=10)
        self.text.tag_configure("b", lmargin1=18, lmargin2=36)
        self.text.tag_configure("w", background=WARN_BG, foreground=WARN_FG, font=self.fonts.bold,
                                lmargin1=8, lmargin2=8, rmargin=8, spacing1=4, spacing3=10)

        for title, _ in guide.TOPICS:
            self.side.insert("end", "  " + title)
        self.side.bind("<<ListboxSelect>>", self._on_pick)

        nav = ttk.Frame(self.win, padding=(10, 0, 10, 10))
        nav.pack(fill="x")
        ttk.Button(nav, text="Close", command=self.close).pack(side="right")
        ttk.Button(nav, text="Next ▶", command=lambda: self.step(1)).pack(side="right", padx=6)
        ttk.Button(nav, text="◀ Back", command=lambda: self.step(-1)).pack(side="right")
        ttk.Button(nav, text="Open full guide in browser",
                   command=lambda: webbrowser.open(DOCS + "unlock-guide.md")).pack(side="left")
        self.pick(0)

    def show(self, index: int) -> None:
        title, blocks = guide.TOPICS[index]
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", title + "\n", "h")
        for kind, content in blocks:
            if kind == "b":
                t.insert("end", "•  " + content + "\n", "b")
            elif kind == "w":
                t.insert("end", "⚠  " + content + "\n", "w")
            else:
                t.insert("end", content + "\n")
        t.configure(state="disabled")
        t.yview_moveto(0)

    def pick(self, index: int) -> None:
        self.side.selection_clear(0, "end")
        self.side.selection_set(index)
        self.side.see(index)
        self.show(index)

    def step(self, delta: int) -> None:
        sel = self.side.curselection()
        self.pick(min(max((sel[0] if sel else 0) + delta, 0), len(guide.TOPICS) - 1))

    def _on_pick(self, _event=None) -> None:
        sel = self.side.curselection()
        if sel:
            self.show(sel[0])
