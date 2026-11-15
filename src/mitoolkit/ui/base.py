"""Base class for the GUI's secondary windows."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from mitoolkit import memory
from mitoolkit.ui.placement import fit_to_screen


class Dialog:
    """A window owned by the main App: titled, sized, closed with Escape, with a padded
    ``body`` frame to build in. Subclasses implement ``build()``."""

    title = "mitoolkit"
    size: Optional[str] = None      # "WIDTHxHEIGHT", or None to fit the content
    min_size: Optional[tuple] = None
    resizable = True
    padding = 12

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()  # stay hidden until sized and placed, so it doesn't jump
        self.win.title(self.title)
        self.win.transient(app.root)
        if self.min_size:
            self.win.minsize(*self.min_size)
        self.win.resizable(self.resizable, self.resizable)
        self.win.bind("<Escape>", lambda _e: self.close())
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.body = ttk.Frame(self.win, padding=self.padding)
        self.body.pack(fill="both", expand=True)
        self.build()
        if self.size:
            w, h = (int(v) for v in self.size.split("x"))
        else:  # fit the content
            self.win.update_idletasks()
            w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        fit_to_screen(self.win, w, h)
        self.win.deiconify()

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

    def _release_traces(self) -> None:
        """Take the window's callbacks off its variables. A traced variable keeps a reference in Tk's
        own command table, out of the garbage collector's sight, so a closed window whose variable still
        calls back into it could never be freed."""
        for value in list(vars(self).values()):
            if isinstance(value, tk.Variable):
                try:
                    for modes, callback in value.trace_info():
                        for mode in modes:
                            value.trace_remove(mode, callback)
                except tk.TclError:
                    pass

    def close(self) -> None:
        if self.alive():
            root = self.app.root
            self._release_traces()
            self.win.destroy()
            memory.collect_soon(root)     # its widgets, charts and data are freed now, not eventually
