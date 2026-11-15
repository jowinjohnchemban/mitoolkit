"""Help > Check for updates: what is new, and one button to install it (single-file program) or open the page."""
from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from typing import Optional

from mitoolkit import build, updater
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button
from mitoolkit.ui.theme import GREEN, MUTED, RED


class UpdateDialog(Dialog):
    title = "Check for updates"
    resizable = False
    padding = 16

    def __init__(self, app, release: Optional[updater.Release] = None, start: bool = True):
        """``release`` is one the start-up check already found; None looks on GitHub now."""
        self.release = release
        self.cancel = threading.Event()
        self._busy = False
        super().__init__(app)
        if start:
            if release is not None:
                self._show(release)
            else:
                self._look()

    def build(self) -> None:
        body = self.body
        ttk.Label(body, text="mitoolkit updates", font=self.fonts.heading).pack(anchor="w")
        ttk.Label(body, text=f"You have {build.full_version()}", foreground=MUTED).pack(anchor="w")
        self.line = ttk.Label(body, text="Looking for updates...", wraplength=440, justify="left")
        self.line.pack(anchor="w", pady=(12, 0))
        self.notes = tk.Text(body, width=58, height=9, wrap="word", borderwidth=0, highlightthickness=0,
                             background=self.app.bg, font=self.fonts.small, state="disabled", takefocus=0)
        self.bar = ttk.Progressbar(body, mode="determinate", maximum=100)
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(14, 0))
        Button(row, text="Close", command=self.close).pack(side="right")
        self.action = Button(row, text="Install and restart", primary=True, command=self._action)
        self.row = row

    def _say(self, text: str, colour: str = "") -> None:
        if self.alive():
            self.line.configure(text=text, foreground=colour)

    # ---------------------------------------------------------------- looking
    def _look(self) -> None:
        def work() -> None:
            try:
                release = updater.latest()
                self.app.call_soon(self._found, release, None)
            except Exception as err:
                self.app.call_soon(self._found, None, str(err))

        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _found(self, release: Optional[updater.Release], error: Optional[str]) -> None:
        if not self.alive():
            return
        updater.mark_checked()
        if release is None:
            self._say(error or "Could not look for updates.", RED)
            return
        self.release = release
        self._show(release)

    def _show(self, release: updater.Release) -> None:
        if not updater.is_newer(release):
            self._say(f"mitoolkit is up to date ({release.tag} is the latest).", GREEN)
            return
        self._say(f"{release.tag} is available.", "")
        if release.notes:
            self.notes.configure(state="normal")
            self.notes.delete("1.0", "end")
            self.notes.insert("1.0", release.notes)
            self.notes.configure(state="disabled")
            self.notes.pack(fill="x", pady=(8, 0), before=self.row)
        if updater.can_self_update():
            self.action.configure(text="Install and restart")
        else:
            self.action.configure(text="Open the release page")
            self._say(f"{release.tag} is available. This copy is not the single-file program, so update it "
                      "the way you installed it, or download the program from the release page.", "")
        self.action.pack(side="right", padx=6)

    # ---------------------------------------------------------------- installing
    def _action(self) -> None:
        if self.release is None or self._busy:
            return
        if not updater.can_self_update():
            webbrowser.open(self.release.page)
            return
        self._busy = True
        self.action.configure(state="disabled")
        self.bar.pack(fill="x", pady=(10, 0), before=self.row)
        self._say("Downloading and checking the update...", MUTED)
        release = self.release
        exe = updater.running_program()
        part = exe.with_name(exe.name + ".new")

        def progress(done: int, total: int) -> None:
            if total:
                self.app.call_soon(self._progress, 100 * done / total)

        def work() -> None:
            try:
                updater.download(release, part, progress, self.cancel)
                self.app.call_soon(self._ready, part, None)
            except Exception as err:
                self.app.call_soon(self._ready, None, str(err))

        threading.Thread(target=work, daemon=True, name="update-download").start()

    def _progress(self, percent: float) -> None:
        if self.alive():
            self.bar.configure(value=percent)

    def _ready(self, part: Optional[Path], error: Optional[str]) -> None:
        self._busy = False
        if not self.alive():
            return
        if part is None:
            self.bar.pack_forget()
            self.action.configure(state="normal")
            self._say(error or "The update failed.", RED)
            self.app.log(f"Update failed: {error}")
            return
        try:
            program = updater.install(part)
        except updater.UpdateError as err:
            self.bar.pack_forget()
            self.action.configure(state="normal")
            self._say(str(err), RED)
            self.app.log(f"Update failed: {err}")
            return
        self.app.log(f"Updated to {self.release.tag if self.release else 'the new version'}; restarting.")
        self._say("Updated. Restarting...", GREEN)
        self.win.after(600, lambda: self._restart(program))

    def _restart(self, program: Path) -> None:
        try:
            updater.restart(program)
        except OSError as err:
            self._say(f"Updated, but could not start the new version ({err}). Open mitoolkit again.", RED)
            return
        self.app.root.after(100, self.app.root.destroy)

    def close(self) -> None:
        self.cancel.set()
        super().close()
