"""Log viewer: the phone's recent system log (logcat), for finding out why something misbehaves.

Read-only. It dumps the log once (Refresh reads it again), colours errors and warnings, filters by
level and by a search word, and can copy or save what is shown. Nothing on the phone is changed.
Logs can hold personal information (names of apps, sometimes account or location hints), so saving
and copying are always your choice and nothing is sent anywhere.
"""
from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import List, Optional, Tuple

from mitoolkit import adb
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button, segmented
from mitoolkit.ui.components.search import SearchBox, rank
from mitoolkit.ui.components.skeleton import Skeleton
from mitoolkit.ui.theme import AMBER, MUTED, RED

LEVELS = (("V", "All"), ("I", "Info and up"), ("W", "Warnings and up"), ("E", "Errors only"))
ORDER = "VDIWEF"
LINE = re.compile(r"^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+(.*?)\s*:\s?(.*)$")


def parse_log(text: str) -> List[Tuple[str, str, str, str]]:
    """Lines of `logcat -v threadtime` as (time, level, tag, message). Lines that don't match (such
    as the "--- beginning of main" headers) are kept as level "V" with the whole line as the message."""
    rows: List[Tuple[str, str, str, str]] = []
    for line in text.splitlines():
        m = LINE.match(line)
        rows.append((m.group(1), m.group(4), m.group(5), m.group(6)) if m else ("", "V", "", line.strip()))
    return rows


def keep(row: Tuple[str, str, str, str], level: str, needle: str) -> bool:
    """Whether a row passes the level filter and the search word."""
    _time, lvl, tag, message = row
    if ORDER.index(lvl) < ORDER.index(level) and tag:
        return False
    return not needle or needle in (tag + " " + message).lower()


class LogDialog(Dialog):
    title = "Log Viewer"
    size = "980x680"
    min_size = (640, 420)

    def __init__(self, app, serial: str, name: str = ""):
        self.serial, self.name = serial, name
        self.rows: List[Tuple[str, str, str, str]] = []
        self._loading: Optional[Skeleton] = None
        super().__init__(app)
        self.reload()

    def build(self) -> None:
        body = self.body
        head = ttk.Frame(body)
        head.pack(fill="x")
        ttk.Label(head, text=f"{self.name or 'Phone'}: system log", font=self.fonts.heading).pack(side="left")
        Button(head, text="Copy", icon="copy", command=self.copy).pack(side="right")
        Button(head, text="Save", icon="save", command=self.save).pack(side="right", padx=(0, 8))
        self.refresh_btn = Button(head, text="Refresh", icon="refresh", command=self.reload)
        self.refresh_btn.pack(side="right", padx=(0, 8))
        ttk.Label(body, text="The phone's recent log, newest last. Reading only. Logs can contain personal "
                             "details: check them before sharing.", foreground=MUTED).pack(anchor="w", pady=(2, 8))

        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(0, 8))
        self.level = tk.StringVar(value="V")
        segmented(bar, LEVELS, self.level, self.show).pack(side="left")
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self.show())
        SearchBox(bar, self.query, "Search the log (tag or text)", width=320,
                  suggest=lambda text: rank(text, ((tag, "tag") for tag in self._tags()))).pack(side="right")

        self.note = ttk.Label(body, text="", foreground=MUTED)
        self.note.pack(side="bottom", anchor="w", pady=(6, 0))
        self.stage = ttk.Frame(body)
        self.stage.pack(fill="both", expand=True)
        sbar = ttk.Scrollbar(self.stage)
        sbar.pack(side="right", fill="y")
        self.text = tk.Text(self.stage, wrap="none", font="TkFixedFont", borderwidth=1, relief="solid", padx=8,
                            pady=6, yscrollcommand=sbar.set, state="disabled", cursor="arrow")
        xbar = ttk.Scrollbar(self.stage, orient="horizontal", command=self.text.xview)
        self.text.configure(xscrollcommand=xbar.set)
        sbar.configure(command=self.text.yview)
        xbar.pack(side="bottom", fill="x")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("E", foreground=RED)
        self.text.tag_configure("F", foreground=RED, font=("TkFixedFont", 9, "bold"))
        self.text.tag_configure("W", foreground=AMBER)
        self.text.tag_configure("D", foreground=MUTED)
        self.text.tag_configure("V", foreground=MUTED)
        self.text.tag_configure("tag", font=("TkFixedFont", 9, "bold"))

    # ----------------------------------------------------------------- data
    def reload(self) -> None:
        if self._loading is not None:
            return
        self.refresh_btn.configure(state="disabled")
        self._loading = Skeleton(self.stage, rows=12, widths=(0.9, 0.7, 0.8, 0.55, 0.85, 0.6), bar=12, gap=10,
                                 label="Reading the log")
        self.text.pack_forget()
        self._loading.pack(fill="x", pady=(4, 0))
        self.note.configure(text="Reading the log from the phone")

        def work():
            return adb.logcat(self.serial, 3000)

        def done(status, result):
            if not self.alive():
                return
            if self._loading is not None:
                self._loading.stop()
                self._loading.destroy()
                self._loading = None
            self.text.pack(side="left", fill="both", expand=True)
            self.refresh_btn.configure(state="normal")
            if status == "error":
                self.rows = []
                self.note.configure(text=f"Could not read the log: {result}", foreground=RED)
                self.show()
                return
            self.rows = parse_log(str(result))
            self.show()

        self.app.run(work, done, "Reading the phone's log")

    def _tags(self) -> List[str]:
        """The tags in the log, most frequent first (what is most likely worth searching for)."""
        counts: dict = {}
        for _time, _lvl, tag, _msg in self.rows:
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
        return sorted(counts, key=lambda t: -counts[t])

    def show(self) -> None:
        level, needle = self.level.get(), self.query.get().strip().lower()
        shown = [r for r in self.rows if keep(r, level, needle)]
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for time_, lvl, tag, message in shown[-4000:]:
            if tag:
                self.text.insert("end", f"{time_}  {lvl}  ", lvl)
                self.text.insert("end", f"{tag}: ", ("tag", lvl))
                self.text.insert("end", message + "\n", lvl)
            else:
                self.text.insert("end", message + "\n", "V")
        self.text.configure(state="disabled")
        self.text.see("end")
        self.note.configure(text=f"{len(shown)} of {len(self.rows)} lines shown.", foreground=MUTED)

    # -------------------------------------------------------------- actions
    def _shown_text(self) -> str:
        return self.text.get("1.0", "end").rstrip("\n")

    def copy(self) -> None:
        self.win.clipboard_clear()
        self.win.clipboard_append(self._shown_text())
        self.note.configure(text="Copied what is shown.", foreground=MUTED)

    def save(self) -> None:
        path = filedialog.asksaveasfilename(parent=self.win, defaultextension=".txt", initialfile="phone-log.txt",
                                            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if path:
            Path(path).write_text(self._shown_text() + "\n", encoding="utf-8")
            self.note.configure(text=f"Saved to {path}", foreground=MUTED)
