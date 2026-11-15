"""Dashboard charts drawn on a Tk canvas, in the style of Apache ECharts, Grafana and current
web dashboards: rounded cards with a soft shadow, a big headline value, smooth lines over a soft
gradient, light split lines, dashed thresholds, a floating tooltip with a crosshair, a marker on
the highest value, a live dot on the newest value, and ring gauges. No extra libraries.

Newest value on the right. Keeps up to an hour of readings and shows the last 1 to 60 minutes
(set_window); long windows are averaged into buckets so the line stays smooth. The title, the
headline value and the legend (last, lowest, average, highest) are real text, never colour alone.
Line colours are ECharts' defaults, darkened where needed to keep 3:1 contrast on the white card
(WCAG 1.4.11).
"""
from __future__ import annotations

import math
import time
import tkinter as tk
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Sequence, Tuple

from mitoolkit import workers
from mitoolkit.ui.components import render
from mitoolkit.ui.components.shapes import CARD, draw_card, page_background, rounded, text_colour
from mitoolkit.ui.components.skeleton import bar_colour, clock

# ECharts' default palette, kept where it reads well on white (>= 3:1)
BLUE = "#5470c6"
GREEN = "#3ba272"
RED = "#ee6666"
ORANGE = "#e8590c"
PURPLE = "#9a60b4"

# Threshold colours (Grafana: green / yellow / red), darkened for 3:1 on white
OK_COLOUR, WARN_COLOUR, CRIT_COLOUR = "#2f9e6b", "#b8860b", "#d6554d"

CARD_BORDER = "#e3e6ec"
GRID = "#e8ebf2"          # split lines
AXIS_TEXT = "#6e7079"     # ECharts' axis label colour
TEXT = "#1b1b1b"
TOOLTIP_BORDER = "#d0d4da"
MAX_SECONDS = 3600         # one hour of history
BANDS = 22                 # strips that fake the gradient under a line
PAD = 16                   # inside the card
PLOT_MIN = 112             # least height of the plot itself
# the shape of the placeholder bars shown until the first readings arrive
SKELETON_BARS = (.35, .5, .42, .66, .55, .74, .48, .6, .82, .58, .44, .7, .52, .38, .64, .78, .5, .46, .68, .56, .4,
                 .72, .6, .48, .54, .36)


def nice_ceiling(value: float) -> float:
    """Round a maximum up to a tidy axis end (chosen so the four gridline values stay tidy)."""
    if value <= 0:
        return 1.0
    magnitude = 1.0
    while value > 10 * magnitude:
        magnitude *= 10
    while value < magnitude:
        magnitude /= 10
    for step in (1, 1.2, 1.6, 2, 2.4, 3.2, 4, 4.8, 6.4, 8, 10):  # four gridlines apart: tidy tick values
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def tint(colour: str, amount: float) -> str:
    """The colour mixed with white: amount 1 = the colour, 0 = white."""
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    mixed = lambda c: round(255 - (255 - c) * amount)  # noqa: E731
    return f"#{mixed(r):02x}{mixed(g):02x}{mixed(b):02x}"


def duration(seconds: float) -> str:
    seconds = round(seconds)
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600} hr"
    return f"{seconds} s" if seconds < 90 else f"{seconds / 60:.0f} min"


def tick_label(seconds: float) -> str:
    """A time-axis label: "30 s", "4 min", "3:45" (not "225 s"), "1 hr"."""
    s = round(seconds)
    if s >= 3600 and s % 3600 == 0:
        return f"{s // 3600} hr"
    if s < 60:
        return f"{s} s"
    return f"{s // 60} min" if s % 60 == 0 else f"{s // 60}:{s % 60:02d}"


def bucket(values: Sequence[Optional[float]], size: int) -> List[Optional[float]]:
    """Average groups of `size` readings, counted back from the newest. None if a group is empty."""
    if size <= 1:
        return list(values)
    out: List[Optional[float]] = []
    for end in range(len(values), 0, -size):
        group = [v for v in values[max(0, end - size):end] if v is not None]
        out.append(sum(group) / len(group) if group else None)
    return out[::-1]


class LineChart(tk.Canvas):
    """One dashboard panel: a rounded card with the title, a big current value, the plot and a
    one-line legend per series (last, lowest, average, highest)."""

    def __init__(self, parent, title: str, series: Sequence[Tuple[str, str]], fonts, *,
                 interval: float = 1.0, window: int = 60, ymin: float = 0.0, ymax: Optional[float] = None,
                 min_top: float = 1.0, fmt: Callable[[float], str] = lambda v: f"{v:g}",
                 thresholds: Sequence[Tuple[float, str, str]] = ()):
        """series: [(name, colour)]. ymax None = scale to the data (at least ymin + min_top).
        thresholds: [(value, colour, label)] drawn as dashed lines, like a Grafana threshold."""
        self._bg = page_background(parent)
        super().__init__(parent, bg=self._bg, highlightthickness=0, borderwidth=0, cursor="crosshair", width=240)
        self.series = list(series)
        self.title, self.thresholds = title, list(thresholds)
        self.interval, self.window = interval, window
        self.ymin, self.ymax, self.min_top, self.fmt, self.fonts = ymin, ymax, min_top, fmt, fonts
        self.data: List[Deque[Optional[float]]] = [
            deque(maxlen=int(MAX_SECONDS / interval)) for _ in self.series]
        self._hover: Optional[int] = None   # pointer x, or None
        self._group = 1                      # readings averaged into one point
        self.loading = True                  # a skeleton shows until the first reading
        self._revision = 0                   # bumps when the data or range changes (the plot image's cache key)
        self._plot_key: Optional[tuple] = None
        self._plot_photo = None
        self._draw_job: Optional[str] = None
        self._ss = 2                         # supersampling; drops to 1 on a slow machine
        self._plot_busy = False              # a plot image is being rendered on a worker thread
        self._want_plot: Optional[tuple] = None
        self._pil_failed = False
        self._gone = False
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._fit()
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Map>", lambda _e: self.draw())
        self.bind("<Motion>", self._on_move)
        self.bind("<Leave>", self._on_leave)

    # -------------------------------------------------------------- sizing
    def _metrics(self) -> Dict[str, int]:
        f = self.fonts
        small, bold, big = f.small.metrics("linespace"), f.bold.metrics("linespace"), f.heading.metrics("linespace")
        head = max(bold, big)
        legend = len(self.series) * (small + 6)
        axis = small + 8
        need = PAD + head + 10 + PLOT_MIN + axis + legend + PAD + 6
        return {"small": small, "head": head, "legend": legend, "axis": axis, "need": need}

    def _fit(self) -> None:
        need = self._metrics()["need"]
        if int(self.cget("height")) != need:
            self.configure(height=need)

    def refresh(self) -> None:
        self._fit()
        self.draw()

    def _on_destroy(self, event) -> None:
        if event.widget is self:                  # release what this chart holds, at once
            self._gone = True
            self._plot_photo = None
            self._want_plot = None
            for buf in self.data:
                buf.clear()

    # ---------------------------------------------------------------- data
    def push(self, *values: Optional[float], redraw: bool = True) -> None:
        """Add one reading per series. Pass redraw=False when adding several in a row, then call
        redraw() once."""
        for buf, value in zip(self.data, values):
            buf.append(value)
        self._revision += 1
        if redraw:
            self._queue_draw()

    def set_window(self, seconds: int) -> None:
        self.window = seconds
        self._revision += 1
        self._queue_draw()

    def clear(self) -> None:
        for buf in self.data:
            buf.clear()
        self._revision += 1
        self._queue_draw()

    def redraw(self) -> None:
        self._queue_draw()

    def _queue_draw(self) -> None:
        """Draw once when the UI is idle, however many changes arrive before then (a burst of
        readings or a stream of pointer moves costs one draw, not one each)."""
        if self._draw_job is None:
            try:
                self._draw_job = self.after_idle(self._draw_now)
            except tk.TclError:  # the widget is gone
                self._draw_job = None

    def _draw_now(self) -> None:
        self._draw_job = None
        try:
            self.draw()
        except tk.TclError:  # destroyed while a draw was waiting
            pass

    def _visible(self, buf) -> List[Optional[float]]:
        return list(buf)[-max(2, int(self.window / self.interval)):]

    def stats(self, index: int = 0) -> Optional[Dict[str, float]]:
        """Last, lowest, average and highest value of one series over the range in view."""
        buf = self.data[index]
        shown = [v for v in self._visible(buf) if v is not None]
        if not shown:
            return None
        last = buf[-1] if buf and buf[-1] is not None else shown[-1]
        return {"last": last, "min": min(shown), "avg": sum(shown) / len(shown), "max": max(shown)}

    # ------------------------------------------------------------- hovering
    def _on_move(self, event) -> None:
        self._hover = event.x
        self._queue_draw()

    def _on_leave(self, _event) -> None:
        self._hover = None
        self._queue_draw()

    # ------------------------------------------------------------- drawing
    def draw(self) -> None:
        if not self.winfo_ismapped():  # on a hidden tab: draw when it is shown again (see <Map>)
            return
        self._fit()
        c = self
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 160 or h < 120:
            return
        m = self._metrics()
        f = self.fonts
        x0, y0, x1, y1 = 2, 1, w - 3, h - 6
        draw_card(c, x0, y0, x1, y1, self._bg)

        # title (left) and the headline value (right)
        c.create_text(x0 + PAD, y0 + PAD, text=self.title, anchor="nw", fill=TEXT, font=f.bold)
        last = self.stats(0)
        if last:
            c.create_text(x1 - PAD, y0 + PAD - 2, text=self.fmt(last["last"]), anchor="ne",
                          fill=text_colour(self.series[0][1]),
                          font=f.heading)

        # the plot
        slots = max(2, int(self.window / self.interval))
        left = x0 + PAD + f.small.measure("0000") + 8
        right = x1 - PAD
        top = y0 + PAD + m["head"] + 12
        base = y1 - PAD - m["legend"] - m["axis"]
        pw, ph = right - left, base - top
        if pw < 40 or ph < 40:
            return
        group = self._group = max(1, math.ceil(slots / max(40, pw // 3)))
        columns = math.ceil(slots / group)
        step = pw / max(columns - 1, 1)
        shown = [bucket(self._visible(buf), group) for buf in self.data]
        values = [v for col in shown for v in col if v is not None]
        top_value = self.ymax if self.ymax is not None else self.ymin + nice_ceiling(
            max([v - self.ymin for v in values] + [self.min_top]) * 1.1)
        span = (top_value - self.ymin) or 1.0

        def y(v: float) -> float:
            return base - (min(max(v, self.ymin), top_value) - self.ymin) / span * ph

        self.loading = not values
        if self.loading:  # a skeleton: shimmering placeholder bars in the shape of a chart
            clock.watch(self)
            self._skeleton(x0, x1, y0, left, right, top, base, m)
        for k in range(5):  # five split lines with their values, like ECharts' value axis
            value = self.ymin + span * k / 4
            c.create_line(left, y(value), right, y(value), fill=GRID)
            c.create_text(left - 8, y(value), text=f"{value:g}", anchor="e", fill=AXIS_TEXT, font=f.small)
        for value, colour, label in self.thresholds:  # dashed threshold lines, as on a Grafana panel
            if self.ymin < value < top_value:
                c.create_line(left, y(value), right, y(value), fill=colour, dash=(6, 4))
                c.create_text(right - 2, y(value) - 8, text=label, anchor="e", fill=text_colour(colour), font=f.small)
        # a time axis like ECharts' dynamic-data example: ticks and labels at each quarter of the range
        for k in range(1, 4):
            tx = left + pw * k / 4
            c.create_line(tx, base, tx, base + 4, fill=AXIS_TEXT)
            c.create_text(tx, base + 6, text=tick_label(self.window * (4 - k) / 4), anchor="n", fill=AXIS_TEXT, font=f.small)
        c.create_text(left, base + 6, text=f"{duration(self.window)} ago", anchor="nw", fill=AXIS_TEXT, font=f.small)
        c.create_text(right, base + 6, text="now", anchor="ne", fill=AXIS_TEXT, font=f.small)

        runs_by_series: List[List[List[Tuple[float, float]]]] = []
        for col in shown:
            runs: List[List[Tuple[float, float]]] = []
            run: List[Tuple[float, float]] = []
            n = len(col)
            for i, v in enumerate(col):
                x = right - (n - 1 - i) * step
                if v is None:
                    if run:
                        runs.append(run)
                    run = []
                else:
                    run.append((x, y(v)))
            if run:
                runs.append(run)
            runs_by_series.append(runs)

        if render.HAVE and not self.loading and not self._pil_failed:
            self._draw_plot_image(runs_by_series, left, top, pw, ph, top_value)
        else:
            self._draw_plot_canvas(runs_by_series, top, ph)
        self._mark_highest(shown, y, right, step)
        if not self.loading:
            self._legend(x0 + PAD, x1 - PAD, base + m["axis"] + 4, m["small"])

        if self._hover is not None and left <= self._hover <= right:
            self._tooltip(w, shown, left, right, top, base, step, y)

    def _draw_plot_image(self, runs_by_series, left: float, top: float, pw: float, ph: float, top_value: float) -> None:
        """The curves, gradient and newest-reading dots as one anti-aliased image (rendered at 3x and
        scaled down, like a Chart.js canvas on a high-resolution screen). It is rebuilt only when the
        data, size or axis change, not when the pointer moves."""
        width, height = max(int(pw), 1), max(int(ph), 1)
        key = (self._revision, width, height, round(top_value, 6), self._group)
        if self._plot_key != key:
            # Render on a worker thread so the window never waits for Pillow; until the new image is
            # ready the previous one stays on screen (it is a fraction of a second old at most).
            local = [[[(x - left, y - top) for x, y in run] for run in runs] for runs in runs_by_series]
            self._want_plot = (key, width, height, local)
            self._start_plot_job()
        if self._plot_photo is not None:
            self.create_image(left, top, image=self._plot_photo, anchor="nw")

    def _start_plot_job(self) -> None:
        if self._plot_busy or self._want_plot is None or self._gone:
            return
        key, width, height, local = self._want_plot
        colours, ss = [c for _n, c in self.series], self._ss

        def job():
            started = time.perf_counter()
            image = render.plot_image(width, height, local, colours, ss=ss)
            return key, image, (time.perf_counter() - started) * 1000

        self._plot_busy = workers.render_pool.submit(job, self._plot_done)
        if self._plot_busy:
            workers.render_pump.kick(self)

    def _plot_done(self, result, error) -> None:
        """On the window's thread: a finished plot image arrived."""
        self._plot_busy = False
        if self._gone:
            return
        if error is not None or result is None:
            self._pil_failed = True                 # fall back to plain canvas drawing from now on
            self._queue_draw()
            return
        key, image, ms = result
        self._plot_photo = render.photo(image)      # Tk images are made on the window's thread
        self._plot_key = key
        if ms > 70:                                 # a slow machine: draw lighter rather than lag
            self._ss = 1
        self._queue_draw()
        if self._want_plot is not None and self._want_plot[0] != key:
            self._start_plot_job()                  # the data moved on while this one was drawn

    def _draw_plot_canvas(self, runs_by_series, top: float, ph: float) -> None:
        """The same, drawn with plain canvas shapes (used when Pillow is not installed)."""
        c = self
        for s, ((_name, colour), runs) in enumerate(zip(self.series, runs_by_series)):
            for run in runs:
                if s == 0 and len(run) >= 2:
                    self._gradient(run, colour, top, ph)
                if len(run) >= 2:
                    flat = [coord for p in run for coord in p]
                    c.create_line(*flat, fill=colour, width=2, smooth=len(run) <= 240, splinesteps=4,
                                  joinstyle="round", capstyle="round")
        for (_name, colour), runs in zip(self.series, runs_by_series):
            if runs and runs[-1]:  # the live dot on the newest reading
                lx, ly = runs[-1][-1]
                c.create_oval(lx - 5, ly - 5, lx + 5, ly + 5, fill=colour, outline="")
                c.create_oval(lx - 2, ly - 2, lx + 2, ly + 2, fill="#ffffff", outline="")

    def _skeleton(self, x0: float, x1: float, y0: float, left: float, right: float, top: float, base: float,
                  m: Dict[str, int]) -> None:
        """Placeholder bars for the plot, the headline value and the legend, with the shared shimmer."""
        n = len(SKELETON_BARS)
        slot = (right - left) / n
        for i, height in enumerate(SKELETON_BARS):
            bx = left + i * slot + slot * 0.2
            self.create_rectangle(bx, base - (base - top) * height, bx + slot * 0.6, base,   # plain rectangles: cheap
                                  fill=bar_colour((bx - left) / max(right - left, 1)), outline="")
        rounded(self, x1 - PAD - 64, y0 + PAD, x1 - PAD, y0 + PAD + 20, 8, fill=bar_colour(0.92), outline="")
        ly = base + m["axis"] + 4 + m["small"] / 2
        rounded(self, x0 + PAD, ly - 5, x0 + PAD + 150, ly + 5, 5, fill=bar_colour(0.1), outline="")
        rounded(self, x1 - PAD - 190, ly - 5, x1 - PAD, ly + 5, 5, fill=bar_colour(0.85), outline="")

    def _gradient(self, run, colour: str, top: float, ph: float) -> None:
        """The soft fade under the first line: horizontal strips from strong (top) to clear."""
        c = self
        for k in range(BANDS):
            y0, y1 = top + ph * k / BANDS, top + ph * (k + 1) / BANDS
            if all(cy >= y1 for _x, cy in run):
                continue  # the line is below this strip: nothing to fill
            upper = [(x, min(max(cy, y0), y1)) for x, cy in run]
            amount = 0.26 * (1 - (k + 0.5) / BANDS) ** 1.2 + 0.01
            poly = [coord for p in upper for coord in p] + [run[-1][0], y1, run[0][0], y1]
            c.create_polygon(*poly, fill=tint(colour, amount), outline="")

    def _mark_highest(self, shown, y, right: float, step: float) -> None:
        """A small rounded label on the highest value in view (ECharts' markPoint)."""
        col = shown[0] if shown else []
        known = [(v, i) for i, v in enumerate(col) if v is not None]
        if len(known) < 5:
            return
        peak, i = max(known)
        x, py = right - (len(col) - 1 - i) * step, y(peak)
        label = self.fmt(peak)
        width = self.fonts.small.measure(label) + 14
        x_mid = min(max(x, 30 + width / 2), right - width / 2)
        top = max(py - 28, 4)
        rounded(self, x_mid - width / 2, top, x_mid + width / 2, top + 20, 6,       # dark enough for its white text
                fill=text_colour(self.series[0][1]), outline="")
        self.create_text(x_mid, top + 10, text=label, fill="#ffffff", font=self.fonts.small)

    def _legend(self, left: float, right: float, top: float, line: int) -> None:
        """One line per series: a coloured dot, its name, then last / lowest / average / highest."""
        small = self.fonts.small
        for row, (name, colour) in enumerate(self.series):
            cy = top + row * (line + 6) + line / 2
            self.create_oval(left, cy - 4, left + 8, cy + 4, fill=colour, outline="")
            self.create_text(left + 14, cy, text=name or "Value", anchor="w", fill=TEXT, font=small)
            st = self.stats(row)
            if not st:
                continue
            parts = [("Last", st["last"]), ("Min", st["min"]), ("Avg", st["avg"]), ("Max", st["max"])]
            x = right
            for label, value in reversed(parts):  # right-aligned: Max, Avg, Min, Last
                text = self.fmt(value)
                self.create_text(x, cy, text=text, anchor="e", fill=TEXT, font=small)
                x -= small.measure(text) + 4
                self.create_text(x, cy, text=label, anchor="e", fill=AXIS_TEXT, font=small)
                x -= small.measure(label) + 14
                if x < left + 14 + small.measure(name or "Value") + 20:
                    break  # not enough room for the rest: keep the ones nearest the right

    def _tooltip(self, w: int, shown, left: float, right: float, top: float, base: float, step: float, y) -> None:
        """The crosshair, a ring on each line and a floating rounded box with the values."""
        c, f = self, self.fonts
        n = max((len(col) for col in shown), default=0)
        if n == 0:
            return
        i = n - 1 - round((right - self._hover) / step)
        if not 0 <= i < n:
            return
        x = right - (n - 1 - i) * step
        c.create_line(x, top, x, base, fill="#9aa0a6", dash=(4, 3))
        rows = []
        for (name, colour), col in zip(self.series, shown):
            idx = i - (n - len(col))
            if 0 <= idx < len(col) and col[idx] is not None:
                c.create_oval(x - 6, y(col[idx]) - 6, x + 6, y(col[idx]) + 6, fill="#ffffff", outline=colour, width=2)
                rows.append((colour, f"{name} {self.fmt(col[idx])}".strip()))
        if not rows:
            return
        ago = (n - 1 - i) * self.interval * self._group
        lines = [(None, f"{duration(ago)} ago" if ago >= 1 else "Now")] + rows
        row_h = f.small.metrics("linespace") + 5
        box_w = max(f.bold.measure(t) if colour else f.small.measure(t) for colour, t in lines) + 36
        box_h = 12 + row_h * len(lines)
        bx = x + 14 if x + 14 + box_w < right + 10 else x - 14 - box_w
        by = max(top - 6, min(top + 4, base - box_h))
        rounded(c, bx + 2, by + 3, bx + box_w + 2, by + box_h + 3, 8, fill="#d9dce2", outline="")  # soft shadow
        rounded(c, bx, by, bx + box_w, by + box_h, 8, fill="#ffffff", outline=TOOLTIP_BORDER)
        for k, (colour, text) in enumerate(lines):
            ty = by + 6 + row_h * k + row_h / 2
            if colour is None:
                c.create_text(bx + 12, ty, text=text, anchor="w", fill=AXIS_TEXT, font=f.small)
            else:
                c.create_oval(bx + 12, ty - 4, bx + 20, ty + 4, fill=colour, outline="")
                c.create_text(bx + 26, ty, text=text, anchor="w", fill=TEXT, font=f.bold)


class Gauge(tk.Canvas):
    """A ring gauge on a rounded card: a grey track, an arc coloured by threshold (green, yellow,
    red) and the value in the middle. The state is also written under the value ("Normal",
    "High", "Critical"), so colour never carries the meaning alone.

    thresholds=(warn, crit): higher is worse, or lower is worse with invert=True (a battery)."""

    RING = 108

    def __init__(self, parent, title: str, fonts, thresholds=(70, 90), invert: bool = False):
        self._bg = page_background(parent)
        super().__init__(parent, bg=self._bg, highlightthickness=0, borderwidth=0, width=120)
        self.title, self.fonts, self.thresholds, self.invert = title, fonts, thresholds, invert
        self.percent: Optional[float] = None
        self.caption = ""
        self.state_text = ""
        self.loading = True                  # a skeleton ring shows until the first reading
        self._draw_job: Optional[str] = None
        self._fit()
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Map>", lambda _e: self.draw())

    def _fit(self) -> None:
        f = self.fonts
        need = 12 + self.RING + 8 + f.bold.metrics("linespace") * 2 + f.small.metrics("linespace") + 22
        if int(self.cget("height")) != need:
            self.configure(height=need)

    def refresh(self) -> None:
        self._fit()
        self.draw()

    def level(self, percent: float) -> Tuple[str, str]:
        """(colour, word) for a value."""
        warn, crit = self.thresholds
        if self.invert:
            return (CRIT_COLOUR, "Critical") if percent <= crit else (WARN_COLOUR, "Low") if percent <= warn else (OK_COLOUR, "Normal")
        return (CRIT_COLOUR, "Critical") if percent >= crit else (WARN_COLOUR, "High") if percent >= warn else (OK_COLOUR, "Normal")

    def set(self, percent: Optional[float], caption: str = "") -> None:
        self.percent, self.caption = percent, caption
        self.state_text = self.level(percent)[1] if percent is not None else ""
        if self._draw_job is None:  # one draw when idle, however many updates arrive first
            try:
                self._draw_job = self.after_idle(self._draw_now)
            except tk.TclError:
                self._draw_job = None

    def _draw_now(self) -> None:
        self._draw_job = None
        try:
            self.draw()
        except tk.TclError:
            pass

    def draw(self) -> None:
        if not self.winfo_ismapped():  # on a hidden tab: draw when it is shown again (see <Map>)
            return
        self._fit()
        c, f = self, self.fonts
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 60 or h < 60:
            return
        draw_card(c, 2, 1, w - 3, h - 6, self._bg)
        cx, ring = w / 2, self.RING
        top = 14
        box = (cx - ring / 2 + 6, top + 6, cx + ring / 2 - 6, top + ring - 6)
        self.loading = self.percent is None
        colour = TEXT
        if self.loading:  # a shimmering skeleton ring and text bars while we wait for the first reading
            clock.watch(self)
            c.create_arc(*box, start=225, extent=-270, style="arc", outline=bar_colour(0.5), width=11)
            for yy, width in ((top + ring + 8, 70), (top + ring + 30, 46), (top + ring + 50, 90)):
                rounded(self, cx - width / 2, yy, cx + width / 2, yy + 10, 5, fill=bar_colour(0.3 + width / 400), outline="")
            return
        colour, _word = self.level(self.percent)
        if render.HAVE:  # an anti-aliased ring with round ends
            self._ring = render.ring_photo(ring, self.percent, colour, GRID)
            c.create_image(cx - ring / 2, top, image=self._ring, anchor="nw")
        else:
            c.create_arc(*box, start=225, extent=-270, style="arc", outline=GRID, width=11)
            sweep = 270 * min(max(self.percent, 0), 100) / 100
            if sweep > 0.5:
                c.create_arc(*box, start=225, extent=-sweep, style="arc", outline=colour, width=11)
        c.create_text(cx, top + ring / 2, text="-" if self.percent is None else f"{self.percent:.0f}%", fill=TEXT,
                      font=f.heading)
        y = top + ring + 4
        c.create_text(cx, y, text=self.title, anchor="n", fill=TEXT, font=f.bold)
        y += f.bold.metrics("linespace") + 1
        c.create_text(cx, y, text=self.state_text, anchor="n", fill=text_colour(colour), font=f.bold)
        y += f.bold.metrics("linespace")
        c.create_text(cx, y, text=self.caption, anchor="n", fill=AXIS_TEXT, font=f.small, width=w - 20, justify="center")


class Sparkline(tk.Canvas):
    """A small filled line for one reading (0-100), the last minute or so. Used for each CPU core:
    the number beside it carries the value, the shape shows the trend."""

    POINTS = 60

    def __init__(self, parent, colour: str, width: int = 150, height: int = 36):
        super().__init__(parent, width=width, height=height, bg=CARD, highlightthickness=0, borderwidth=0)
        self.colour = colour
        self.values: Deque[Optional[float]] = deque(maxlen=self.POINTS)
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Map>", lambda _e: self.draw())

    def push(self, value: Optional[float]) -> None:
        self.values.append(value)
        self.draw()

    def draw(self) -> None:
        if not self.winfo_ismapped():  # not on screen: nothing to draw
            return
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 10:
            return
        rounded(self, 0, 0, w, h, 6, fill="#f6f8fb", outline="")
        known = [(i, v) for i, v in enumerate(self.values) if v is not None]
        if len(known) < 2:
            return
        n, step = len(self.values), (w - 8) / (self.POINTS - 1)
        pts = [(w - 4 - (n - 1 - i) * step, h - 4 - min(max(v, 0), 100) / 100 * (h - 8)) for i, v in known]
        if render.HAVE:  # an anti-aliased smooth line
            self._img = render.photo(render.spark_image(w, h, pts, self.colour))
            self.create_image(0, 0, image=self._img, anchor="nw")
            return
        flat = [c for p in pts for c in p]
        self.create_polygon(pts[0][0], h - 4, *flat, pts[-1][0], h - 4, fill=tint(self.colour, 0.16), outline="")
        self.create_line(*flat, fill=self.colour, width=2, smooth=True, joinstyle="round", capstyle="round")

