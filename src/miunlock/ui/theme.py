"""Colours, links and fonts shared by every window."""
from __future__ import annotations

from tkinter import font as tkfont

REPO = "https://github.com/jowinjohnchemban/miunlock"
DOCS = REPO + "/blob/main/docs/"

GREEN = "#1a7f37"
RED = "#b3261e"
AMBER = "#9a5b00"
MUTED = "#5f6368"
ORANGE_DOT = "#e8710a"
ACCENT = "#e8590c"
WARN_BG = "#fff4ce"
WARN_FG = "#5c4400"
BORDER = "#d0d0d0"
LOCKED = "#9aa0a6"


class Fonts:
    """The four fonts the GUI uses, derived from the system's default font."""

    def __init__(self):
        self.base = tkfont.nametofont("TkDefaultFont")
        self.bold = self.base.copy()
        self.bold.configure(weight="bold")
        self.title = self.base.copy()
        self.title.configure(size=self.base.cget("size") + 8, weight="bold")
        self.small = self.base.copy()
        self.small.configure(size=max(self.base.cget("size") - 1, 8))
        self.link = self.base.copy()
        self.link.configure(underline=True)
