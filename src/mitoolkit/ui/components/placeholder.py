"""Grey example text inside an empty entry, like 192.168.1.xx:41234. It disappears as soon as something is typed and
comes back when the entry is empty again. The entry's variable never holds the example, so nothing can be submitted
by mistake, and clicking the example puts the cursor in the entry.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

HINT = "#6b7280"            # 4.8:1 on white


def placeholder(entry: ttk.Entry, variable: tk.StringVar, text: str) -> tk.Label:
    """Show ``text`` in ``entry`` while ``variable`` is empty. Returns the label (for tests)."""
    field = ttk.Style(entry).lookup("TEntry", "fieldbackground") or "white"
    label = tk.Label(entry, text=text, fg=HINT, bg=field, borderwidth=0, padx=0, pady=0, cursor="xterm")
    label.bind("<Button-1>", lambda _e: entry.focus_set())

    def sync(*_args) -> None:
        if variable.get():
            label.place_forget()
        else:
            label.place(x=4, rely=0.5, anchor="w")

    trace = variable.trace_add("write", sync)
    entry.bind("<Destroy>", lambda e: _forget(variable, trace) if e.widget is entry else None, add="+")
    sync()
    return label


def _forget(variable: tk.StringVar, trace: str) -> None:
    try:
        variable.trace_remove("write", trace)          # the variable outlives the entry: do not leave a callback on it
    except (tk.TclError, ValueError):
        # already removed
        pass
