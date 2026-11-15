"""Modern buttons, drawn on a plain canvas (no images, no extra theme, so they repaint as fast as
any native widget).

Rounded corners, a soft shadow line, colours that ease between rest, hover and pressed, an
accent-filled main button, a selected state for toggle/segmented buttons, an optional icon from
the system's icon font (Segoe Fluent Icons / Segoe MDL2 Assets on Windows), a clear disabled look
and a strong keyboard focus ring. They are focusable, act on Space and Enter, and are 34 px tall
so they are easy to hit. Meaning never rests on colour alone: every button has a text label.

On macOS the system's own (Aqua) buttons are the best look, so ``Button()`` returns a ttk button
there. Everywhere else it returns a ModernButton. Both take the same arguments and answer to
``configure(text=..., state=...)``, ``cget("text")`` and ``invoke()``.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Callable, Dict, Optional, Tuple

from miunlock.ui.components.shapes import mix as _mix
from miunlock.ui.components.shapes import page_background, rounded
from miunlock.ui.theme import ACCENT

# Windows 11 (Fluent) button colours: a near-white face, a hairline border, a darker bottom edge,
# 4 px corners, and the accent colour for the main action.
FACE, BORDER = "#fbfbfb", "#e0e0e0"
# Colour follows what the button is doing: a blue tint when the pointer is over it, a deeper blue
# while it is pressed, and an accent ring when the keyboard is on it (never a black box).
HOVER, BORDER_HOVER = "#eaf2fc", "#86b6e8"
PRESSED, BORDER_PRESSED = "#d5e6f8", ACCENT
SHADOW = "#c4c4c4"
TEXT = "#1b1b1b"
PRIMARY, PRIMARY_HOVER, PRIMARY_PRESSED = ACCENT, "#1269bf", "#004a91"   # white text stays above 4.5:1 in every state
# Buttons that carry a state. Each kind is (border, text, hover wash, pressed wash):
# danger = erases something or needs attention (red), warn = review (amber), good = all clear (green).
KINDS = {
    "danger": ("#d6554d", "#a52419", "#fdeceb", "#f8d2cf"),
    "warn": ("#b8860b", "#6f5200", "#fff6dc", "#f7e4a8"),
    "good": ("#2f9e6b", "#17623f", "#eaf7f0", "#cdebdc"),
}
SELECTED_FACE = "#e1ecfb"
DISABLED_FACE, DISABLED_BORDER, DISABLED_TEXT = "#f4f4f4", "#ececec", "#8a8a8a"
FOCUS = ACCENT
RADIUS = 4
PAD_X = 16
MIN_HEIGHT = 32
STEPS, STEP_MS = 4, 20     # colour easing between states

# Glyphs of Segoe MDL2 Assets / Segoe Fluent Icons (checked by eye on Windows 10)
ICONS: Dict[str, str] = {
    "refresh": "", "copy": "", "pause": "", "play": "", "save": "",
    "apps": "", "lock": "", "chart": "", "phone": "", "power": "",
    "search": "", "shield": "", "user": "", "info": "", "settings": "",
}
ICONS.update({"down": "", "up": "",      # chevrons for the expander bar
              "wifi": ""})                      # connections
_icon_families: Dict[str, Optional[str]] = {}


def icon_family(widget) -> Optional[str]:
    """The installed icon font, or None (then buttons simply have no icon)."""
    key = str(widget.winfo_toplevel())
    if key not in _icon_families:
        names = set(tkfont.families(widget))
        _icon_families[key] = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in names), None)
    return _icon_families[key]


class ModernButton(tk.Canvas):
    def __init__(self, parent, text: str = "", command: Optional[Callable[[], None]] = None, *,
                 primary: bool = False, variable: Optional[tk.Variable] = None, value=None,
                 font: Optional[tkfont.Font] = None, icon: Optional[str] = None, kind: str = "normal"):
        """icon: a name from ICONS (drawn only when the system has an icon font).
        kind: "normal", "flat" (an expander bar), or a state colour: "danger" (red), "warn" (amber) or
        "good" (green). It can be changed later with configure(kind=...)."""
        self._bg = page_background(parent)
        super().__init__(parent, highlightthickness=0, borderwidth=0, bg=self._bg, takefocus=True, cursor="arrow")
        self._text, self._command, self.primary = text, command, primary
        self._variable, self._value = variable, value
        self._icon_name = icon
        self._font = font or tkfont.nametofont("TkDefaultFont")
        self._icon_font: Optional[tkfont.Font] = None
        self._state = "normal"
        self._hover = self._down = self._focus = False
        self._mouse = False          # focus that came from a click: no focus ring for that
        self.kind = kind
        self._anim: Optional[str] = None
        self._shown: Tuple[str, str] = (FACE, BORDER)
        self._fit()
        self._shown = self._colours()[:2]
        for seq, fn in (("<Enter>", self._on_enter), ("<Leave>", self._on_leave), ("<Motion>", self._on_motion),
                        ("<ButtonPress-1>", self._on_press), ("<ButtonRelease-1>", self._on_release),
                        ("<FocusIn>", lambda e: self._set(focus=not self._mouse)),
                        ("<FocusOut>", lambda e: self._focus_lost()),
                        ("<space>", self._key), ("<Return>", self._key), ("<Configure>", lambda e: self._paint()),
                        ("<Destroy>", self._on_destroy)):
            self.bind(seq, fn)
        if variable is not None:
            self._trace = variable.trace_add("write", lambda *_: self._transition())

    # ------------------------------------------------------------- sizing
    def _icon_glyph(self) -> Optional[str]:
        return ICONS.get(self._icon_name or "") if icon_family(self) else None

    def _fit(self) -> None:
        """Size to the icon and text (re-run when they, or the text size, change)."""
        glyph = self._icon_glyph()
        if glyph:
            self._icon_font = tkfont.Font(family=icon_family(self), size=int(self._font.actual("size")))
        width = self._font.measure(self._text) + 2 * PAD_X
        if glyph:
            width += self._icon_font.measure(glyph) + (10 if self._text else 0)
        height = max(MIN_HEIGHT, self._font.metrics("linespace") + 18)
        self.configure(width=width, height=height)
        self._paint()

    def refresh(self) -> None:
        self._fit()

    # --------------------------------------------------- ttk-style interface
    def configure(self, cnf=None, **kw):  # type: ignore[override]
        cnf = dict(cnf or {}, **kw)
        changed = False
        if "text" in cnf:
            self._text, changed = cnf.pop("text"), True
        if "state" in cnf:
            self._state = "disabled" if cnf.pop("state") == "disabled" else "normal"
            self.configure_cursor()
            changed = True
        if "command" in cnf:
            self._command = cnf.pop("command")
        if "icon" in cnf:
            self._icon_name, changed = cnf.pop("icon"), True
        if "kind" in cnf:
            self.kind, changed = cnf.pop("kind"), True
        cnf.pop("style", None)
        if cnf:
            super().configure(cnf)
        if changed:
            self._fit()
            self._shown = self._colours()[:2]
            self._paint()
        return None

    config = configure

    def cget(self, key):  # type: ignore[override]
        return {"text": self._text, "state": self._state}.get(key) or super().cget(key)

    def configure_cursor(self) -> None:
        super().configure(cursor="arrow" if self._state == "disabled" else "hand2")

    def invoke(self) -> None:
        if self._state == "disabled":
            return
        if self._variable is not None:
            self._variable.set(self._value)
        if self._command:
            self._command()

    # ------------------------------------------------------------- events
    def _set(self, **flags) -> None:
        for name, value in flags.items():
            setattr(self, "_" + name, value)
        if "down" in flags and flags["down"]:
            self._shown = self._colours()[:2]  # pressing answers at once
            self._paint()
        else:
            self._transition()

    def _on_enter(self, _e) -> None:
        self._set(hover=True)

    def _on_leave(self, _e) -> None:
        self._set(hover=False, down=False)

    def _on_press(self, _e) -> None:
        if self._state != "disabled":
            self._mouse = True
            self.focus_set()
            self._set(down=True, focus=False)

    def _focus_lost(self) -> None:
        self._mouse = False
        self._set(focus=False)

    def _on_release(self, e) -> None:
        was_down = self._down
        self._set(down=False)
        if was_down and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            # A click leaves nothing "selected" behind: no hover tint (the pointer may never get a Leave
            # event if the click opens a window) and no focus ring. The keyboard keeps its own focus ring.
            self._set(hover=False, focus=False)
            self._mouse = False
            try:
                self.winfo_toplevel().focus_set()
            except tk.TclError:
                pass
            self.invoke()

    def _on_motion(self, _e) -> None:
        if not self._hover and self._state != "disabled":   # the pointer is over us again after a click
            self._set(hover=True)

    def _key(self, _e) -> str:
        self.invoke()
        return "break"

    def _on_destroy(self, event) -> None:
        if event.widget is not self:
            return
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                pass
            self._anim = None
        if self._variable is not None:  # take our callback off the variable so it can't keep the window alive
            try:
                self._variable.trace_remove("write", self._trace)
            except (tk.TclError, ValueError, AttributeError):
                pass
        self._command = None

    # ------------------------------------------------------------ painting
    @property
    def selected(self) -> bool:
        return self._variable is not None and self._variable.get() == self._value

    def _colours(self) -> Tuple[str, str, str]:
        """(face, border, text) for the current state."""
        if self._state == "disabled":
            return DISABLED_FACE, DISABLED_BORDER, DISABLED_TEXT
        if self.kind == "flat":  # an expander bar: no border or shadow, a blue wash when the pointer is on it
            face = PRESSED if self._down else HOVER if self._hover else self._bg
            return face, face, ACCENT
        if self.primary:
            face = PRIMARY_PRESSED if self._down else PRIMARY_HOVER if self._hover else PRIMARY
            return face, face, "#ffffff"
        if self.kind in KINDS:
            border, text, hover, pressed = KINDS[self.kind]
            return (pressed if self._down else hover if self._hover else FACE), border, text
        if self.selected:
            return (PRESSED if self._down else SELECTED_FACE), ACCENT, TEXT
        if self._down:
            return PRESSED, BORDER_PRESSED, TEXT
        return (HOVER, BORDER_HOVER, TEXT) if self._hover else (FACE, BORDER, TEXT)

    def _transition(self) -> None:
        """Ease the face and border colours to the new state over a few frames."""
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                return
            self._anim = None
        start = self._shown
        face, border, _t = self._colours()

        def step(i: int) -> None:
            try:
                t = i / STEPS
                self._shown = (_mix(start[0], face, t), _mix(start[1], border, t))
                self._paint()
                self._anim = self.after(STEP_MS, step, i + 1) if i < STEPS else None
            except tk.TclError:  # the button was destroyed mid-way
                self._anim = None

        step(1)

    def _paint(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 8 or h < 8:  # not laid out yet
            w, h = int(self.cget("width")), int(self.cget("height"))
        face, border = self._shown
        text = self._colours()[2]
        bottom = h - 2                                           # the body; a 1 px shadow sits under it
        rounded(self, 1, 2, w - 1, h - 1, RADIUS, fill=self._bg if self.kind == "flat" else SHADOW, outline="")
        rounded(self, 1, 1, w - 1, bottom, RADIUS, fill=border, outline="")
        rounded(self, 2, 2, w - 2, bottom - 1, RADIUS - 1, fill=face, outline="")
        if self._focus and self._state != "disabled":  # keyboard focus: an accent ring with a white gap
            rounded(self, 0, 0, w, bottom + 1, RADIUS + 1, fill="", outline=FOCUS, width=2)
            rounded(self, 3, 3, w - 3, bottom - 2, RADIUS - 2, fill="", outline="#ffffff", width=1)
        glyph = self._icon_glyph()
        cy = (bottom + 1) / 2
        if glyph and self._icon_font is not None:
            icon_w = self._icon_font.measure(glyph)
            text_w = self._font.measure(self._text) if self._text else 0
            x = (w - (icon_w + (10 if self._text else 0) + text_w)) / 2
            self.create_text(x, cy, text=glyph, fill=text, font=self._icon_font, anchor="w")
            if self._text:
                self.create_text(x + icon_w + 10, cy, text=self._text, fill=text, font=self._font, anchor="w")
        else:
            self.create_text(w / 2, cy, text=self._text, fill=text, font=self._font)


def Button(parent, text: str = "", command: Optional[Callable[[], None]] = None, *, primary: bool = False,
           variable: Optional[tk.Variable] = None, value=None, font=None, icon: Optional[str] = None,
           kind: str = "normal"):
    """A button in the best look for this system (see the module notes)."""
    if sys.platform == "darwin":
        if variable is not None:
            return ttk.Radiobutton(parent, text=text, variable=variable, value=value, style="Toolbutton",
                                   command=command)
        return ttk.Button(parent, text=text, command=command, style="Primary.TButton" if primary else "TButton")
    return ModernButton(parent, text, command, primary=primary, variable=variable, value=value, font=font,
                        icon=icon, kind=kind)


def segmented(parent, choices, variable: tk.Variable, command: Optional[Callable[[], None]] = None):
    """A group of choices [(value, label)] that act like radio buttons.

    Windows and Linux: one Windows 11 style selector bar with a sliding accent indicator (see
    selector.py). macOS: the system's own toggle buttons."""
    if sys.platform == "darwin":
        frame = ttk.Frame(parent)
        made = {}
        for value, label in choices:
            made[value] = Button(frame, label, command, variable=variable, value=value)
            made[value].pack(side="left")
        frame.set_label = lambda value, text: made[value].configure(text=text)  # same call as the selector bar
        return frame
    from miunlock.ui.components.selector import SelectorBar
    return SelectorBar(parent, choices, variable, command)
