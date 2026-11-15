"""A search box with suggestions.

A rounded field with a search icon, a placeholder, a clear button and a border that turns blue when
you are typing. As you type, a short list of matches drops down; Up and Down move through it, Enter
or a click picks one, Escape closes it. The text editing itself is an ordinary Tk entry, so copy and
paste, selection and input methods all work as everywhere else.

The caller says what to suggest: a function that takes the text and returns [(value, note)], for
example app names with their package, or process names. ``rank()`` is a ready-made way to build such a
list from the candidates in hand: matches that start with the text first, then words that start with
it, then anything that contains it.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from miunlock.ui.components.buttons import icon_family
from miunlock.ui.components.shapes import page_background, rounded
from miunlock.ui.theme import ACCENT, MUTED, SELECT_BG

Suggestion = Tuple[str, str]               # (text to fill in, a note shown after it)

BORDER, BORDER_HOVER = "#868b94", "#5f6772"  # a field's edge needs 3:1 against the page (WCAG 1.4.11)
HEIGHT = 36
MAX_SHOWN = 8


def rank(query: str, candidates: Iterable[Suggestion], limit: int = MAX_SHOWN) -> List[Suggestion]:
    """The candidates that match the query, best first: starts with it, then a word starts with it,
    then contains it. Case does not matter; the same text is never offered twice."""
    q = query.strip().lower()
    if not q:
        return []
    scored: List[Tuple[int, int, Suggestion]] = []
    seen = set()
    for order, (text, note) in enumerate(candidates):
        key = text.lower()
        if key in seen:
            continue
        haystack = key + " " + note.lower()
        if key.startswith(q):
            score = 0
        elif any(word.startswith(q) for word in key.replace(".", " ").replace("_", " ").replace("-", " ").split()):
            score = 1
        elif q in haystack:
            score = 2
        else:
            continue
        seen.add(key)
        scored.append((score, order, (text, note)))
    scored.sort(key=lambda s: (s[0], s[2][0].lower()))
    return [s[2] for s in scored[:limit]]


class SearchBox(tk.Canvas):
    def __init__(self, parent, variable: tk.StringVar, placeholder: str = "Search", *, width: int = 280,
                 suggest: Optional[Callable[[str], Sequence[Suggestion]]] = None,
                 on_pick: Optional[Callable[[str], None]] = None, font: Optional[tkfont.Font] = None):
        self._bg = page_background(parent)
        super().__init__(parent, bg=self._bg, highlightthickness=0, borderwidth=0, width=width, height=HEIGHT)
        self.variable, self.placeholder, self.suggest, self.on_pick = variable, placeholder, suggest, on_pick
        self._font = font or tkfont.nametofont("TkDefaultFont")
        self._hover = self._focus = False
        self._popup: Optional[tk.Toplevel] = None
        self._list: Optional[tk.Listbox] = None
        self._shown: List[Suggestion] = []
        self._typing = False                    # suggestions only for what the person types, not for a pick

        self.entry = tk.Entry(self, textvariable=variable, relief="flat", borderwidth=0, highlightthickness=0,
                              bg="#ffffff", fg="#1b1b1b", insertbackground="#1b1b1b", font=self._font)
        self._entry_win = self.create_window(0, 0, window=self.entry, anchor="w")
        self.hint = tk.Label(self, text=placeholder, bg="#ffffff", fg=MUTED, font=self._font, anchor="w", cursor="xterm")
        self._hint_win = self.create_window(0, 0, window=self.hint, anchor="w")
        self.hint.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda _e: self.after(120, self._lost_focus))   # a click on the list needs a moment
        self.entry.bind("<Key>", lambda _e: setattr(self, "_typing", True), add="+")
        self.entry.bind("<Down>", lambda e: self._move(1))
        self.entry.bind("<Up>", lambda e: self._move(-1))
        self.entry.bind("<Return>", self._enter)
        self.entry.bind("<Escape>", self._escape)
        for widget in (self, self.entry):
            widget.bind("<Enter>", lambda _e: self._set_hover(True), add="+")
            widget.bind("<Leave>", lambda _e: self._set_hover(False), add="+")
        self.bind("<Configure>", lambda _e: self._layout())
        self.bind("<Button-1>", self._click)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._trace = variable.trace_add("write", lambda *_: self._changed())
        self._layout()

    # ------------------------------------------------------------- drawing
    def _icon(self) -> Optional[str]:
        return "" if icon_family(self) else None

    def _layout(self) -> None:
        w = self.winfo_width() if self.winfo_width() > 1 else int(self.cget("width"))
        h = HEIGHT
        left = 38 if self._icon() else 34
        right = w - 34
        self.itemconfigure(self._entry_win, width=max(right - left, 20), height=h - 12)
        self.coords(self._entry_win, left, h / 2)
        self.itemconfigure(self._hint_win, width=max(right - left, 20), height=h - 12)
        self.coords(self._hint_win, left, h / 2)
        self._paint()

    def _paint(self) -> None:
        self.delete("frame")
        w = self.winfo_width() if self.winfo_width() > 1 else int(self.cget("width"))
        h = HEIGHT
        edge = ACCENT if self._focus else BORDER_HOVER if self._hover else BORDER
        rounded(self, 1, 1, w - 1, h - 1, 8, fill=edge, outline="", tags="frame")
        inset = 3 if self._focus else 2                       # a thicker blue edge while typing
        rounded(self, inset, inset, w - inset, h - inset, 7, fill="#ffffff", outline="", tags="frame")
        icon = self._icon()
        if icon:
            self.create_text(14, h / 2, text=icon, anchor="w", fill=ACCENT if self._focus else MUTED,
                             font=tkfont.Font(family=icon_family(self), size=int(self._font.actual("size"))), tags="frame")
        else:                                                 # no icon font: draw a small magnifier
            c = ACCENT if self._focus else MUTED
            self.create_oval(13, h / 2 - 7, 24, h / 2 + 4, outline=c, width=2, tags="frame")
            self.create_line(23, h / 2 + 3, 28, h / 2 + 8, fill=c, width=2, tags="frame")
        if self.variable.get():                               # the clear button
            self.create_text(w - 17, h / 2, text="✕", fill=MUTED, font=self._font, tags=("frame", "clear"))
        self.tag_lower("frame")
        show_hint = not self.variable.get() and not self._focus
        self.itemconfigure(self._hint_win, state="normal" if show_hint else "hidden")

    def _set_hover(self, on: bool) -> None:
        self._hover = on
        self._paint()

    def _set_focus(self, on: bool) -> None:
        self._focus = on
        self._paint()

    def _lost_focus(self) -> None:
        try:
            if self.focus_get() is self._list:
                return
        except KeyError:
            pass
        self._set_focus(False)
        self._close_popup()

    def _click(self, event) -> None:
        w = self.winfo_width()
        if self.variable.get() and event.x > w - 30:
            self.variable.set("")
            self.entry.focus_set()
        else:
            self.entry.focus_set()

    # ----------------------------------------------------------- suggestions
    def _changed(self) -> None:
        self._paint()
        if self._typing and self._focus:
            self._show_suggestions()
        elif not self.variable.get():
            self._close_popup()

    def _show_suggestions(self) -> None:
        if self.suggest is None:
            return
        try:
            found = list(self.suggest(self.variable.get()))[:MAX_SHOWN]
        except Exception:                                      # a broken provider must not break typing
            found = []
        # nothing to offer, or the only offer is exactly what is typed: close the list
        if not found or (len(found) == 1 and found[0][0].lower() == self.variable.get().strip().lower()):
            self._close_popup()
            return
        self._shown = found
        if self._popup is None:
            popup = tk.Toplevel(self)
            popup.withdraw()
            popup.overrideredirect(True)
            popup.attributes("-topmost", True)
            frame = tk.Frame(popup, bg=BORDER, padx=1, pady=1)
            frame.pack(fill="both", expand=True)
            self._list = tk.Listbox(frame, activestyle="none", exportselection=False, borderwidth=0, highlightthickness=0,
                                    font=self._font, bg="#ffffff", fg="#1b1b1b", selectbackground=SELECT_BG,
                                    selectforeground="#1b1b1b")
            self._list.pack(fill="both", expand=True)
            self._list.bind("<ButtonRelease-1>", self._pick_clicked)
            self._popup = popup
        assert self._list is not None
        self._list.delete(0, "end")
        for text, note in found:
            self._list.insert("end", text + (f"    {note}" if note else ""))
        self._list.configure(height=len(found))
        self.update_idletasks()
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 2
        self._popup.geometry(f"{self.winfo_width()}x{self._list.winfo_reqheight() + 2}+{x}+{y}")
        self._popup.deiconify()
        self._popup.lift()

    def _close_popup(self) -> None:
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:
                pass
            self._popup, self._list, self._shown = None, None, []

    def _move(self, step: int) -> str:
        if self._popup is None:
            self._typing = True
            self._show_suggestions()
            if self._popup is None:
                return "break"
            step = 0 if step > 0 else step
        assert self._list is not None
        current = self._list.curselection()
        index = (current[0] + step) if current else (0 if step >= 0 else len(self._shown) - 1)
        index = max(0, min(len(self._shown) - 1, index))
        self._list.selection_clear(0, "end")
        self._list.selection_set(index)
        self._list.see(index)
        return "break"

    def _enter(self, _event) -> str:
        if self._popup is not None and self._list is not None and self._list.curselection():
            self._pick(self._list.curselection()[0])
            return "break"
        self._close_popup()
        return ""

    def _escape(self, _event) -> str:
        if self._popup is not None:
            self._close_popup()
        elif self.variable.get():
            self.variable.set("")
        return "break"

    def _pick_clicked(self, event) -> None:
        if self._list is not None:
            index = self._list.nearest(event.y)
            if 0 <= index < len(self._shown):
                self._pick(index)

    def _pick(self, index: int) -> None:
        text = self._shown[index][0]
        self._typing = False                                  # setting the text is not typing: no new list
        self._close_popup()
        self.variable.set(text)
        self.entry.focus_set()
        self.entry.icursor("end")
        if self.on_pick:
            self.on_pick(text)

    def _on_destroy(self, event) -> None:
        if event.widget is not self:
            return
        self._close_popup()
        try:                                                   # the variable outlives this widget
            self.variable.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass
