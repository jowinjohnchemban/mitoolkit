"""Live status window: gauges and graphs of the phone's SoC (processor with every core, GPU and memory, each with its
temperature), battery, temperatures and network, plus a task-manager style list of processes.

One reading a second. Read-only: nothing on the phone is changed, and closing the window stops it.
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional

from mitoolkit import adb, monitor, watchdog
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button, segmented
from mitoolkit.ui.components.charts import (BLUE, CRIT_COLOUR, GREEN, ORANGE, PURPLE, RED, WARN_COLOUR, Gauge,
                                           LineChart, Sparkline)
from mitoolkit.ui.components.scroll_page import ScrollPage
from mitoolkit.ui.components.search import SearchBox, rank
from mitoolkit.ui.components.shapes import CARD, Card
from mitoolkit.ui.components.skeleton import Skeleton
from mitoolkit.ui.theme import AMBER, GREEN as GREEN_TEXT, MUTED
from mitoolkit.ui.theme import RED as TEXT_RED

INTERVAL = 1.0
CALL_TIMEOUT = 15.0       # a reading that takes longer than this is given up on (and tried again)
WINDOWS = ((60, "1 min"), (300, "5 min"), (900, "15 min"), (1800, "30 min"), (3600, "1 hr"))
PROCESS_FILTERS = (("apps", "Apps"), ("apps+system", "Apps and system"), ("all", "Everything"))
COLUMNS = (("name", "Name", 300, "w"), ("pid", "PID", 70, "e"), ("cpu", "CPU %", 80, "e"),
           ("mem", "Memory", 90, "e"), ("state", "State", 70, "w"))
TABS = (("overview", "Overview"), ("processor", "SoC"), ("sensors", "Sensors"),
        ("processes", "Processes"))
STATES = {"R": "Running", "S": "Sleeping", "D": "Waiting", "Z": "Zombie", "T": "Stopped"}


def _speed(kbs: float) -> str:
    return f"{kbs / 1024:.1f} MB/s" if kbs >= 1024 else f"{kbs:.0f} KB/s"


def _percent(v: float) -> str:
    return f"{v:.0f}%"


def temperature_level(degrees: float) -> str:
    """A word as well as a colour, so the meaning never rests on colour alone."""
    return "Hot" if degrees >= 60 else "Warm" if degrees >= 45 else "Normal"


def with_temperature(text: str, degrees: Optional[float]) -> str:
    """``text`` followed by a part's temperature and what it means, like "2208 MHz · 49 °C warm"."""
    if degrees is None:
        return text
    reading = f"{degrees:.0f} °C {temperature_level(degrees).lower()}"
    return f"{text} · {reading}" if text else reading


class LiveStatusDialog(Dialog):
    title = "Live status"
    size = "1000x820"
    min_size = (700, 460)
    padding = 0

    def __init__(self, app, serial: str, name: str = "", start: bool = True):
        """start=False builds the window without the reading thread (for tests, which feed readings)."""
        self.serial, self.name = serial, name
        self.stop = threading.Event()
        self.paused = threading.Event()
        self.last: Dict[str, object] = {}
        self.core_cells: List[tuple] = []
        self.procs: List[Dict[str, object]] = []
        self.sensors: List[tuple] = []
        self._lock = threading.Lock()
        self._inbox: List[tuple] = []
        self._scheduled = False
        self.proc_total: Optional[int] = None
        self.sort_key, self.sort_desc = "cpu", True
        self._gone = False                     # the phone was unplugged (the main window noticed)
        super().__init__(app)
        self._heard = False                    # becomes True when the first reading (or error) arrives
        self._opened = time.monotonic()
        if start:
            threading.Thread(target=self._loop, daemon=True, name="live-status").start()
            self._wait_tick()
            self._watch_connection()

    def _watch_connection(self) -> None:
        """The main window notices an unplugged phone within a second; follow it at once instead of
        waiting for a reading to fail."""
        if not self.alive():
            return
        current = self.app.android
        present = bool(current) and current.get("serial") == self.serial and current.get("state") == "device"
        if not present and not self._gone and self._heard:
            self._gone = True
            self._badge("● Disconnected", TEXT_RED)
            self.headline.configure(text=f"{self.name or 'Phone'}: disconnected")
            self._set_sub("The phone was unplugged. This window continues by itself when it is back.", TEXT_RED)
        elif present and self._gone:
            self._gone = False                           # back: the next reading redraws everything
            self._badge("◌ Reconnecting", AMBER)
        self.win.after(500, self._watch_connection)

    # --------------------------------------------------------------- layout
    def build(self) -> None:
        """A fixed header (what the phone is doing, the controls and the tabs) over one page at a
        time. Lists get a whole page to themselves, so a window never holds two scrollbars."""
        f = self.fonts
        top = ttk.Frame(self.body, padding=(20, 14, 20, 8))
        top.pack(fill="x")
        head = ttk.Frame(top)
        head.pack(fill="x")
        self.headline = ttk.Label(head, text=f"{self.name or 'Phone'}: reading...", font=f.heading)
        self.headline.pack(side="left")
        Button(head, text="Copy snapshot", icon="copy", command=self._copy).pack(side="right")
        self.pause_btn = Button(head, text="Pause", icon="pause", command=self._toggle_pause)
        self.pause_btn.pack(side="right", padx=(0, 8))
        self.live = ttk.Label(head, text="● Live", foreground=GREEN_TEXT, font=f.bold)
        self.live.pack(side="right", padx=(0, 16))
        self.sub = ttk.Label(top, text="One reading a second. Nothing on the phone is changed.", foreground=MUTED)
        self.sub.pack(anchor="w", pady=(2, 10))
        # tabs on the left; on the right the time range, which only the graphs page uses
        row = ttk.Frame(top)
        row.pack(fill="x")
        self.tab_var = tk.StringVar(value=TABS[0][0])
        segmented(row, TABS, self.tab_var, self._show_tab).pack(side="left")
        self.range_box = ttk.Frame(row)
        self.window_var = tk.IntVar(value=WINDOWS[0][0])
        segmented(self.range_box, WINDOWS, self.window_var, self._window_changed).pack(side="right")
        ttk.Label(self.range_box, text="Time range").pack(side="right", padx=(0, 10))
        ttk.Separator(self.body, orient="horizontal").pack(fill="x")

        self.stage = ttk.Frame(self.body)
        self.stage.pack(fill="both", expand=True)
        self.pages: Dict[str, tk.Misc] = {}
        self.scrolls: Dict[str, ScrollPage] = {}
        self._build_overview(f)
        self._build_processor()
        self._build_sensors()
        self._build_processes()
        self._show_tab()
        for number, (key, _label) in enumerate(TABS, 1):  # Ctrl+1 ... Ctrl+4 switch tabs
            self.win.bind(f"<Control-Key-{number}>", lambda _e, k=key: (self.tab_var.set(k), self._show_tab()))
        self.win.bind("<MouseWheel>", self._wheel)

    def _scrolling_page(self, name: str) -> tk.Misc:
        """A page that scrolls as a whole (for pages made of graphs and panels, not lists)."""
        page = ScrollPage(self.stage, self.app.bg, lambda _w: None)
        page.MAX_WIDTH = 10_000  # use the whole window, so the cards line up with the header
        self.pages[name] = page
        self.scrolls[name] = page
        return page.content

    def _plain_page(self, name: str) -> ttk.Frame:
        """A page that fills the window; its one list scrolls itself."""
        page = ttk.Frame(self.stage, padding=(20, 14, 20, 14))
        self.pages[name] = page
        return page

    def _show_tab(self) -> None:
        current = self.tab_var.get()
        for name, page in self.pages.items():
            page.pack_forget()
        self.pages[current].pack(fill="both", expand=True)
        if current == "overview":
            self.range_box.pack(side="right")
        else:
            self.range_box.pack_forget()
        if current == "sensors" and self.sensors:
            self._show_sensors(self.sensors)
        elif current == "processes" and self.procs:
            self._fill_procs()
        if current in self.scrolls:
            self.scrolls[current].to_top()

    def _build_overview(self, f) -> None:
        page = self._scrolling_page("overview")
        gauges = ttk.Frame(page)
        gauges.pack(fill="x", pady=(0, 6))
        for col in range(5):
            gauges.columnconfigure(col, weight=1, uniform="gauges")
        self.g_cpu = Gauge(gauges, "Processor", f, (70, 90))
        self.g_gpu = Gauge(gauges, "Graphics (GPU)", f, (70, 90))
        self.g_mem = Gauge(gauges, "Memory", f, (75, 90))
        self.g_bat = Gauge(gauges, "Battery", f, (40, 20), invert=True)
        self.g_disk = Gauge(gauges, "Storage", f, (80, 92))
        self._gauge_order = [self.g_cpu, self.g_mem, self.g_bat, self.g_disk]
        self._place_gauges()

        grid = ttk.Frame(page)
        grid.pack(fill="x")
        for col in (0, 1):
            grid.columnconfigure(col, weight=1, uniform="charts")
        kw = {"interval": INTERVAL, "window": WINDOWS[0][0]}
        self.cpu = LineChart(grid, "Processor use", [("", BLUE)], f, ymax=100, fmt=_percent,
                             thresholds=[(80, WARN_COLOUR, "High")], **kw)
        self.gpu = LineChart(grid, "Graphics (GPU) load", [("", RED)], f, ymax=100, fmt=_percent,
                             thresholds=[(80, WARN_COLOUR, "High")], **kw)
        self.mem = LineChart(grid, "Memory in use", [("", GREEN)], f, ymax=100, fmt=_percent,
                             thresholds=[(85, WARN_COLOUR, "High")], **kw)
        self.bat = LineChart(grid, "Battery charge", [("", ORANGE)], f, ymax=100, fmt=_percent,
                             thresholds=[(20, CRIT_COLOUR, "Low")], **kw)
        self.power = LineChart(grid, "Battery power", [("", PURPLE)], f, fmt=lambda v: f"{v:.0f} mA", min_top=200, **kw)
        self.temp = LineChart(grid, "Temperature", [("Battery", ORANGE), ("Hottest sensor", PURPLE)], f,
                              ymin=20, min_top=30, fmt=lambda v: f"{v:.0f}\u00b0C",
                              thresholds=[(45, WARN_COLOUR, "Warm"), (60, CRIT_COLOUR, "Hot")], **kw)
        self.net = LineChart(grid, "Network traffic", [("Down", BLUE), ("Up", GREEN)], f, fmt=_speed, min_top=20, **kw)
        self.charts = (self.cpu, self.gpu, self.mem, self.bat, self.power, self.temp, self.net)
        self._chart_order = [self.cpu, self.mem, self.bat, self.power, self.temp, self.net]
        self._place_charts()
        self.facts = ttk.Label(page, text="", foreground=MUTED, justify="left")
        self.facts.pack(anchor="w", pady=(2, 0))

    def _build_processor(self) -> None:
        """The SoC (system on a chip) page: the processor, the graphics chip and the memory with their load, speed and
        temperature, then every processor core."""
        page = self._scrolling_page("processor")
        ttk.Label(page, text="The chip that runs the phone (SoC): its processor, graphics (GPU) and memory (RAM), "
                             "each with its load, speed and temperature.", foreground=MUTED).pack(anchor="w", pady=(0, 10))
        parts = ttk.Frame(page)
        parts.pack(fill="x", pady=(0, 6))
        for col in range(3):
            parts.columnconfigure(col, weight=1, uniform="soc")
        f = self.fonts
        self.s_cpu = Gauge(parts, "Processor", f, (70, 90))
        self.s_gpu = Gauge(parts, "Graphics (GPU)", f, (70, 90))
        self.s_ram = Gauge(parts, "Memory (RAM)", f, (75, 90))
        for col, gauge in enumerate((self.s_cpu, self.s_gpu, self.s_ram)):
            gauge.grid(row=0, column=col, sticky="ew", padx=6, pady=(0, 4))
        self.soc_note = ttk.Label(page, text="A part's temperature is the highest reading among its sensors. Every "
                                             "sensor is listed on the Sensors tab.", foreground=MUTED)
        self.soc_note.pack(anchor="w", pady=(0, 14))
        ttk.Label(page, text="Cores", font=self.fonts.bold).pack(anchor="w")
        ttk.Label(page, text="Each core with its own trend (the last minute), its usage and its speed.",
                  foreground=MUTED).pack(anchor="w", pady=(0, 10))
        self.cores = ttk.Frame(page)
        self.cores.pack(fill="x")
        for col in (0, 1):
            self.cores.columnconfigure(col, weight=1, uniform="cores")
        self.cores_skel = Skeleton(self.cores, rows=4, widths=(0.45, 0.45), bar=34, gap=14, label="Reading the cores")
        self.cores_skel.grid(row=0, column=0, columnspan=2, sticky="ew")

    def _build_sensors(self) -> None:
        page = self._plain_page("sensors")
        ttk.Label(page, text="Every temperature sensor the phone lets us read, hottest first.",
                  foreground=MUTED).pack(anchor="w", pady=(0, 8))
        self.sensor_note = ttk.Label(page, text="Waiting for readings...", foreground=MUTED)
        self.sensor_note.pack(side="bottom", anchor="w", pady=(6, 0))
        self.sensor_skel = Skeleton(page, rows=7, widths=(0.55, 0.4, 0.5, 0.35, 0.48, 0.42, 0.52), label="Reading sensors")
        self.sensor_skel.pack(fill="x")
        self.sensor_tree = self._tree(page, (("name", "Sensor", 360, "w"), ("temp", "Temperature", 120, "e"),
                                             ("level", "Level", 100, "w")))
        self.sensor_tree.master.pack_forget()
        self.sensor_tree.tag_configure("Hot", foreground=TEXT_RED)
        self.sensor_tree.tag_configure("Warm", foreground=AMBER)

    def _build_processes(self) -> None:
        page = self._plain_page("processes")
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 8))
        self.filter_var = tk.StringVar(value="apps")
        segmented(bar, PROCESS_FILTERS, self.filter_var, self._fill_procs).pack(side="left")
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self._fill_procs())
        SearchBox(bar, self.query, "Search processes", width=300,
                  suggest=lambda text: rank(text, ((str(p["name"]), f"PID {p['pid']}") for p in self.procs))
                  ).pack(side="right")
        self.proc_note = ttk.Label(page, text="Waiting for the process list...", foreground=MUTED)
        self.proc_note.pack(side="bottom", anchor="w", pady=(6, 0))
        self.proc_skel = Skeleton(page, rows=9, widths=(0.6, 0.45, 0.7, 0.5, 0.55, 0.4, 0.65, 0.48, 0.58),
                                  label="Reading processes")
        self.proc_skel.pack(fill="x")
        self.proc_tree = self._tree(page, COLUMNS, sortable=True)
        self.proc_tree.master.pack_forget()

    def _tree(self, parent, columns, sortable: bool = False) -> ttk.Treeview:
        """A list that fills its page and has the only scrollbar there."""
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=6,
                            selectmode="browse")
        sbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sbar.set)
        for key, label, width, anchor in columns:
            tree.heading(key, text=label, anchor=anchor,
                         command=(lambda k=key: self._sort_by(k)) if sortable else "")
            tree.column(key, width=width, anchor=anchor, stretch=(key == columns[0][0]))
        sbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def _place_gauges(self) -> None:
        for gauge in (self.g_cpu, self.g_gpu, self.g_mem, self.g_bat, self.g_disk):
            gauge.grid_forget()
        for col, gauge in enumerate(self._gauge_order):
            gauge.grid(row=0, column=col, sticky="ew", padx=6, pady=(0, 4))

    def _place_charts(self) -> None:
        for chart in self.charts:
            chart.grid_forget()
        for i, chart in enumerate(self._chart_order):
            chart.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 14) if i % 2 == 0 else 0, pady=(0, 14))

    def _wheel(self, event) -> None:
        """The wheel scrolls what is under it: a list scrolls itself (and the page stays put); on a
        page of graphs it scrolls that page."""
        if isinstance(event.widget, ttk.Treeview):
            return
        page = self.scrolls.get(self.tab_var.get())
        if page is not None:
            page.scroll(-3 if event.delta > 0 else 3)

    # -------------------------------------------------------------- sampling
    def _loop(self) -> None:
        """The reading thread: one reading a second, handed to the window through a small queue. After
        a failure it waits longer (up to 2 s) instead of hammering a phone that isn't answering."""
        mon: Optional[monitor.Monitor] = None
        failures = 0
        while not self.stop.is_set():
            started = time.monotonic()
            wait = INTERVAL
            if not self.paused.is_set():
                try:
                    if mon is None:  # connecting is guarded too: a stuck USB open must not hang this
                        mon = monitor.Monitor(watchdog.call_with_timeout(
                            lambda: adb.Phone(self.serial), CALL_TIMEOUT, "the phone"))
                    current = mon
                    self._deliver(watchdog.call_with_timeout(current.sample, CALL_TIMEOUT, "the phone"), None)
                    failures = 0
                except Exception as err:  # the phone was unplugged, adb is busy, or it stopped answering
                    mon = None
                    failures += 1
                    wait = min(2.0, INTERVAL * 2 ** min(failures, 3))      # comes back quickly when replugged
                    self._deliver(None, str(err))
            self.stop.wait(max(0.25, wait - (time.monotonic() - started)))

    def _deliver(self, sample: Optional[Dict[str, object]], error: Optional[str]) -> None:
        """Called on the reading thread. Readings wait in a list; the window takes them all in one go,
        so if it is busy (or hidden) readings never pile up as separate tasks."""
        with self._lock:
            self._inbox.append((sample, error))
            if len(self._inbox) > 120:          # the window stalled for two minutes: keep the newest
                del self._inbox[:-120]
            schedule = not self._scheduled
            self._scheduled = True
        if schedule:
            self.app.call_soon(self._drain)

    def _drain(self) -> None:
        with self._lock:
            items, self._inbox = self._inbox, []
            self._scheduled = False
        for i, (sample, error) in enumerate(items):
            try:
                self._update(sample, error, last=i == len(items) - 1)
            except Exception as err:  # never let one odd reading break the window
                self.app.log(f"Live status: could not show a reading ({err})")

    def _wait_tick(self) -> None:
        """Until the first reading arrives, say plainly that we are working, and for how long, so a
        slow phone never looks like a frozen window. The grey shapes shimmer meanwhile."""
        if not self.alive() or self._heard:
            return
        self._badge("◌ Connecting", AMBER)
        if time.monotonic() - self._opened >= 8:      # a normal start says nothing more; only a slow one explains
            self._set_sub("Still waiting for the phone. Unlock its screen, check the cable, and allow USB "
                          "debugging if it asks. The window is fine: it keeps trying.", MUTED)
        self.win.after(1000, self._wait_tick)

    def _badge(self, text: str, colour: str) -> None:
        """The Live / Paused mark in the top bar; set only when it changes, so refreshes cause no redraw."""
        if self.live.cget("text") != text:
            self.live.configure(text=text, foreground=colour)

    def _set_sub(self, text: str, colour: str) -> None:
        if self.sub.cget("text") != text:
            self.sub.configure(text=text, foreground=colour)

    def _update(self, sample: Optional[Dict[str, object]], error: Optional[str], last: bool = True) -> None:
        """Show one reading. When several arrive together every one goes into the graphs, but the
        gauges, lists and labels are redrawn only for the newest."""
        if not self.alive():
            return
        self._heard = True
        if sample is None:
            if self._gone:
                return                                   # already said "disconnected"; no error text over it
            self._badge("● No answer", TEXT_RED)
            self.headline.configure(text=f"{self.name or 'Phone'}: not answering")
            self._set_sub((error or "")[:160] or "Check the cable and that USB debugging is allowed.", TEXT_RED)
            return
        self.last = sample
        g = sample.get
        ma, hot = g("current_ma"), g("hottest")
        self.cpu.push(g("cpu"), redraw=last)
        self.mem.push(g("mem_pct"), redraw=last)
        self.bat.push(g("battery_level"), redraw=last)
        self.power.push(None if ma is None else abs(ma), redraw=last)
        self.temp.push(g("battery_temp_c"), hot[1] if hot else None, redraw=last)
        self.net.push(g("net_down_kbs"), g("net_up_kbs"), redraw=last)
        if g("gpu_pct") is not None:
            self.gpu.push(g("gpu_pct"), redraw=last)
        if not last:
            return
        self._badge("● Live", GREEN_TEXT)
        cpu_speed = f"{max(g('cores_mhz') or [0])} MHz top core" if g("cores_mhz") else ""
        mem_text = f"{g('mem_used_gb')} of {g('mem_total_gb')} GB" if g("mem_total_gb") else ""
        gpu_speed = f"{g('gpu_mhz')} MHz" if g("gpu_mhz") else ""
        self.g_cpu.set(g("cpu"), cpu_speed)
        self.g_mem.set(g("mem_pct"), mem_text)
        # the SoC page: each part with its load, speed and temperature (the load is blank when the phone does not say)
        self.s_cpu.set(g("cpu"), with_temperature(cpu_speed, g("cpu_temp")))
        if g("gpu_pct") is not None:
            self.s_gpu.set(g("gpu_pct"), with_temperature(gpu_speed, g("gpu_temp")))
        else:                                              # many phones give the GPU's temperature but not its load
            self.s_gpu.set_unavailable("No load reading", with_temperature("", g("gpu_temp")))
        self.s_ram.set(g("mem_pct"), with_temperature(mem_text, g("ram_temp")))
        self.g_bat.set(g("battery_level"), (g("battery_status") or "").lower())
        if g("gpu_pct") is not None:
            if self.g_gpu not in self._gauge_order:  # this phone reports GPU load: add its gauge and graph
                self._gauge_order.insert(1, self.g_gpu)
                self._place_gauges()
                self._chart_order.insert(1, self.gpu)
                self._place_charts()
            self.g_gpu.set(g("gpu_pct"), f"{g('gpu_mhz')} MHz" if g("gpu_mhz") else "")
        if g("storage_total_gb"):
            used, total = g("storage_used_gb"), g("storage_total_gb")
            self.g_disk.set(100 * used / total, f"{used} of {total} GB used")
        if g("core_pct") or g("cores_mhz"):
            self._show_cores(g("core_pct") or [], g("cores_mhz") or [], g("cores_max_mhz") or [])
        # the lists are rebuilt only while their tab is open; opening a tab shows the latest data
        if g("thermal"):
            self.sensors = g("thermal")
            if self.tab_var.get() == "sensors":
                self._show_sensors(self.sensors)
        if "procs" in sample:
            self.procs = sample["procs"]
            self.proc_total = g("proc_total")
            if self.tab_var.get() == "processes":
                self._fill_procs()

        status, level = g("battery_status") or "", g("battery_level")
        self.headline.configure(
            text=f"{self.name or 'Phone'}: " + (f"battery {level}%" if level is not None else "running")
            + (f", {status.lower()}" if status else ""))
        self._set_sub("One reading a second; nothing on the phone is changed. Point at a graph to read "
                      "exact values.", MUTED)
        facts: List[str] = []
        if g("mem_used_gb") is not None:
            facts.append(f"Memory: {g('mem_used_gb')} of {g('mem_total_gb')} GB in use"
                         + (f", {g('swap_used_mb')} MB of swap" if g("swap_used_mb") else ""))
        if g("battery_voltage_mv"):
            facts.append(f"Battery: {g('battery_voltage_mv') / 1000:.2f} V"
                         + (f", {g('battery_technology')}" if g("battery_technology") else ""))
        if g("gpu_mhz"):
            facts.append(f"GPU speed: {g('gpu_mhz')} MHz" + (f" of {g('gpu_max_mhz')} MHz" if g("gpu_max_mhz") else ""))
        self.facts.configure(text="\n".join(facts))

    # ----------------------------------------------------------------- cores
    @staticmethod
    def _core_kind(limits: List[int], i: int) -> str:
        """Performance cores top out higher than efficiency cores."""
        if not limits or i >= len(limits) or len(set(limits)) < 2:
            return ""
        return "Performance" if limits[i] == max(limits) else "Efficiency"

    def _reveal(self, skeleton: Skeleton, tree: ttk.Treeview) -> None:
        """First data arrived: swap the skeleton for the real list."""
        if skeleton.loading:
            skeleton.stop()
            skeleton.pack_forget()
            tree.master.pack(fill="both", expand=True)

    def _show_cores(self, usage: List[float], speeds: List[int], limits: List[int]) -> None:
        if self.cores_skel.loading:
            self.cores_skel.stop()
            self.cores_skel.grid_forget()
        count = max(len(usage), len(speeds))
        if len(self.core_cells) != count:
            for child in self.cores.winfo_children():
                child.destroy()
            self.core_cells = []
            for i in range(count):
                card = Card(self.cores)
                card.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 10) if i % 2 == 0 else 0, pady=(0, 4))
                cell = card.body
                cell.columnconfigure(1, weight=1)
                kind = self._core_kind(limits, i)
                tk.Label(cell, text=f"Core {i}" + (f"\n{kind}" if kind else ""), fg=MUTED, bg=CARD, width=11,
                         anchor="w", justify="left", font=self.fonts.base).grid(row=0, column=0, sticky="w")
                spark = Sparkline(cell, BLUE if kind != "Efficiency" else GREEN, height=40)
                spark.grid(row=0, column=1, sticky="ew", padx=(0, 10))
                value = tk.Label(cell, text="", width=14, anchor="e", justify="right", bg=CARD, fg="#1b1b1b",
                                 font=self.fonts.base)
                value.grid(row=0, column=2, sticky="e")
                self.core_cells.append((spark, value))
        for i, (spark, value) in enumerate(self.core_cells):
            pct = usage[i] if i < len(usage) else None
            mhz = speeds[i] if i < len(speeds) else None
            spark.push(pct)
            value.configure(text="\n".join(x for x in (f"{pct:.0f}%" if pct is not None else "",
                                                       f"{mhz} MHz" if mhz else "") if x))

    # --------------------------------------------------------------- sensors
    def _show_sensors(self, sensors) -> None:
        self._reveal(self.sensor_skel, self.sensor_tree)
        self._fill(self.sensor_tree, [(name, (name, f"{deg:.1f} °C", temperature_level(deg)),
                                       (temperature_level(deg),) if deg >= 45 else ()) for name, deg in sensors])
        self.sensor_note.configure(text=f"{len(sensors)} sensors, hottest first. Normal is under 45 °C, "
                                        "warm 45 to 60, hot 60 and above.")

    @staticmethod
    def _fill(tree: ttk.Treeview, rows) -> None:
        """Update a list in place: change rows that exist, add new ones, drop old ones, keep the order."""
        wanted = {iid for iid, _v, _t in rows}
        for iid in tree.get_children():
            if iid not in wanted:
                tree.delete(iid)
        for index, (iid, values, tags) in enumerate(rows):
            if tree.exists(iid):
                tree.item(iid, values=values, tags=tags)
            else:
                tree.insert("", index, iid=iid, values=values, tags=tags)
            tree.move(iid, "", index)

    # -------------------------------------------------------------- processes
    def _sort_by(self, key: str) -> None:
        self.sort_desc = not self.sort_desc if key == self.sort_key else key not in ("name", "state")
        self.sort_key = key
        self._fill_procs()

    def _fill_procs(self) -> None:
        if self.procs:
            self._reveal(self.proc_skel, self.proc_tree)
        kinds = {"apps": {"app"}, "apps+system": {"app", "system"},
                 "all": {"app", "system", "kernel"}}[self.filter_var.get()]
        needle = self.query.get().strip().lower()
        rows = [p for p in self.procs if p["kind"] in kinds and (not needle or needle in str(p["name"]).lower())]
        keys = {"name": lambda p: str(p["name"]).lower(), "pid": lambda p: p["pid"], "cpu": lambda p: p["cpu"],
                "mem": lambda p: p["mem_mb"] or 0, "state": lambda p: str(p["state"])}
        rows.sort(key=keys[self.sort_key], reverse=self.sort_desc)
        for key, label, _w, _a in COLUMNS:  # an arrow on the column being sorted
            arrow = (" ▼" if self.sort_desc else " ▲") if key == self.sort_key else ""
            self.proc_tree.heading(key, text=label + arrow)
        self._fill(self.proc_tree, [
            (str(p["pid"]), (p["name"], p["pid"], f"{p['cpu']:.1f}",
                             f"{p['mem_mb']:.0f} MB" if p["mem_mb"] else "", STATES.get(str(p["state"]), p["state"])), ())
            for p in rows])
        self.proc_note.configure(text=f"{len(rows)} shown" + (f" of {self.proc_total} running" if self.proc_total else "")
                                 + ". Click a heading to sort. Reading only: nothing can be stopped from here.")

    # --------------------------------------------------------------- actions
    def _window_changed(self) -> None:
        for chart in self.charts:
            chart.set_window(self.window_var.get())

    def _toggle_pause(self) -> None:
        if self.paused.is_set():
            self.paused.clear()
            self.pause_btn.configure(text="Pause", icon="pause")
            self._badge("● Live", GREEN_TEXT)
        else:
            self.paused.set()
            self.pause_btn.configure(text="Resume", icon="play")
            self._badge("❚❚ Paused", MUTED)

    def _copy(self) -> None:
        if not self.last:
            return
        skip = ("time", "cores_mhz", "cores_max_mhz", "core_pct", "top", "procs", "thermal")
        lines = [f"{k}: {v}" for k, v in self.last.items() if k not in skip]
        lines += [f"core {i}: {v}%" for i, v in enumerate(self.last.get("core_pct", []))]
        lines += [f"sensor {n}: {d} C" for n, d in self.last.get("thermal", [])]
        lines += [f"busy app: {n} {c:.0f}%" for n, c in self.last.get("top", [])]
        self.win.clipboard_clear()
        self.win.clipboard_append("\n".join(lines))
        self.app.log("Live status copied.")

    def close(self) -> None:
        """Stop reading, drop what was collected, and close. The charts free their own images when
        their widgets are destroyed; the window then collects garbage (see Dialog.close)."""
        self.stop.set()
        with self._lock:
            self._inbox.clear()
        self.last, self.procs, self.sensors = {}, [], []
        super().close()
