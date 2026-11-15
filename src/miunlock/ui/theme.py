"""Colours, links, fonts and the ttk theme shared by every window.

Accessibility (WCAG 2.2 AA): every text colour below has at least 4.5:1 contrast on the
background it is used on, and the status dot at least 3:1 (checked by
tests/test_accessibility.py). Colour is never the only signal: each state also has words.
Text can be enlarged up to 200% with Ctrl + (scale_fonts)."""
from __future__ import annotations

import sys
from tkinter import font as tkfont

REPO = "https://github.com/jowinjohnchemban/miunlock"
DOCS = REPO + "/blob/main/docs/"

GREEN = "#0f7b3a"
RED = "#c42b1c"
RED_DARK = "#a52419"     # pressed state of the red (destructive) button
DISABLED_BG = "#e0e0e0"  # the theme's disabled button colours
DISABLED_FG = "#a0a0a0"
AMBER = "#9d5d00"
MUTED = "#5f6368"
TEXT = "#1b1b1b"
ORANGE_DOT = "#c25400"   # 4.6:1 on the window background
ACCENT = "#005fb8"      # the accent blue: main buttons, step badges, focus
WARN_BG = "#fff4ce"
WARN_FG = "#5c4400"
BORDER = "#d0d0d0"
LOCKED = "#6b7075"       # "not yet" step badge: white text at 4.9:1

# The Activity log: soft grey, readable, not a black terminal.
CONSOLE_BG = "#f4f5f7"
CONSOLE_HEAD = "#e8eaed"
CONSOLE_BORDER = "#d0d4da"
CONSOLE_FG = "#30343b"
CONSOLE_DIM = "#5f6368"

# One type scale for the whole program (points).
SIZE_SMALL, SIZE_BODY, SIZE_HEADING, SIZE_TITLE = 9, 10, 12, 18


def named_font(name: str, root=None) -> tkfont.Font:
    """A named Tk font of this window's interpreter. (tkfont.nametofont only takes ``root`` from Python 3.10.)"""
    return tkfont.Font(root=root, name=name, exists=True)


def _family(root) -> str:
    """The system UI font: Segoe UI on Windows, else whatever Tk uses by default."""
    families = set(tkfont.families(root))
    for name in (("Segoe UI",) if sys.platform == "win32" else ()) + (".AppleSystemUIFont", "SF Pro Text",
                                                                    "Cantarell", "Ubuntu", "Noto Sans"):
        if name in families:
            return name
    return named_font("TkDefaultFont", root).actual("family")


def _unify_fonts(root) -> str:
    """Give every named font (Tk's and the theme's) the same family and a consistent size, so
    labels, buttons, lists and fields all match."""
    family = _family(root)
    semibold = "Segoe UI Semibold" if family == "Segoe UI" and "Segoe UI Semibold" in tkfont.families(root) else None
    sizes = {
        "TkDefaultFont": SIZE_BODY, "TkTextFont": SIZE_BODY, "TkMenuFont": SIZE_BODY,
        "TkHeadingFont": SIZE_BODY, "TkCaptionFont": SIZE_BODY, "TkIconFont": SIZE_BODY,
        "TkTooltipFont": SIZE_SMALL, "TkSmallCaptionFont": SIZE_SMALL,
    }
    strong = {"TkHeadingFont"}
    for name, size in sizes.items():
        try:
            f = named_font(name, root)
        except tk_error():
            continue
        if name in strong and semibold:
            f.configure(family=semibold, size=size, weight="normal")
        else:
            f.configure(family=family, size=size, weight="bold" if name in strong else "normal")
    return family


def tk_error():
    import tkinter
    return tkinter.TclError


# Neutral greys, used only for the flat style on Linux (the native themes bring their own).
WINDOW_BG = "#fafafa"
FIELD_BG = "#ffffff"
EDGE = "#c9ccd1"          # borders of buttons and fields
HOVER = "#eef2f8"
PRESSED = "#e0e7f1"
SELECT_BG = "#d6e6fa"     # selected row
HEADING_BG = "#eef0f3"

# The look of each system: its own native ttk theme where Tk has one.
NATIVE_THEMES = {"win32": ("vista", "winnative", "clam"), "darwin": ("aqua", "clam")}
LINUX_THEMES = ("clam", "alt", "default")


def native_theme_name(names) -> str:
    """The best installed theme for this system: Windows native on Windows, Aqua on macOS,
    clam on Linux and anywhere else (the best Tk offers there, styled flat below)."""
    for name in NATIVE_THEMES.get(sys.platform, LINUX_THEMES):
        if name in names:
            return name
    return names[0]


def apply_theme(root) -> dict:
    """Use the operating system's own look.

    Windows: the native "vista" theme. macOS: "aqua". Linux (and anything else): "clam" with a
    light, flat style, since the other Tk themes there look dated. Image-based add-on themes
    (Sun Valley) were tried and dropped: they repaint about three times slower, so parts of the
    window painted late on resize. Native themes are the fastest and look right on their system.

    Adds "Primary.TButton" (the main action: coloured on Linux, bold on the native themes) and
    "Card.TFrame". Returns {"bg": window background, "family": font family, "theme": name}."""
    from tkinter import ttk
    style = ttk.Style(root)
    name = native_theme_name(style.theme_names())
    style.theme_use(name)
    family = _unify_fonts(root)
    bold = (family, SIZE_BODY, "bold")
    if name == "clam":
        _style_clam(style, bold)
        bg = WINDOW_BG
    else:
        # Native look kept as is. Only the main-action button gets bold text, and cards a border.
        style.configure("Primary.TButton", font=bold, padding=(14, 5))
        style.configure("Card.TFrame", relief="solid", borderwidth=1)
        style.configure("Treeview", rowheight=26)
        style.configure("Treeview.Heading", font=bold)
        bg = style.lookup("TFrame", "background") or root.cget("bg")
        root.configure(bg=bg)
    return {"bg": bg, "family": family, "theme": name}


def _style_clam(style, bold) -> None:
    """Flat, light styling for Linux. White buttons with a thin edge, a blue main button."""
    style.configure(".", background=WINDOW_BG, foreground=TEXT, bordercolor=EDGE, darkcolor=WINDOW_BG,
                    lightcolor=WINDOW_BG, troughcolor=HEADING_BG, focuscolor=ACCENT, selectbackground=SELECT_BG,
                    selectforeground=TEXT, insertcolor=TEXT)
    style.configure("TFrame", background=WINDOW_BG)
    # a single 1 px border: light and dark edge colours match the border colour
    style.configure("Card.TFrame", background=WINDOW_BG, relief="solid", borderwidth=1, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER)
    style.configure("TLabel", background=WINDOW_BG, foreground=TEXT)
    style.configure("TSeparator", background=BORDER)

    style.configure("TButton", background=FIELD_BG, foreground=TEXT, bordercolor=EDGE, lightcolor=FIELD_BG,
                    darkcolor=FIELD_BG, padding=(12, 5), anchor="center")
    style.map("TButton", background=[("disabled", WINDOW_BG), ("pressed", PRESSED), ("active", HOVER)],
              foreground=[("disabled", DISABLED_FG)], bordercolor=[("focus", ACCENT), ("disabled", BORDER)],
              lightcolor=[("pressed", PRESSED), ("active", HOVER)], darkcolor=[("pressed", PRESSED), ("active", HOVER)])
    style.configure("Primary.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT, padding=(14, 5), font=bold)
    style.map("Primary.TButton", background=[("disabled", DISABLED_BG), ("pressed", "#004a91"), ("active", "#0a6fd1")],
              foreground=[("disabled", DISABLED_FG)], bordercolor=[("disabled", DISABLED_BG), ("focus", TEXT)],
              lightcolor=[("disabled", DISABLED_BG), ("pressed", "#004a91"), ("active", "#0a6fd1")],
              darkcolor=[("disabled", DISABLED_BG), ("pressed", "#004a91"), ("active", "#0a6fd1")])
    style.configure("Toolbutton", background=FIELD_BG, foreground=TEXT, bordercolor=EDGE, lightcolor=FIELD_BG,
                    darkcolor=FIELD_BG, padding=(12, 5), anchor="center")
    style.map("Toolbutton", background=[("selected", ACCENT), ("pressed", PRESSED), ("active", HOVER)],
              foreground=[("selected", "#ffffff"), ("disabled", DISABLED_FG)],
              lightcolor=[("selected", ACCENT), ("active", HOVER)], darkcolor=[("selected", ACCENT), ("active", HOVER)],
              bordercolor=[("selected", ACCENT)])
    style.configure("TMenubutton", background=FIELD_BG, foreground=TEXT, bordercolor=EDGE, arrowcolor=TEXT,
                    lightcolor=FIELD_BG, darkcolor=FIELD_BG, padding=(12, 5))
    style.map("TMenubutton", background=[("active", HOVER)])

    style.configure("TEntry", fieldbackground=FIELD_BG, bordercolor=EDGE, lightcolor=FIELD_BG, darkcolor=FIELD_BG,
                    padding=5)
    style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)])
    style.configure("TCheckbutton", background=WINDOW_BG, indicatorbackground=FIELD_BG, indicatorforeground=ACCENT,
                    upperbordercolor=EDGE, lowerbordercolor=EDGE)
    style.map("TCheckbutton", background=[("active", WINDOW_BG)], foreground=[("disabled", DISABLED_FG)])

    style.configure("Treeview", background=FIELD_BG, fieldbackground=FIELD_BG, foreground=TEXT, bordercolor=EDGE,
                    rowheight=26, relief="flat")
    style.map("Treeview", background=[("selected", SELECT_BG)], foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=HEADING_BG, foreground=TEXT, relief="flat", padding=(8, 5),
                    bordercolor=EDGE, lightcolor=HEADING_BG, darkcolor=HEADING_BG, font=bold)
    style.map("Treeview.Heading", background=[("active", HOVER)])
    style.configure("TScrollbar", background="#c7cbd1", troughcolor=WINDOW_BG, bordercolor=WINDOW_BG,
                    lightcolor="#c7cbd1", darkcolor="#c7cbd1", arrowcolor=TEXT, gripcount=0, relief="flat")
    style.map("TScrollbar", background=[("active", "#a9aeb5"), ("pressed", "#8f959c")],
              lightcolor=[("active", "#a9aeb5")], darkcolor=[("active", "#a9aeb5")])
    style.configure("TProgressbar", background=ACCENT, troughcolor=HEADING_BG, bordercolor=EDGE,
                    lightcolor=ACCENT, darkcolor=ACCENT)
    style.configure("TPanedwindow", background=WINDOW_BG)
    style.master.configure(bg=WINDOW_BG)


# ---------------------------------------------------------------- text size (WCAG 1.4.4)
_named_base: dict = {}


def scale_fonts(root, factor: float, extra=()) -> None:
    """Resize every named font, and the Font objects in ``extra``, to factor x their normal
    size (1.0 = normal, 2.0 = double)."""
    for name in tkfont.names(root):
        f = named_font(name, root)
        base = _named_base.setdefault(name, f.actual("size"))
        f.configure(size=max(6, round(base * factor)))
    for f in extra:
        base = getattr(f, "_base_size", None)
        if base is None:
            base = f._base_size = f.actual("size")
        f.configure(size=max(6, round(base * factor)))


class Fonts:
    """The fonts the GUI uses, on the same family and scale as the theme."""

    def __init__(self, root=None):
        base = named_font("TkDefaultFont", root)
        family = base.actual("family")
        semi = "Segoe UI Semibold" if family == "Segoe UI" and "Segoe UI Semibold" in tkfont.families(root) else None

        def make(size: int, strong: bool = False, **kw) -> tkfont.Font:
            if strong and semi:
                return tkfont.Font(root=root, family=semi, size=size, **kw)
            return tkfont.Font(root=root, family=family, size=size, weight="bold" if strong else "normal", **kw)

        self.base = base
        self.bold = make(SIZE_BODY, strong=True)
        self.heading = make(SIZE_HEADING, strong=True)
        self.title = make(SIZE_TITLE, strong=True)
        self.small = make(SIZE_SMALL)
        self.link = make(SIZE_BODY, underline=True)

    def all(self):
        """The Font objects made here (TkDefaultFont is scaled as a named font)."""
        return (self.bold, self.heading, self.title, self.small, self.link)
