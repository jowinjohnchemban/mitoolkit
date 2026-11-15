"""Small drawing helpers shared by the buttons, charts and cards: rounded rectangles, colour mixing
and the soft shadow card."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from miunlock.ui.components import render

CARD = "#ffffff"
CARD_BORDER = "#e3e6ec"


def rounded(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, r: float, **kw) -> int:
    """A rounded rectangle (a smoothed polygon)."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(pts, smooth=True, **kw)


def mix(a: str, b: str, t: float) -> str:
    """Colour a moved a fraction t of the way to colour b."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def _luminance(colour: str) -> float:
    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(int(colour[i:i + 2], 16) / 255) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours (1 to 21)."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def text_colour(colour: str, background: str = "#ffffff", ratio: float = 4.5) -> str:
    """The colour, darkened just enough to be readable as text on the background (WCAG 1.4.3). The
    chart palette is chosen for lines (3:1); words and numbers in the same hue need this."""
    for step in range(21):
        candidate = mix(colour, "#000000", step * 0.05)
        if contrast_ratio(candidate, background) >= ratio:
            return candidate
    return "#000000"


def page_background(widget) -> str:
    """The colour of the window behind a card (so its corners and shadow blend in)."""
    colour = ttk.Style(widget).lookup("TFrame", "background") or "#f0f0f0"
    try:  # the theme may answer with a system colour name ("systemButtonFace"); we need hex to blend
        r, g, b = widget.winfo_rgb(colour)
        return f"#{r >> 8:02x}{g >> 8:02x}{b >> 8:02x}"
    except tk.TclError:
        return "#f0f0f0"


def draw_card(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, bg: str, radius: float = 10,
              tag: str = "card") -> None:
    """A white rounded card with a soft shadow and a hairline border. With Pillow it is an
    anti-aliased image with a blurred shadow; without, three faint layers of plain shapes."""
    if render.HAVE:
        w, h = int(canvas.winfo_width()), int(canvas.winfo_height())
        if w > 20 and h > 20:
            image = render.card_photo(w, h, bg, (round(x0), round(y0), round(x1), round(y1)), round(radius))
            canvas.create_image(0, 0, image=image, anchor="nw", tags=tag)
            return
    for offset, strength in ((3, 0.025), (2, 0.04), (1, 0.06)):
        rounded(canvas, x0, y0 + offset, x1, y1 + offset, radius, fill=mix(bg, "#000000", strength), outline="",
                tags=tag)
    rounded(canvas, x0, y0, x1, y1, radius, fill=CARD_BORDER, outline="", tags=tag)
    rounded(canvas, x0 + 1, y0 + 1, x1 - 1, y1 - 1, radius - 1, fill=CARD, outline="", tags=tag)


class Card(tk.Canvas):
    """A rounded card with a soft shadow that holds ordinary widgets: put them in ``card.body``
    (a white frame). The card grows to fit what is inside."""

    PAD = 12
    SHADOW = 6

    def __init__(self, parent):
        self._bg = page_background(parent)
        super().__init__(parent, bg=self._bg, highlightthickness=0, borderwidth=0)
        self.body = tk.Frame(self, bg=CARD)
        self._win = self.create_window(self.PAD + 2, self.PAD, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: self._fit())
        self.bind("<Configure>", lambda _e: self._paint())

    def _fit(self) -> None:
        height = self.body.winfo_reqheight() + 2 * self.PAD + self.SHADOW
        if int(self.cget("height")) != height:
            self.configure(height=height)

    def _paint(self) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        self.delete("card")
        draw_card(self, 2, 1, w - 3, h - self.SHADOW, self._bg, tag="card")
        self.itemconfigure(self._win, width=max(10, w - 2 * self.PAD - 4))
        self.tag_lower("card")
