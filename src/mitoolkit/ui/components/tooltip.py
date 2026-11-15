"""A small label that names a control that only shows an icon.

It appears after the pointer rests on the control for half a second, or at once when the keyboard reaches it, and goes
away when the pointer leaves, a key is pressed or the control is clicked. Nothing is kept alive after the control is
destroyed.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional, Union

DELAY_MS = 500
BG, FG, EDGE = "#2b2f36", "#ffffff", "#2b2f36"          # dark chip, white text (about 14:1)


class Tooltip:
    def __init__(self, widget: tk.Widget, text: Union[str, Callable[[], str]], delay: int = DELAY_MS):
        self.widget, self.text, self.delay = widget, text, delay
        self._after: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        for seq, fn in (("<Enter>", lambda e: self._schedule(self.delay)), ("<Leave>", lambda e: self.hide()),
                        ("<ButtonPress>", lambda e: self.hide()), ("<KeyPress>", lambda e: self.hide()),
                        ("<FocusIn>", lambda e: self._schedule(0)), ("<FocusOut>", lambda e: self.hide()),
                        ("<Destroy>", lambda e: self.hide() if e.widget is self.widget else None)):
            widget.bind(seq, fn, add="+")

    def _schedule(self, delay: int) -> None:
        self.hide()
        self._after = self.widget.after(delay, self.show)

    def show(self) -> None:
        self._after = None
        if self._tip is not None or not self.widget.winfo_exists():
            return
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        tip = tk.Toplevel(self.widget)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=text, bg=BG, fg=FG, padx=8, pady=3, borderwidth=0, highlightthickness=1,
                 highlightbackground=EDGE).pack()
        tip.update_idletasks()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - tip.winfo_reqwidth() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        x = max(0, min(x, self.widget.winfo_screenwidth() - tip.winfo_reqwidth()))          # stay on the screen
        tip.geometry(f"+{x}+{y}")
        tip.deiconify()
        self._tip = tip

    def hide(self) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                # the widget is already gone
                pass
            self._after = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                # the tip went with its window
                pass
            self._tip = None
