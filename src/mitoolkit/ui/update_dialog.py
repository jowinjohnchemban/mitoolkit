"""Help > Check for updates: what is new, and what to do about it: install it (single-file program), download the
release file (checked against its SHA-256, saved in Downloads), or open the release page."""
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
        self.saved: Optional[Path] = None              # a release file this window downloaded
        super().__init__(app)
        if start:
            if release is not None:
                self._show(release)
            else:
                self._look()

    def build(self) -> None:
        body = self.body
        ttk.Label(body, text="MiToolkit updates", font=self.fonts.heading).pack(anchor="w")
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
        self.download_btn = Button(row, text="Download only", command=self._download)       # beside Install
        self.page_btn = Button(row, text="Release page", command=self._open_page)
        self.reveal_btn = Button(row, text="Show in folder", command=self._reveal)
        self.row = row

    def _say(self, text: str, colour: str = "") -> None:
        if self.alive():
            self.line.configure(text=text, foreground=colour)

    def _refit(self) -> None:
        """The window fits its content once, when it is built: grow it when buttons or notes appear later."""
        if not self.alive():
            return
        self.win.update_idletasks()
        need_w, need_h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        if need_w > self.win.winfo_width() or need_h > self.win.winfo_height():
            self.win.geometry(f"{max(need_w, self.win.winfo_width())}x{max(need_h, self.win.winfo_height())}")

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
            self._say(f"MiToolkit is up to date ({release.tag} is the latest).", GREEN)
            return
        self._say(f"{release.tag} is available.", "")
        if release.notes:
            self.notes.configure(state="normal")
            self.notes.delete("1.0", "end")
            self.notes.insert("1.0", release.notes)
            self.notes.configure(state="disabled")
            self.notes.pack(fill="x", pady=(8, 0), before=self.row)
        for button in (self.page_btn, self.download_btn, self.action):       # right to left: Close, then these
            button.pack_forget()
        if updater.can_self_update():
            self.action.configure(text="Install and restart")
            self.action.pack(side="right", padx=6)
            self.download_btn.pack(side="right")
        else:
            # not the single-file program: it cannot replace itself, so offer the release file to download
            self.action.configure(text="Download")
            self.action.pack(side="right", padx=6)
            self._say(f"{release.tag} is available. This copy is not the single-file program, so it cannot update "
                      "itself. Download the release file for this system (checked against its checksum), or update "
                      "the way you installed it.", "")
        self.page_btn.pack(side="right", padx=6)
        self._refit()

    def _open_page(self) -> None:
        if self.release is not None:
            webbrowser.open(self.release.page)

    # ---------------------------------------------------------------- installing
    def _action(self) -> None:
        if self.release is None or self._busy:
            return
        if not updater.can_self_update():
            self._download()
            return
        self._begin("Downloading and checking the update...")
        release = self.release
        exe = updater.running_program()
        part = exe.with_name(exe.name + ".new")

        def work() -> None:
            try:
                updater.download(release, part, self._progress_to_ui, self.cancel)
                self.app.call_soon(self._ready, part, None)
            except Exception as err:
                self.app.call_soon(self._ready, None, str(err))

        threading.Thread(target=work, daemon=True, name="update-download").start()

    def _begin(self, text: str) -> None:
        """Something is downloading: grey the buttons, show the bar."""
        self._busy = True
        for button in (self.action, self.download_btn):
            button.configure(state="disabled")
        self.bar.configure(value=0)
        self.bar.pack(fill="x", pady=(10, 0), before=self.row)
        self._say(text, MUTED)
        self._refit()

    def _end(self) -> None:
        self._busy = False
        if self.alive():
            self.bar.pack_forget()
            for button in (self.action, self.download_btn):
                button.configure(state="normal")

    def _progress_to_ui(self, done: int, total: int) -> None:
        if total:
            self.app.call_soon(self._progress, 100 * done / total)

    def _progress(self, percent: float) -> None:
        if self.alive():
            self.bar.configure(value=percent)

    def _ready(self, part: Optional[Path], error: Optional[str]) -> None:
        if not self.alive():
            self._busy = False
            return
        self._end()
        if part is None:
            self._say(error or "The update failed.", RED)
            self.app.log(f"Update failed: {error}")
            return
        try:
            program = updater.install(part)
        except updater.UpdateError as err:
            self._say(str(err), RED)
            self.app.log(f"Update failed: {err}")
            return
        self.app.log(f"Updated to {self.release.tag if self.release else 'the new version'}; restarting.")
        self._say("Updated. Restarting...", GREEN)
        self.win.after(600, lambda: self._restart(program))

    # --------------------------------------------------------------- downloading only
    def _download(self) -> None:
        """Save the release file for this system in Downloads (checked), without installing anything."""
        if self.release is None or self._busy:
            return
        self._begin("Downloading and checking the release...")
        release, folder = self.release, updater.downloads_folder()

        def work() -> None:
            try:
                path = updater.download_to(release, folder, self._progress_to_ui, self.cancel)
                self.app.call_soon(self._downloaded, path, None)
            except Exception as err:
                self.app.call_soon(self._downloaded, None, str(err))

        threading.Thread(target=work, daemon=True, name="release-download").start()

    def _downloaded(self, path: Optional[Path], error: Optional[str]) -> None:
        if not self.alive():
            self._busy = False
            return
        self._end()
        if path is None:
            self._say(error or "The download failed.", RED)
            self.app.log(f"Download failed: {error}")
            return
        self.saved = path
        self.app.log(f"Downloaded {path.name} to {path.parent}.")
        self._say(f"Saved to {path} (its checksum matches the release). It was not installed: run it, or replace "
                  "the program you use now.", GREEN)
        self.reveal_btn.pack(side="right", padx=6, before=self.page_btn)
        self._refit()

    def _reveal(self) -> None:
        if self.saved is not None:
            try:
                updater.reveal(self.saved)
            except OSError as err:
                self._say(f"Could not open the folder ({err.strerror or err.__class__.__name__}).", RED)

    def _restart(self, program: Path) -> None:
        try:
            updater.restart(program)
        except OSError as err:
            self._say(f"Updated, but could not start the new version ({err}). Open MiToolkit again.", RED)
            return
        self.app.root.after(100, self.app.root.destroy)

    def close(self) -> None:
        self.cancel.set()
        super().close()
