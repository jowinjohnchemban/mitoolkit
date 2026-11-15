"""Help > Check and fix problems: what is wrong with the setup, in plain words, with a Fix button where one is safe."""
from __future__ import annotations

import threading
from tkinter import ttk
from typing import List

from mitoolkit import doctor
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button
from mitoolkit.ui.theme import AMBER, GREEN, MUTED, RED

COLOUR = {doctor.OK: GREEN, doctor.INFO: MUTED, doctor.WARN: AMBER, doctor.FAIL: RED}


class DoctorDialog(Dialog):
    title = "Check and Fix Problems"
    size = "600x560"
    min_size = (480, 360)
    padding = 16

    def __init__(self, app, start: bool = True):
        self.checks: List[doctor.Check] = []
        self._busy = False
        self._note = ""
        super().__init__(app)
        if start:
            self._look()

    def build(self) -> None:
        body = self.body
        ttk.Label(body, text="Check and Fix Problems", font=self.fonts.heading).pack(anchor="w")
        self.summary = ttk.Label(body, text="Looking", foreground=MUTED, wraplength=540, justify="left")
        self.summary.pack(anchor="w", pady=(2, 10))
        self.rows = ttk.Frame(body)
        self.rows.pack(fill="both", expand=True)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        Button(buttons, text="Close", command=self.close).pack(side="right")
        self.fix_all = Button(buttons, text="Fix What Is Safe", primary=True, command=self._fix_safe)
        self.fix_all.pack(side="right", padx=6)
        Button(buttons, text="Check Again", command=self._look).pack(side="right")

    # ----------------------------------------------------------------------------------------- looking
    def _work(self, job, then) -> None:
        if self._busy:
            return
        self._busy = True
        self.fix_all.configure(state="disabled")
        outcome: list = []

        def target() -> None:
            try:
                outcome.append(job())
            except Exception as err:             # the doctor must show a problem, not become one
                outcome.append(err)
        threading.Thread(target=target, daemon=True, name="doctor").start()

        def poll() -> None:
            if not self.alive():
                return
            if not outcome:
                self.win.after(120, poll)
                return
            self._busy = False
            then(outcome[0])
        self.win.after(120, poll)

    def _look(self) -> None:
        self.summary.configure(text="Looking", foreground=MUTED)
        self._work(doctor.run, self._show)

    def _show(self, result) -> None:
        if isinstance(result, Exception):
            self.summary.configure(text=f"The check itself failed: {result}", foreground=RED)
            return
        self.checks = result
        for child in self.rows.winfo_children():
            child.destroy()
        bad = doctor.problems(result)
        for check in sorted(result, key=lambda c: c.status in (doctor.OK, doctor.INFO)):    # problems first, same order otherwise
            self._row(check)
        safe = [c for c in bad if c.fix is not None and c.safe]
        note, self._note = self._note, ""
        if not bad:
            self.summary.configure(text=("No problems found. " + note).strip(), foreground=GREEN)
        else:
            text = f"{len(bad)} thing(s) need a look." + (f" {len(safe)} can be fixed safely." if safe else "")
            self.summary.configure(text=(text + " " + note).strip(), foreground=AMBER)
        self.fix_all.configure(state="normal" if safe else "disabled")

    def _row(self, check: doctor.Check) -> None:
        row = ttk.Frame(self.rows)
        row.pack(fill="x", pady=2)
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text=doctor.MARKS[check.status], foreground=COLOUR[check.status], width=2).grid(row=0, column=0, sticky="n")
        bad = check.status in (doctor.WARN, doctor.FAIL)
        ttk.Label(row, text=check.title, font=self.fonts.bold if bad else None).grid(row=0, column=1, sticky="w")
        if check.detail:
            ttk.Label(row, text=check.detail, foreground=MUTED, wraplength=430, justify="left").grid(row=1, column=1, sticky="w")
        if check.needs_admin and bad:
            ttk.Label(row, text="Asks for administrator permission first.", foreground=MUTED,
                      font=self.fonts.small).grid(row=2, column=1, sticky="w")
        if check.fix is not None and bad:
            Button(row, text=check.fix_label or "Fix", command=lambda c=check: self._fix_one(c)).grid(
                row=0, column=2, rowspan=2, sticky="e", padx=(8, 0))

    # ------------------------------------------------------------------------------------------ fixing
    def _after_fix(self, done) -> None:
        notes = []
        for check, message in (done if isinstance(done, list) else []):
            self.app._log(message if message.startswith("Could not") else f"Fixed: {check.title}. {message}")
            notes.append(message)
        self._busy = False
        self._note = " ".join(notes)                 # shown under the heading after the list is read again
        self._look()

    def _fix_one(self, check: doctor.Check) -> None:
        if check.needs_admin:
            self.summary.configure(text="Waiting for your answer to the administrator prompt", foreground=MUTED)
        self._work(lambda: doctor.apply([check], include_decisions=True), self._after_fix)

    def _fix_safe(self) -> None:
        self._work(lambda: doctor.apply(self.checks), self._after_fix)
