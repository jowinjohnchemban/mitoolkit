"""The Activity log in its own window, so it never takes space from the main page.

The App keeps every line (ActivityLog); this window shows them and follows new ones while it
is open. A grey, readable console: time in grey, problems in red, successes in green.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable, List, Optional, Tuple

from mitoolkit.ui.components.buttons import Button
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.theme import (CONSOLE_BG, CONSOLE_BORDER, CONSOLE_DIM, CONSOLE_FG, CONSOLE_HEAD, GREEN, RED)

_BAD = ("fail", "could not", "can't", "cannot", "error", "refused", "did not", "denied")
_GOOD = ("detected", "signed in", "done", "unlocked", "restored", "removed", "copied", "saved", "eligible")


def kind_of(text: str) -> str:
    low = text.lower()
    if any(w in low for w in _BAD):
        return "bad"
    return "good" if any(w in low for w in _GOOD) else ""


class ActivityLog:
    """Every line the program logged this session, plus whoever is listening."""

    MAX = 3000

    def __init__(self):
        self.lines: List[Tuple[str, str, str]] = []  # (time, text, kind)
        self.listener: Optional[Callable[[Tuple[str, str, str]], None]] = None

    def add(self, text: str) -> Tuple[str, str, str]:
        line = (time.strftime("%H:%M:%S"), text, kind_of(text))
        self.lines.append(line)
        del self.lines[:-self.MAX]
        if self.listener is not None:
            self.listener(line)
        return line

    def clear(self) -> None:
        self.lines.clear()

    def text(self) -> str:
        return "\n".join(f"{t}  {msg}" for t, msg, _k in self.lines)


class ActivityWindow(Dialog):
    title = "MiToolkit activity"
    size = "820x380"
    min_size = (480, 220)
    padding = 0

    def build(self) -> None:
        frame = tk.Frame(self.body, bg=CONSOLE_BORDER, padx=1, pady=1)
        frame.pack(fill="both", expand=True)
        head = tk.Frame(frame, bg=CONSOLE_HEAD, padx=10, pady=6)
        head.pack(side="top", fill="x")
        tk.Label(head, text="Activity", bg=CONSOLE_HEAD, fg=CONSOLE_FG, font=self.fonts.bold).pack(side="left")
        tk.Label(head, text="What MiToolkit is doing; no tokens or passwords are shown", bg=CONSOLE_HEAD,
                 fg=CONSOLE_DIM, font=self.fonts.small).pack(side="left", padx=8)
        Button(head, text="Close", command=self.close).pack(side="right")
        Button(head, text="Copy", command=self.copy).pack(side="right", padx=6)
        Button(head, text="Clear", command=self.clear).pack(side="right")

        body = tk.Frame(frame, bg=CONSOLE_BG)
        body.pack(side="top", fill="both", expand=True)
        mono = ("Consolas", 9)
        self.text = tk.Text(body, wrap="word", state="disabled", font=mono, bg=CONSOLE_BG, fg=CONSOLE_FG,
                            relief="flat", borderwidth=0, highlightthickness=0, padx=0, pady=6,
                            spacing1=1, spacing3=1, selectbackground="#c8d6e8", selectforeground=CONSOLE_FG)
        sb = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        indent = tkfont.Font(font=mono).measure("00:00:00  ") + 10
        self.text.tag_configure("line", lmargin1=10, lmargin2=indent)  # wrapped text lines up after the time
        self.text.tag_configure("time", foreground=CONSOLE_DIM)
        self.text.tag_configure("bad", foreground=RED)
        self.text.tag_configure("good", foreground=GREEN)

        self.log: ActivityLog = self.app.activity
        for line in self.log.lines:
            self._insert(line)
        self.log.listener = lambda line: self.app.call_soon(self._follow, line)

    def _insert(self, line: Tuple[str, str, str]) -> None:
        stamp, msg, kind = line
        self.text.configure(state="normal")
        self.text.insert("end", stamp + "  ", ("line", "time"))
        self.text.insert("end", msg + "\n", ("line", kind) if kind else ("line",))
        self.text.configure(state="disabled")

    def _follow(self, line: Tuple[str, str, str]) -> None:
        if self.alive():
            at_end = self.text.yview()[1] >= 0.999
            self._insert(line)
            if at_end:  # keep following unless the reader scrolled up
                self.text.see("end")

    def copy(self) -> None:
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(self.log.text())

    def clear(self) -> None:
        self.log.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def close(self) -> None:
        if getattr(self, "log", None) is not None:
            self.log.listener = None
        super().close()
