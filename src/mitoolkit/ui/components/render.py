"""Anti-aliased, high resolution drawing for the dashboard, using Pillow.

Tk's canvas draws jagged lines and corners (no anti-aliasing), which makes charts look pixelated. So
the curves, gradients, rings and card backgrounds are drawn here at 3 times the size and scaled down
(supersampling), then shown on the canvas as images. Text stays on the canvas, so it keeps the
system's own text rendering. If Pillow (or its Tk bridge) is missing, ``HAVE`` is False and the
widgets fall back to plain canvas drawing.

Chart.js is the reference for the look: smooth curves (cubic interpolation that does not overshoot),
a vertical gradient fill under the line, round line caps and soft dots.
"""
from __future__ import annotations

import itertools
import math
import threading
from collections import OrderedDict
from typing import List, Optional, Sequence, Tuple

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageTk
    HAVE = True
except Exception:  # Pillow is optional at run time: the GUI still works, just less smooth
    HAVE = False

SS = 3                      # supersampling factor
Point = Tuple[float, float]


def rgb(colour: str) -> Tuple[int, int, int]:
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def photo(image):
    """A Tk image for a Pillow image. Keep a reference to it for as long as it is shown."""
    return ImageTk.PhotoImage(image)


def smooth(points: Sequence[Point]) -> List[Point]:
    """A cubic curve through the points (Catmull-Rom), kept from overshooting between neighbours, as
    Chart.js' monotone interpolation does. Fewer steps per segment when there are many points."""
    n = len(points)
    if n < 3:
        return list(points)
    steps = 6 if n < 60 else 4 if n < 120 else 2 if n < 240 else 1
    out: List[Point] = []
    for i in range(n - 1):
        p0, p1, p2, p3 = points[max(i - 1, 0)], points[i], points[i + 1], points[min(i + 2, n - 1)]
        lo, hi = min(p1[1], p2[1]), max(p1[1], p2[1])
        for s in range(steps):
            t = s / steps
            x = 0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t * t
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t ** 3)
            y = 0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t * t
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t ** 3)
            out.append((x, min(max(y, lo), hi)))
    out.append(points[-1])
    return out


_ramps: "OrderedDict[Tuple[int, int, float], object]" = OrderedDict()
_ramps_lock = threading.Lock()      # plot_image runs on worker threads


def _gradient_alpha(size: Tuple[int, int], top_alpha: float):
    """A vertical alpha ramp: opaque-ish at the top, clear at the bottom (cached by size)."""
    key = (size[0], size[1], top_alpha)
    with _ramps_lock:
        ramp = _ramps.get(key)
        if ramp is None:
            ramp = ImageOps.invert(Image.linear_gradient("L")).resize(size, Image.BILINEAR)
            ramp = _ramps[key] = ramp.point(lambda v: int(v * top_alpha))
            while len(_ramps) > 12:
                _ramps.popitem(last=False)
        else:
            _ramps.move_to_end(key)
    return ramp


def plot_image(width: int, height: int, runs_by_series: Sequence[Sequence[Sequence[Point]]],
               colours: Sequence[str], fill_first: bool = True, line_width: float = 2.2, ss: int = 2):
    """The graph itself (curves, gradient, newest-reading dots) as an RGBA image of width x height,
    from point lists in the image's own pixel coordinates. Drawn at `ss` times the size and scaled
    down (2x keeps the once-a-second redraw of several graphs cheap; it already removes the jaggies)."""
    big_size = (width * ss, height * ss)
    big = Image.new("RGBA", big_size, (0, 0, 0, 0))
    lw = max(1, int(line_width * ss))
    for index, (runs, colour) in enumerate(zip(runs_by_series, colours)):
        for run in runs:
            if len(run) < 2:
                continue
            pts = [(x * ss, y * ss) for x, y in smooth(run)]
            if index == 0 and fill_first:
                mask = Image.new("L", big_size, 0)
                ImageDraw.Draw(mask).polygon(pts + [(pts[-1][0], big_size[1]), (pts[0][0], big_size[1])], fill=255)
                layer = Image.new("RGBA", big_size, rgb(colour) + (0,))
                layer.putalpha(ImageChops.multiply(_gradient_alpha(big_size, 0.30), mask))
                big.alpha_composite(layer)
            draw = ImageDraw.Draw(big)
            draw.line(pts, fill=rgb(colour) + (255,), width=lw, joint="curve")
            for x, y in (pts[0], pts[-1]):  # round caps
                draw.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=rgb(colour) + (255,))
    draw = ImageDraw.Draw(big)
    for runs, colour in zip(runs_by_series, colours):  # a soft dot on the newest reading
        if runs and runs[-1]:
            x, y = runs[-1][-1][0] * ss, runs[-1][-1][1] * ss
            for radius, fill in ((6, rgb(colour) + (60,)), (4.2, rgb(colour) + (255,)), (1.8, (255, 255, 255, 255))):
                r = radius * ss
                draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)
    return big.resize((width, height), Image.BOX)       # an exact whole-number reduction: BOX averages it, and is fast


def ring_image(size: int, percent: Optional[float], colour: str, track: str, thickness: int = 11):
    """A gauge ring: a grey track over 270 degrees (open at the bottom) and a coloured arc with
    round ends for the value. Anti-aliased; RGBA so it sits on any card."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    t = thickness * SS
    pad = t // 2 + 9 * SS              # room outside the ring for the tick marks
    box = (pad, pad, s - pad, s - pad)
    radius = (s - 2 * pad) / 2 - t / 2      # the middle of the stroke (an arc's width grows inward from the box)
    cx = cy = s / 2

    def cap(angle: float, fill) -> None:
        x, y = cx + radius * math.cos(math.radians(angle)), cy + radius * math.sin(math.radians(angle))
        draw.ellipse((x - t / 2, y - t / 2, x + t / 2, y + t / 2), fill=fill)

    start, sweep = 135, 270            # PIL angles run clockwise from 3 o'clock: 135 = lower left
    # fine tick marks every 10% just outside the ring, like ECharts' progress gauge
    outer = radius + t / 2 + 2 * SS
    for k in range(11):
        a = math.radians(start + sweep * k / 10)
        long = k % 5 == 0
        r0, r1 = outer, outer + (4 if long else 2.5) * SS
        draw.line((cx + r0 * math.cos(a), cy + r0 * math.sin(a), cx + r1 * math.cos(a), cy + r1 * math.sin(a)),
                  fill=(160, 166, 176, 255) if long else (200, 204, 212, 255), width=max(1, SS // 2 + 1))
    draw.arc(box, start, start + sweep, fill=rgb(track) + (255,), width=t)
    cap(start, rgb(track) + (255,))
    cap(start + sweep, rgb(track) + (255,))
    if percent is not None and percent > 0:
        end = start + sweep * min(max(percent, 0), 100) / 100
        draw.arc(box, start, end, fill=rgb(colour) + (255,), width=t)
        cap(start, rgb(colour) + (255,))
        cap(end, rgb(colour) + (255,))
    return img.resize((size, size), Image.BOX)


def _plug(draw, cx: float, cy: float, u: float, colour: Tuple[int, int, int, int]) -> None:
    """A USB plug: a connector with two pins on a cable. ``u`` is one design pixel in drawing units."""
    w = 1.7 * u
    draw.rounded_rectangle((cx - 3.8 * u, cy - 7.4 * u, cx + 3.8 * u, cy - 1.6 * u), 1.2 * u, outline=colour, width=round(w))
    for dx in (-1.5, 1.5):                                           # the two pins
        draw.rectangle((cx + (dx - 0.55) * u, cy - 5.9 * u, cx + (dx + 0.55) * u, cy - 3.6 * u), fill=colour)
    draw.line((cx, cy - 1.6 * u, cx, cy + 5.6 * u), fill=colour, width=round(1.9 * u))
    draw.ellipse((cx - 0.95 * u, cy + 4.65 * u, cx + 0.95 * u, cy + 6.55 * u), fill=colour)       # round cable end


def _wifi(draw, cx: float, cy: float, u: float, colour: Tuple[int, int, int, int]) -> None:
    """The Wi-Fi symbol: three arcs over a dot, with round ends."""
    base = cy + 4.6 * u
    for radius in (4.2, 7.6, 11.0):
        r = radius * u
        draw.arc((cx - r, base - r, cx + r, base + r), 225, 315, fill=colour, width=round(1.9 * u))
        for angle in (225, 315):                                   # round caps (PIL's arcs end square)
            x, y = cx + r * math.cos(math.radians(angle)), base + r * math.sin(math.radians(angle))
            draw.ellipse((x - 0.95 * u, y - 0.95 * u, x + 0.95 * u, y + 0.95 * u), fill=colour)
    draw.ellipse((cx - 1.7 * u, base - 1.7 * u, cx + 1.7 * u, base + 1.7 * u), fill=colour)


def toggle_image(width: int, height: int, pos: float, fill: str, border: str, thumb: str, thumb_size: int, pad: int,
                 stretch: int, glyph: str, glyph_colour: str, ring: str, margin: int, k: float):
    """The track, thumb (with a soft shadow and a glyph) and optional focus ring of a toggle switch, anti-aliased, on a
    transparent background. Sizes are device pixels; ``pos`` is 0 (thumb left) to 1 (right); ``k`` is the screen's
    scale over 96 dpi, so lines and the glyph stay in proportion on a high-DPI display."""
    s = 4
    w, h, m = width * s, height * s, margin * s
    img = Image.new("RGBA", ((width + 2 * margin) * s, (height + 2 * margin) * s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if ring:
        gap = margin * s // 2
        draw.rounded_rectangle((m - gap, m - gap, m + w + gap, m + h + gap), h // 2 + gap, outline=rgb(ring) + (255,),
                               width=max(2, round(2 * k * s)))
    draw.rounded_rectangle((m, m, m + w, m + h), h // 2, fill=rgb(border) + (255,))
    inset = max(1, round(k)) * s
    draw.rounded_rectangle((m + inset, m + inset, m + w - inset, m + h - inset), (h - 2 * inset) // 2, fill=rgb(fill) + (255,))
    # the thumb: it slides, stretching towards where it is going while pressed
    size, p = thumb_size * s, pad * s
    left = m + p + (w - size - 2 * p) * pos - stretch * s * pos
    right = left + size + stretch * s
    top = m + (h - size) / 2
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((left, top + 1.6 * k * s, right, top + size + 1.6 * k * s), fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(1.3 * k * s)))
    draw = ImageDraw.Draw(img)
    draw.ellipse((left, top, right, top + size), fill=rgb(thumb) + (255,), outline=(0, 0, 0, 28), width=max(1, round(k * s / 2)))
    cx, cy = (left + right) / 2, top + size / 2
    colour = rgb(glyph_colour) + (255,)
    (_plug if glyph == "usb" else _wifi)(draw, cx, cy, k * s, colour)
    return img.resize((width + 2 * margin, height + 2 * margin), Image.LANCZOS)


def toggle_photo(*spec):
    """The toggle switch as a cached Tk image (position rounded to 1/24, so the animation reuses its frames)."""
    spec = list(spec)
    spec[2] = round(spec[2] * 24) / 24
    return _cached(("toggle",) + tuple(spec), lambda: toggle_image(*spec))


_photos: "OrderedDict[Tuple, object]" = OrderedDict()
MAX_PHOTOS = 96            # images kept; the least recently used go first
_root_tokens = itertools.count(1)


def _cached(key: Tuple, make):
    """Tk images are slow to make and must stay referenced, so keep the recent ones (a least recently
    used cache, so what is on screen stays and old sizes and values are released one by one). An
    image belongs to one Tk interpreter, so the cache is keyed by it (tests make several)."""
    import tkinter
    root = tkinter._default_root
    token = getattr(root, "_mitoolkit_image_token", None)
    if token is None:                       # a number that is never reused (a destroyed window's address can be)
        token = next(_root_tokens)
        if root is not None:
            root._mitoolkit_image_token = token
    key = (token,) + key
    if key in _photos:
        _photos.move_to_end(key)
        return _photos[key]
    image = _photos[key] = photo(make())
    while len(_photos) > MAX_PHOTOS:
        _photos.popitem(last=False)
    return image


def release_images() -> None:
    """Drop every cached image (for housekeeping when memory runs high); they are rebuilt on demand."""
    _photos.clear()
    with _ramps_lock:
        _ramps.clear()


def card_photo(width: int, height: int, bg: str, box: Tuple[int, int, int, int], radius: int = 10):
    """A white rounded card with a soft blurred shadow and a hairline border, on the page colour, as
    a Tk image of width x height. `box` is where the card itself sits inside it (x0, y0, x1, y1)."""

    def make():
        # The shadow is soft, so it is blurred at normal size (cheap). Only the card's crisp edges need
        # supersampling, and 2x is plenty for those: a card is made in a few milliseconds, which matters
        # because every new window size needs its own image.
        s = 2
        x0, y0, x1, y1 = box
        base = Image.new("RGB", (width, height), rgb(bg))
        shadow = Image.new("L", (width, height), 0)
        ImageDraw.Draw(shadow).rounded_rectangle((x0, y0 + 3, x1, y1 + 3), radius, fill=255)
        shadow = shadow.filter(ImageFilter.GaussianBlur(4)).point(lambda v: int(v * 0.14))
        base.paste(Image.new("RGB", (width, height), (0, 0, 0)), mask=shadow)
        card = Image.new("RGBA", (width * s, height * s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(card)
        draw.rounded_rectangle((x0 * s, y0 * s, x1 * s, y1 * s), radius * s, fill=(227, 230, 236, 255))
        draw.rounded_rectangle(((x0 + 1) * s, (y0 + 1) * s, (x1 - 1) * s, (y1 - 1) * s), (radius - 1) * s,
                               fill=(255, 255, 255, 255))
        card = card.resize((width, height), Image.BOX)
        base.paste(card, mask=card.getchannel("A"))
        return base

    return _cached(("card", width, height, bg, box, radius), make)


def ring_photo(size: int, percent: Optional[float], colour: str, track: str, thickness: int = 11):
    """The gauge ring as a cached Tk image (the value is rounded to a whole percent)."""
    pct = None if percent is None else round(percent)
    return _cached(("ring", size, pct, colour, track, thickness), lambda: ring_image(size, pct, colour, track, thickness))


def spark_image(width: int, height: int, points: Sequence[Point], colour: str):
    """A small smooth line over a soft fill, for a core's trend."""
    return plot_image(width, height, [[list(points)]] if len(points) >= 2 else [[]], [colour], fill_first=True,
                      line_width=1.8)
