"""Security check window: runs mitoolkit.security and shows what it found, worst first."""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import List

from mitoolkit import security
from mitoolkit.ui.components.buttons import Button
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.theme import AMBER, GREEN, MUTED, RED, WARN_BG, WARN_FG

STYLE = {
    security.HIGH: ("⚠", RED, "Needs attention"),
    security.MEDIUM: ("●", AMBER, "Review"),
    security.INFO: ("ℹ", MUTED, "Good to know"),
    security.OK: ("✔", GREEN, "OK"),
}


class SecurityDialog(Dialog):
    title = "Security check"
    size = "860x620"
    min_size = (640, 420)

    def __init__(self, app, serial: str):
        self.serial = serial
        self.findings: List[security.Finding] = []
        super().__init__(app)
        self.start()

    def build(self) -> None:
        body = self.body
        self.verdict = ttk.Label(body, text="Checking the phone...", font=self.fonts.title)
        self.verdict.pack(anchor="w")
        self.summary = ttk.Label(body, foreground=MUTED, justify="left", text=(
            "Compares the phone with Android's security bulletins (OSV), checks Google Play Protect and "
            "where apps came from, and looks for known stalkerware. Nothing on the phone is changed."))
        self.summary.pack(anchor="w", fill="x", pady=(2, 8))
        self.summary.bind("<Configure>", lambda e: self.summary.configure(wraplength=max(e.width - 10, 200)))
        self.bar = ttk.Progressbar(body, mode="indeterminate")
        self.bar.pack(fill="x")

        buttons = ttk.Frame(body)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        Button(buttons, text="Close", command=self.close).pack(side="right")
        self.again = Button(buttons, text="Check again", command=self.start)
        self.again.pack(side="right", padx=6)
        Button(buttons, text="Android Security Bulletins",
                   command=lambda: webbrowser.open(security.BULLETINS)).pack(side="left")
        tk.Label(body, bg=WARN_BG, fg=WARN_FG, anchor="w", justify="left", padx=8, pady=4, text=(
            "This is not an antivirus. Keep Google Play Protect on; it is the main protection on the phone."
        )).pack(side="bottom", fill="x", pady=(8, 0))

        frame = ttk.Frame(body)
        frame.pack(fill="both", expand=True, pady=(8, 0))
        sbar = ttk.Scrollbar(frame)
        sbar.pack(side="right", fill="y")
        self.text = tk.Text(frame, wrap="word", padx=12, pady=8, borderwidth=0, highlightthickness=0,
                            font=self.fonts.base, yscrollcommand=sbar.set, cursor="arrow", spacing3=4)
        self.text.pack(side="left", fill="both", expand=True)
        sbar.configure(command=self.text.yview)
        self.text.tag_configure("area", font=self.fonts.heading, spacing1=12, spacing3=6)
        self.text.tag_configure("title", font=self.fonts.bold, lmargin1=8, lmargin2=28)
        self.text.tag_configure("detail", lmargin1=28, lmargin2=28, foreground=MUTED, spacing3=8)
        self.text.tag_configure("link", lmargin1=28, foreground="#1a5fb4", underline=True)
        for level, (_icon, colour, _label) in STYLE.items():
            self.text.tag_configure(level, foreground=colour, font=self.fonts.bold)
        self.text.tag_bind("link", "<Enter>", lambda _e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("link", "<Leave>", lambda _e: self.text.configure(cursor="arrow"))
        self.text.configure(state="disabled")

    def progress(self, text: str) -> None:
        self.app.log(text)
        self.app.call_soon(self._show_progress, text)

    def _show_progress(self, text: str) -> None:
        if self.alive():
            self.summary.configure(text=text)

    def start(self) -> None:
        self.again.configure(state="disabled")
        self.bar.pack(fill="x", before=self.text.master)
        self.bar.start(12)
        self.verdict.configure(text="Checking the phone...", foreground="")
        self.app.run(lambda: security.run(self.serial, self.progress), self._done, "Running the security check...")

    def _done(self, status: str, result) -> None:
        if not self.alive():
            return
        self.bar.stop()
        self.bar.pack_forget()
        self.again.configure(state="normal")
        if status == "error":
            self.verdict.configure(text="The check did not finish", foreground=RED)
            self.summary.configure(text=str(result))
            return
        report: security.Report = result
        self.app.log(f"Security check: {report.verdict}")
        self.app.security_result(self.serial, report.verdict)   # colours the Security check button
        colour = {"Needs attention": RED, "Some things to review": AMBER}.get(report.verdict, GREEN)
        self.verdict.configure(text=report.verdict, foreground=colour)
        counts = {lv: sum(1 for f in report.findings if f.level == lv) for lv in STYLE}
        self.summary.configure(text=" · ".join(f"{counts[lv]} {STYLE[lv][2].lower()}" for lv in STYLE
                                                    if counts[lv]) + ". Nothing on the phone was changed.")
        self.show(report)

    def show(self, report: security.Report) -> None:
        order = {lv: i for i, lv in enumerate(security.LEVELS)}
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for area in ("Phone software", "Google Play", "Apps"):
            items = sorted((f for f in report.findings if f.area == area), key=lambda f: order[f.level])
            if not items:
                continue
            t.insert("end", area + "\n", "area")
            for i, f in enumerate(items):
                icon = STYLE[f.level][0]
                t.insert("end", f"{icon}  ", (f.level, "title"))
                t.insert("end", f.title + "\n", "title")
                if f.detail:
                    t.insert("end", f.detail + "\n", "detail")
                if f.link:
                    tag = f"link{area}{i}"
                    t.insert("end", "Android Security Bulletins\n", ("link", tag))
                    t.tag_bind(tag, "<Button-1>", lambda _e, url=f.link: webbrowser.open(url))
        t.configure(state="disabled")
