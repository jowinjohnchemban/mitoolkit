"""Back up files from a phone running Android (read-only for the phone)."""
from __future__ import annotations

import datetime
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from miunlock import adb
from miunlock.ui.base import Dialog
from miunlock.ui.theme import GREEN, MUTED, RED


class BackupDialog(Dialog):
    title = "Back up files from the phone"
    resizable = False
    padding = 16

    def __init__(self, app, serial: str, model: str = ""):
        self.serial, self.model = serial, model
        self.cancel = threading.Event()
        super().__init__(app)

    def build(self) -> None:
        body = self.body
        ttk.Label(body, text="Copy files from the phone to this computer", font=self.fonts.bold).pack(anchor="w")
        ttk.Label(body, foreground=MUTED, justify="left", text=(
            "Nothing on the phone is changed or deleted. Keep the screen unlocked and allow file\n"
            "access if the phone asks. App data, contacts, SMS and chats are not covered: use\n"
            "Mi Cloud, Google or each app's own backup for those (see the guide).")).pack(anchor="w", pady=(2, 10))

        self.choices = {}
        for key, (label, _folders) in adb.BACKUP_SETS.items():
            var = tk.BooleanVar(value=key in ("photos", "documents"))
            self.choices[key] = var
            ttk.Checkbutton(body, text=label, variable=var).pack(anchor="w")

        name = (self.model or "phone").replace(" ", "-")
        self.dest = tk.StringVar(value=str(Path.home() / "miunlock-backup" / f"{name}-{datetime.date.today().isoformat()}"))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(12, 0))
        ttk.Label(row, text="Save to:").pack(side="left")
        ttk.Entry(row, textvariable=self.dest, width=48).pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._browse).pack(side="left")

        self.status = ttk.Label(body, text="", foreground=MUTED, wraplength=520, justify="left")
        self.status.pack(anchor="w", pady=(10, 0))
        self.bar = ttk.Progressbar(body, mode="indeterminate")
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        self.start_btn = ttk.Button(buttons, text="Start backup", style="Primary.TButton", command=self.start)
        self.start_btn.pack(side="right", padx=6)

    def close(self) -> None:
        self.cancel.set()  # stops a running copy after the current file
        super().close()

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(parent=self.win, initialdir=str(Path.home()))
        if chosen:
            self.dest.set(chosen)

    def progress(self, text: str) -> None:
        """Called from the worker thread."""
        self.app.log(text)
        self.app.call_soon(self._show_progress, text)

    def _show_progress(self, text: str) -> None:
        if self.alive():
            self.status.configure(text=text, foreground=MUTED)

    def start(self) -> None:
        chosen = [k for k, v in self.choices.items() if v.get()]
        if not chosen:
            messagebox.showinfo("Back up", "Tick at least one thing to copy.", parent=self.win)
            return
        self.cancel.clear()
        self.start_btn.configure(state="disabled")
        self.bar.pack(fill="x", pady=(8, 0))
        self.bar.start(12)
        dest = self.dest.get().strip()
        self.app.run(lambda: adb.backup_files(self.serial, dest, chosen, self.progress, self.cancel),
                     self._done, "Backing up files from the phone...")

    @staticmethod
    def summary(result: dict) -> str:
        if result.get("cancelled"):
            return f"Cancelled. Files copied so far are in {result['dest']}"
        msg = (f"Done. {result['files']} files ({result['bytes'] / 1e6:.1f} MB) from "
               f"{len(result['copied'])} folder(s) saved to {result['dest']}")
        if result.get("failed_files"):
            msg += f". {result['failed_files']} file(s) could not be read"
        if result["skipped"]:
            msg += f"  (not found or failed: {', '.join(result['skipped'])})"
        return msg

    def _done(self, status: str, result) -> None:
        msg = f"Backup did not finish: {result}" if status == "error" else self.summary(result)
        self.app.log(msg)
        if not self.alive():
            return
        self.bar.stop()
        self.bar.pack_forget()
        self.start_btn.configure(state="normal")
        self.status.configure(text=msg, foreground=RED if status == "error" else GREEN)
