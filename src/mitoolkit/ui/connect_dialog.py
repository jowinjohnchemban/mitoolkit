"""Connections window: Wi-Fi, mobile network (modem), SIM, Bluetooth, USB and power, and what the
phone is connected to, for finding out why Wi-Fi, mobile data or calls misbehave.

Read-only. A Summary tab says in plain words what looks wrong and what to try; the other tabs list
every detail. It can refresh by itself every 5 seconds and graphs the Wi-Fi and mobile signal while it
does. The Network test button is the one action that sends traffic (a few small pings), and only when
pressed.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional

from mitoolkit import adb, diagnostics, watchdog
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button, segmented
from mitoolkit.ui.components.charts import BLUE, GREEN, LineChart
from mitoolkit.ui.components.scroll_page import ScrollPage
from mitoolkit.ui.components.shapes import CARD, Card
from mitoolkit.ui.components.skeleton import Skeleton
from mitoolkit.ui.theme import AMBER, MUTED, RED
from mitoolkit.ui.theme import GREEN as GREEN_TEXT

REFRESH_S = 5
TIMEOUT_S = 30
TABS = (("summary", "Summary"), ("wifi", "Wi-Fi"), ("mobile", "Mobile network"), ("other", "Bluetooth, USB, power"))
PAGES = {"wifi": ("Wi-Fi", "Wi-Fi networks nearby"), "mobile": ("Mobile network", "SIM card"),
         "other": ("Bluetooth", "Power and USB", "Networks Android is using")}
MARKS = {diagnostics.OK: ("✔", GREEN_TEXT, "OK"), diagnostics.WARN: ("⚠", AMBER, "Check"),
         diagnostics.BAD: ("✖", RED, "Problem")}


class ConnectionsDialog(Dialog):
    title = "Connections and signal"
    size = "960x740"
    min_size = (680, 460)
    padding = 0

    def __init__(self, app, serial: str, name: str = "", start: bool = True):
        self.serial, self.name = serial, name
        self.report: Optional[Dict[str, object]] = None
        self.test_rows: List[tuple] = []
        self._busy = False
        self._testing = False
        self._present = True                   # the main window still sees this phone
        self._shown_key: Optional[str] = None
        super().__init__(app)
        if start:
            self.refresh()
            self._auto_tick()
            self._watch_connection()

    # ---------------------------------------------------------------- layout
    def build(self) -> None:
        f = self.fonts
        top = ttk.Frame(self.body, padding=(20, 14, 20, 8))
        top.pack(fill="x")
        head = ttk.Frame(top)
        head.pack(fill="x")
        ttk.Label(head, text=f"{self.name or 'Phone'}: connections and signal", font=f.heading).pack(side="left")
        Button(head, text="Copy", icon="copy", command=self.copy).pack(side="right")
        self.test_btn = Button(head, text="Network test", icon="wifi", command=self.run_test)
        self.test_btn.pack(side="right", padx=(0, 8))
        self.refresh_btn = Button(head, text="Refresh", icon="refresh", command=self.refresh)
        self.refresh_btn.pack(side="right", padx=(0, 8))
        self.sub = ttk.Label(top, text="Reading the phone...", foreground=MUTED)
        self.sub.pack(anchor="w", pady=(2, 8))
        row = ttk.Frame(top)
        row.pack(fill="x")
        self.tab_var = tk.StringVar(value="summary")
        segmented(row, TABS, self.tab_var, self._show_tab).pack(side="left")
        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text=f"Update every {REFRESH_S} s", variable=self.auto_var,
                        command=self._auto_changed).pack(side="right")
        ttk.Separator(self.body, orient="horizontal").pack(fill="x")

        self.stage = ttk.Frame(self.body)
        self.stage.pack(fill="both", expand=True)
        self.pages: Dict[str, ScrollPage] = {}
        for key, _label in TABS:
            page = ScrollPage(self.stage, self.app.bg, lambda _w: None)
            page.MAX_WIDTH = 10_000
            self.pages[key] = page
        self.win.bind("<MouseWheel>", self._wheel)
        # the Summary page: findings, two signal graphs, the network test
        s = self.pages["summary"].content
        self.findings_box = ttk.Frame(s)
        self.findings_box.pack(fill="x")
        self.loading = Skeleton(self.findings_box, rows=4, widths=(0.5, 0.8, 0.4, 0.7), bar=14, gap=14,
                                label="Reading the phone")
        self.loading.pack(fill="x", pady=(8, 0))
        charts = ttk.Frame(s)
        charts.pack(fill="x", pady=(8, 0))
        for col in (0, 1):
            charts.columnconfigure(col, weight=1, uniform="signal")
        kw = {"interval": REFRESH_S, "window": 300, "ymin": -110, "ymax": -30}
        self.wifi_chart = LineChart(charts, "Wi-Fi signal", [("Wi-Fi", BLUE)], f, fmt=lambda v: f"{v:.0f} dBm", **kw)
        self.mobile_chart = LineChart(charts, "Mobile signal (RSRP)", [("Mobile", GREEN)], f,
                                      fmt=lambda v: f"{v:.0f} dBm", **kw)
        self.wifi_chart.grid(row=0, column=0, sticky="ew", padx=(0, 14))
        self.mobile_chart.grid(row=0, column=1, sticky="ew")
        self.test_box = ttk.Frame(s)
        self.test_box.pack(fill="x", pady=(14, 0))
        self._show_tab()

    def _show_tab(self) -> None:
        current = self.tab_var.get()
        for page in self.pages.values():
            page.pack_forget()
        self.pages[current].pack(fill="both", expand=True)
        self.pages[current].to_top()
        self._render(current)

    def _wheel(self, event) -> None:
        page = self.pages.get(self.tab_var.get())
        if page is not None:
            page.scroll(-3 if event.delta > 0 else 3)

    # ---------------------------------------------------------------- reading
    def refresh(self) -> None:
        """Read the phone on a worker thread; show the result when it arrives."""
        if self._busy or not self.alive() or not self._present:
            return
        self._busy = True
        self.refresh_btn.configure(state="disabled")
        if self.report is None:                          # automatic updates stay quiet: the bar does not flicker
            self._set_sub("Reading the phone...", MUTED)

        def work() -> None:
            try:
                phone = watchdog.call_with_timeout(lambda: adb.Phone(self.serial), TIMEOUT_S, "the phone")
                raw = watchdog.call_with_timeout(lambda: diagnostics.collect_raw(phone), TIMEOUT_S, "the phone")
                self.app.call_soon(self._arrived, diagnostics.build(raw), None)
            except Exception as err:  # unplugged, busy, or not answering: say so, keep the last report
                self.app.call_soon(self._arrived, None, str(err))

        threading.Thread(target=work, daemon=True, name="connections").start()

    def _arrived(self, report: Optional[Dict[str, object]], error: Optional[str]) -> None:
        self._busy = False
        if not self.alive():
            return
        self.refresh_btn.configure(state="normal")
        if report is None:
            self._set_sub(f"Could not read the phone: {error}", RED)
            return
        self.report = report
        self._set_sub("Reading only: nothing on the phone is changed. Contains your network and device "
                      "names: check before sharing.", MUTED)
        signals = report["signals"]
        self.wifi_chart.push(signals.get("wifi_dbm"))  # type: ignore[union-attr]
        self.mobile_chart.push(signals.get("mobile_dbm"))  # type: ignore[union-attr]
        self._render(self.tab_var.get())                 # rebuilds the page only if its content changed

    def _set_sub(self, text: str, colour: str) -> None:
        if self.sub.cget("text") != text:                # set only when it changes
            self.sub.configure(text=text, foreground=colour)
        elif str(self.sub.cget("foreground")) != str(colour):
            self.sub.configure(foreground=colour)

    def _watch_connection(self) -> None:
        """Say at once when the main window sees the phone go away; it stops reading until it is back."""
        if not self.alive():
            return
        current = self.app.android
        present = bool(current) and current.get("serial") == self.serial and current.get("state") == "device"
        if present != self._present:
            self._present = present
            if not present:
                self._set_sub("The phone was unplugged. This window updates again when it is back.", RED)
            elif not self._busy:
                self.refresh()
        self.win.after(500, self._watch_connection)

    # --------------------------------------------------------------- auto update
    def _auto_changed(self) -> None:
        if self.auto_var.get():
            self.refresh()

    def _auto_tick(self) -> None:
        if not self.alive():
            return
        if self.auto_var.get() and not self._busy:
            self.refresh()
        self.win.after(REFRESH_S * 1000, self._auto_tick)

    # ---------------------------------------------------------------- drawing
    def _render(self, tab: str) -> None:
        if self.report is None:
            return
        sections = dict(self.report["sections"])  # type: ignore[arg-type]
        key = repr((tab, self.report["findings"], [sections.get(t) for t in PAGES.get(tab, ())], self.test_rows))
        if key == self._shown_key:
            return                                        # nothing on this page changed: leave it alone
        self._shown_key = key
        if tab == "summary":
            self._render_summary()
            return
        content = self.pages[tab].content
        for child in content.winfo_children():
            child.destroy()
        for title in PAGES[tab]:
            if title in sections:
                self._section(content, title, sections[title])  # type: ignore[arg-type]
        if not content.winfo_children():
            ttk.Label(content, text="The phone did not report anything for this.", foreground=MUTED).pack(anchor="w")

    def _render_summary(self) -> None:
        if self.loading is not None:
            self.loading.stop()
            self.loading.destroy()
            self.loading = None
        for child in self.findings_box.winfo_children():
            child.destroy()
        for level, title, advice in self.report["findings"]:  # type: ignore[union-attr]
            mark, colour, word = MARKS[level]
            card = Card(self.findings_box)
            card.pack(fill="x", pady=(0, 4))
            body = card.body
            body.columnconfigure(1, weight=1)
            tk.Label(body, text=mark, fg=colour, bg=CARD, font=self.fonts.heading, width=3).grid(row=0, column=0,
                                                                                                    rowspan=2, sticky="n")
            tk.Label(body, text=f"{title}", fg=colour, bg=CARD, font=self.fonts.bold, anchor="w",
                     justify="left").grid(row=0, column=1, sticky="w")
            tk.Label(body, text=advice, fg="#1b1b1b", bg=CARD, font=self.fonts.base, anchor="w", justify="left",
                     wraplength=760).grid(row=1, column=1, sticky="w")
        for child in self.test_box.winfo_children():
            child.destroy()
        if self.test_rows:
            self._section(self.test_box, "Network test (from the phone)", self.test_rows)

    def _section(self, parent, title: str, rows) -> None:
        ttk.Label(parent, text=title, font=self.fonts.bold).pack(anchor="w", pady=(10, 4))
        card = Card(parent)
        card.pack(fill="x", pady=(0, 4))
        body = card.body
        body.columnconfigure(2, weight=1)
        for i, (label, value, level) in enumerate(rows):
            mark, colour, word = MARKS.get(level, ("", "#1b1b1b", ""))
            tk.Label(body, text=label, fg=MUTED, bg=CARD, font=self.fonts.base, anchor="w", justify="left",
                     wraplength=260).grid(row=i, column=0, sticky="nw", padx=(0, 16), pady=2)
            tk.Label(body, text=mark, fg=colour, bg=CARD, font=self.fonts.bold, width=2).grid(row=i, column=1, sticky="n")
            tk.Label(body, text=str(value), fg=colour if level else "#1b1b1b", bg=CARD, font=self.fonts.base, anchor="w",
                     justify="left", wraplength=520).grid(row=i, column=2, sticky="w", pady=2)

    # ---------------------------------------------------------------- actions
    def run_test(self) -> None:
        """Ping the router and the internet from the phone (a few small packets), then show the results."""
        if self._testing or self.report is None:
            return
        self._testing = True
        self.test_btn.configure(state="disabled", text="Testing...")
        gateway = str(self.report.get("gateway") or "")       # the Wi-Fi router (the carrier's gateway never answers)

        def work() -> None:
            try:
                phone = watchdog.call_with_timeout(lambda: adb.Phone(self.serial), TIMEOUT_S, "the phone")
                rows = watchdog.call_with_timeout(lambda: diagnostics.network_test(phone, gateway), 60, "the phone")
                self.app.call_soon(self._test_done, rows, None)
            except Exception as err:
                self.app.call_soon(self._test_done, None, str(err))

        threading.Thread(target=work, daemon=True, name="network-test").start()

    def _test_done(self, rows, error: Optional[str]) -> None:
        self._testing = False
        if not self.alive():
            return
        self.test_btn.configure(state="normal", text="Network test")
        self.test_rows = rows if rows is not None else [("Network test", f"Could not run: {error}", diagnostics.BAD)]
        self.tab_var.set("summary")
        self._shown_key = None
        self._show_tab()

    def copy(self) -> None:
        if self.report is None:
            return
        text = diagnostics.as_text(self.report)
        if self.test_rows:
            text += "\n\n[Network test]\n" + "\n".join(f"{label}: {value}" for label, value, _l in self.test_rows)
        self.win.clipboard_clear()
        self.win.clipboard_append(text)
        self.app.log("Connection details copied.")
