"""Base class for the GUI's secondary windows."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional


class Dialog:
    """A window owned by the main App: titled, sized, closed with Escape, with a padded
    ``body`` frame to build in. Subclasses implement ``build()``."""

    title = "miunlock"
    size: Optional[str] = None      # "WIDTHxHEIGHT", or None to fit the content
    min_size: Optional[tuple] = None
    resizable = True
    padding = 12

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title(self.title)
        self.win.transient(app.root)
        if self.size:
            self.win.geometry(self.size)
        if self.min_size:
            self.win.minsize(*self.min_size)
        self.win.resizable(self.resizable, self.resizable)
        self.win.bind("<Escape>", lambda _e: self.close())
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.body = ttk.Frame(self.win, padding=self.padding)
        self.body.pack(fill="both", expand=True)
        self.build()

    @property
    def fonts(self):
        return self.app.fonts

    def build(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def focus(self) -> None:
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def close(self) -> None:
        if self.alive():
            self.win.destroy()
