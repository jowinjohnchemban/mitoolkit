"""
Tkinter GUI for miunlock: one plain window with the system's native look.

Four sections, top to bottom: Mi Account, Phone, Eligibility, Unlock. A "Next:" line at the
top says what to do now. The window has the usual menus (File, Unlock, Phone, View, Help) and a status line.

The one destructive action, the unlock itself, needs two deliberate acts: tick a box saying
the data is backed up, and type the phone's name. Only then does the button come alive, and
only that button sets confirm_wipe=True. See api.py for why the confirmation is never
defaulted or inferred.
"""
from __future__ import annotations

import ctypes
import io
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional

from miunlock import __version__, adb, api, details, export, fastboot, log, memory, security, usbio, watchdog
from miunlock.auth import store
from miunlock.auth.redact import mask_id
from miunlock.errors import MiunlockError
from miunlock.hints import explain
from miunlock.system import NO_WINDOW
from miunlock.ui.activity_window import ActivityLog, ActivityWindow
from miunlock.ui.apps_dialog import AppManagerDialog
from miunlock.ui.backup_dialog import BackupDialog
from miunlock.ui.base import fit_to_screen
from miunlock.ui.components.button_row import ButtonRow
from miunlock.ui.components.buttons import Button, ModernButton
from miunlock.ui.driver_dialog import DriverHelpDialog
from miunlock.ui.guide_window import GuideWindow
from miunlock.ui.menu import MenuBar
from miunlock.ui.components.details_view import DetailsView
from miunlock.ui.components.scroll_page import ScrollPage
from miunlock.ui.components.shapes import page_background
from miunlock.ui.components.skeleton import Skeleton
from miunlock.ui.security_dialog import SecurityDialog
from miunlock.ui.theme import (AMBER, GREEN, MUTED, ORANGE_DOT, RED, Fonts, apply_theme, scale_fonts)


POLL_MS = 1000           # how often the window looks for the phone: an unplugged phone shows within a second
INFO_REFRESH_S = 15     # how often the basic phone details (battery, storage, ...) are read again
MORE_REFRESH_S = 20      # and the extra details (Wi-Fi, uptime, ...) while Show more is open


class _LogStream(io.TextIOBase):
    """Collects what the library prints (login progress, fastboot output) for the Activity
    log. Also keeps printing safe in a windowed program, where sys.stdout would be None."""

    def __init__(self, sink: Callable[[str], None]):
        self._sink = sink

    def write(self, text: str) -> int:
        if text and text.strip():
            self._sink(text.rstrip())
        return len(text or "")

    def flush(self) -> None:  # pragma: no cover - nothing to do
        pass

    def isatty(self) -> bool:
        return False


class App:
    ZOOM_STEPS = (0.9, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)  # up to 200% (WCAG 1.4.4)

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"miunlock {__version__}")
        root.minsize(640, 460)
        try:
            self._icon = tk.PhotoImage(file=str(Path(__file__).parent / "assets" / "logo.png"))
            root.iconphoto(True, self._icon)
        except Exception:  # the logo is cosmetic; never fail because of it
            pass

        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.token: Optional[dict] = None
        self.zone: Optional[str] = None
        self.fastboot: Optional[str] = None
        self.device: Optional[str] = None      # serial of the phone in fastboot mode
        self.android: Optional[dict] = None    # phone seen by adb while running Android
        self.fb_info: Optional[dict] = None
        self.eligibility: Optional[dict] = None
        self.unlocked = False
        self.busy = False
        self._polling = False
        self._scan_started = 0.0
        self._info: dict = {}
        self._fbinfo: dict = {}
        self._guide: Optional[GuideWindow] = None
        self._live = None  # the Live status window (imported when first opened: it brings in the charts)
        self.activity = ActivityLog()
        self._activity_win: Optional[ActivityWindow] = None
        self._none_since: Optional[float] = time.time()
        self._wrap_labels: List[ttk.Label] = []
        self._zoom_factor = 1.0
        self._f1_logged = False
        self.check_skel: Optional[Skeleton] = None
        root.report_callback_exception = self._on_callback_error   # a slip in one handler never ends the program
        self._more_open = False
        self._more_built: Optional[tuple] = None   # which readings the Show more rows were built from
        self._more_view = None
        self._more_at = 0.0                        # when the extra details were last read
        self._prefetching = False
        self._info_at: dict = {}                   # serial -> when the basic details were last read
        self._more: dict = {}                  # (mode, serial) -> sections from details.py

        self.theme = apply_theme(root)
        self.bg = self.theme["bg"]
        self.fonts = Fonts(root)
        self.f_base, self.f_bold, self.f_title, self.f_small = (
            self.fonts.base, self.fonts.bold, self.fonts.title, self.fonts.small)

        self._menu()
        self._statusbar()
        self.page = ScrollPage(root, self.bg, self._on_page_width)
        self.page.pack(fill="both", expand=True)
        self._build(self.page.content)
        self._bindings()
        fit_to_screen(root, 860, 720)  # after the menu exists, so it isn't moved afterwards
        self._refresh()
        self._render_status()

        root.after(100, self._pump)
        root.after(300, self._prepare_fastboot)

    def release_memory(self) -> None:
        """Drop what can be rebuilt (called when memory runs high): chart images and the cached
        'Show more' readings. The next view reads them again."""
        from miunlock.ui.components import render
        render.release_images()
        self._more.clear()
        self._more_built = None
        for child in self.more_box.winfo_children():      # the built rows too (they hold hundreds of widgets)
            child.destroy()

    def window_stalled(self, seconds: float) -> None:
        """Called by the watchdog's thread when the window stopped answering. Only queues a note
        (the queue is thread safe); the window shows it when it wakes up."""
        self._log(f"The window was busy for {seconds:.0f} s. A report of what was running was saved to the log file.")

    def _on_callback_error(self, exc, value, tb) -> None:
        """Tk calls this when a handler raises. Record it in the activity log and the log file and
        carry on, instead of printing a traceback to a console nobody sees (or stopping)."""
        import traceback
        detail = "".join(traceback.format_exception(exc, value, tb)).strip().splitlines()
        self._log(f"Internal error: {exc.__name__}: {value}")
        for line in detail[-8:]:  # the traceback goes to the log file (which never holds tokens), not the screen
            log.get("gui").error(line)
        self._set_status("Something went wrong; see File > Activity log.")

    # ================================================================ layout
    def _menu(self) -> None:
        self.menubar = MenuBar(self)

    def _statusbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 4))
        bar.pack(side="bottom", fill="x")
        ttk.Separator(self.root, orient="horizontal").pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self.status = ttk.Label(bar, text="Ready.", foreground=MUTED)
        self.status.pack(side="left")
        self.last_activity = ttk.Label(bar, text="", foreground=MUTED)
        self.last_activity.pack(side="left", padx=(12, 0), fill="x", expand=True)

    def _wrap(self, parent, text="", **kw) -> ttk.Label:
        lab = ttk.Label(parent, text=text, justify="left", wraplength=600, **kw)
        self._wrap_labels.append(lab)
        return lab

    def _section(self, parent, title: str) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text=title, padding=12)
        frame.pack(fill="x", pady=(0, 10))
        return frame

    def _build(self, page) -> None:
        self.next_line = self._wrap(page, "", font=self.fonts.heading)
        self.next_line.pack(anchor="w", pady=(0, 2))
        self._wrap(page, "Unlocking erases all data on the phone and can't be undone. Back up first "
                         "(step 2 has a Back up files button).", foreground=MUTED).pack(anchor="w", pady=(0, 10))

        # 1. Mi Account
        self.f1 = self._section(page, "1. Mi Account")
        self.f1_note = self._wrap(self.f1, "Opens Xiaomi's own login page. Your password is never entered here.",
                                  foreground=MUTED)
        self.f1_note.pack(anchor="w")
        self.f1_row = ttk.Frame(self.f1)
        self.f1_row.pack(fill="x", pady=(8, 0))
        self.login_btn = Button(self.f1_row, text="Sign in", icon="user", command=self._login)
        self.login_btn.pack(side="left")
        self.r1 = self._wrap(self.f1_row, "", foreground=MUTED)
        self.r1.pack(side="left", padx=10)
        self.signout_btn = Button(self.f1_row, text="Sign out", command=self._sign_out)   # shown once signed in

        # 2. Phone
        self.f2 = self._section(page, "2. Phone")
        head = ttk.Frame(self.f2)
        head.pack(fill="x")
        self.rescan_btn = Button(head, text="Rescan", icon="refresh", command=self._rescan)
        self.rescan_btn.pack(side="right", anchor="n")
        self.dev_dot = tk.Label(head, text="\u25cf", fg=MUTED, bg=self.bg, font=self.f_base)
        self.dev_dot.pack(side="left", anchor="n")
        self.dev_text = ttk.Label(head, text="Looking for a phone...", font=self.f_bold, justify="left")
        self.dev_text.pack(side="left", padx=6, fill="x", anchor="n")
        self.dev_detail = self._wrap(self.f2, "", foreground=MUTED)
        self.dev_detail.pack(anchor="w", padx=(22, 0), pady=(2, 0))
        # One aligned row of equal-width buttons: the main action first (bold), then the tools
        # that work while the phone runs Android.
        self.buttons = ButtonRow(self.f2)
        self.stop_adb_btn = Button(self.buttons, text="Stop Google's adb", primary=True, command=self._stop_google_adb)
        self.driver_btn = Button(self.buttons, text="Driver help", primary=True, command=self._driver_help)
        self.leave_btn = Button(self.buttons, text="Restart phone...", icon="power", command=self._restart_dialog)
        self.fb_btn = Button(self.buttons, text="Reboot to fastboot", primary=True, icon="power", command=self._to_fastboot)
        self.tool_btns = [Button(self.buttons, text=text, icon=icon, command=cmd) for text, icon, cmd in (
            ("Back up files...", "save", self._backup_dialog), ("Manage apps...", "apps", self._apps_dialog),
            ("Security check...", "shield", self._security_dialog), ("Live status...", "chart", self._live_dialog),
            ("Connections...", "wifi", self._connect_dialog))]
        self.security_btn = self.tool_btns[2]       # takes the colour of the last security check
        self._security: dict = {}                    # serial -> verdict of the last full check
        self._passive: dict = {}                     # serial -> verdict of the quick check made on connecting
        self.dev_tip = self._wrap(self.f2, "", foreground=AMBER)
        self.details = ttk.Frame(self.f2)
        self.info_box = ttk.Frame(self.details)
        self.info_box.pack(fill="x")
        self.more_box = ttk.Frame(self.details)  # "Show more": filled on demand
        # "Show more" is an expander bar (a flat, full-width row with a chevron), not a button
        self.more_btn = Button(self.details, text="Show more", icon="down", kind="flat", command=self._toggle_more)
        self.more_btn.pack(fill="x", pady=(8, 0))
        # Copy details sits at the top of the section, beside Rescan, while there are details to copy
        self.copy_btn = Button(head, text="Copy details", icon="copy", command=self._copy_device)
        self.export_btn = Button(head, text="Export...", icon="save", command=self._export_device)

        # 3. Eligibility
        self.f3 = self._section(page, "3. Eligibility")
        row2 = ttk.Frame(self.f3)
        row2.pack(fill="x")
        self.check_btn = Button(row2, text="Check eligibility", command=self._check)
        self.check_btn.pack(side="left")
        self.check_hint = self._wrap(row2, "", foreground=MUTED)
        self.check_hint.pack(side="left", padx=10)
        self.r2_title = ttk.Label(self.f3, text="", font=self.f_bold)
        self.r2_body = self._wrap(self.f3, "")
        self.r2_raw = self._wrap(self.f3, "", foreground=MUTED)

        # 4. Unlock
        self.f4 = self._section(page, "4. Unlock")
        self.d3 = self._wrap(self.f4, "Available once Xiaomi says the phone is eligible.", foreground=MUTED)
        self.d3.pack(anchor="w")
        self.confirm_var = tk.BooleanVar(value=False)
        self.name_var = tk.StringVar()
        self.confirm_var.trace_add("write", lambda *_: self._refresh())
        self.name_var.trace_add("write", lambda *_: self._refresh())
        self.chk = ttk.Checkbutton(self.f4, text="I have backed up my data and understand it will be erased.",
                                   variable=self.confirm_var)
        self.chk.pack(anchor="w", pady=(8, 0))
        nrow = ttk.Frame(self.f4)
        nrow.pack(fill="x", pady=(6, 0))
        self.name_lbl = ttk.Label(nrow, text="Type the phone's name to confirm:")
        self.name_lbl.pack(side="left")
        self.name_entry = ttk.Entry(nrow, textvariable=self.name_var, width=18)
        self.name_entry.pack(side="left", padx=8)
        row3 = ttk.Frame(self.f4)
        row3.pack(fill="x", pady=(10, 0))
        self.unlock_btn = Button(row3, text="Erase phone and unlock", icon="lock", kind="danger", command=self._unlock)
        self.unlock_btn.pack(side="left")
        self.reboot_btn = Button(row3, text="Restart phone", command=self._reboot)
        self.r3 = self._wrap(self.f4, "")

    def _bindings(self) -> None:
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self.root.bind_all("<Button-4>", self._on_wheel)  # Linux
        self.root.bind_all("<Button-5>", self._on_wheel)

    # ============================================================ geometry
    def _on_page_width(self, width: int) -> None:
        """Re-wrap text for the page width (called once per resize, after it settles)."""
        inner = width - 40 - 24  # page padding and section padding
        self._wrap_labels = [lab for lab in self._wrap_labels if lab.winfo_exists()]  # drop destroyed ones
        for lab in self._wrap_labels:
            lab.configure(wraplength=max(inner - 40, 260))
        self.dev_text.configure(wraplength=max(inner - self.rescan_btn.winfo_reqwidth() - 40, 160))

    def _relayout(self) -> None:
        self._on_page_width(self.page.width())

    def _on_wheel(self, event):
        """Scroll the page when the pointer is over it; other windows scroll themselves."""
        try:
            widget = event.widget if isinstance(event.widget, tk.Misc) else self.root.nametowidget(event.widget)
            if widget.winfo_toplevel() is not self.root:
                return
        except (KeyError, tk.TclError):
            return
        step = -1 if (getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0) else 1
        self.page.scroll(step * 3)

    def _zoom(self, direction: int) -> None:
        """Make all text larger (+1), smaller (-1) or normal (0)."""
        i = self.ZOOM_STEPS.index(self._zoom_factor)
        i = self.ZOOM_STEPS.index(1.0) if direction == 0 else max(0, min(len(self.ZOOM_STEPS) - 1, i + direction))
        self._zoom_factor = self.ZOOM_STEPS[i]
        scale_fonts(self.root, self._zoom_factor, self.fonts.all())
        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=round(26 * self._zoom_factor))
        style.theme_use(style.theme_use())  # every themed widget re-measures its text
        self._remeasure(self.root)
        self.root.update_idletasks()
        self._relayout()
        self._set_status(f"Text size {round(self._zoom_factor * 100)}%")

    def _remeasure(self, widget) -> None:
        for child in widget.winfo_children():
            if isinstance(child, (ModernButton, DetailsView)):
                child.refresh()
            elif isinstance(child, (ttk.Button, ttk.Menubutton, ttk.Checkbutton)):
                child.configure(text=child.cget("text"))
            self._remeasure(child)

    # ===================================================== thread plumbing
    def run(self, work: Callable[[], object], done: Callable[[str, object], None], text: str) -> None:
        """Run work() on a thread, then done(status, result) on the UI thread."""
        self._run(work, done, text)

    def log(self, text: str) -> None:
        """Add a line to the Activity log. Safe from any thread."""
        self._log(text)

    def call_soon(self, fn: Callable, *args) -> None:
        """Run fn(*args) on the UI thread. Safe from any thread."""
        self.q.put(("call", fn, args))

    def _log(self, text: str):
        self.q.put(("log", text))

    def _append_log(self, text: str):
        stamp, msg, kind = self.activity.add(text)
        self.last_activity.configure(text=f"{stamp}  {msg}",
                                     foreground=RED if kind == "bad" else (GREEN if kind == "good" else MUTED))

    def _toggle_details(self):
        if self._activity_win is not None and self._activity_win.alive():
            self._activity_win.focus()
        else:
            self._activity_win = ActivityWindow(self)

    def _set_status(self, text: str):
        self.status.configure(text=text)

    def _set_busy(self, busy: bool, text: str = ""):
        self.busy = busy
        if busy:
            self.progress.pack(side="right", padx=10)
            self.progress.start(12)
            self._set_status(text)
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self._set_status("Ready.")
        self._refresh()

    def _run(self, work: Callable[[], object], done: Callable[[str, object], None], text: str):
        self._set_busy(True, text)

        def target():
            try:
                self.q.put(("done", done, "ok", work()))
            except MiunlockError as err:
                self.q.put(("done", done, "error", str(err)))
            except Exception as err:  # never let a worker thread kill the window
                self.q.put(("done", done, "error", f"Unexpected error: {err}"))

        threading.Thread(target=target, daemon=True).start()

    def _pump(self):
        """Hand what the worker threads queued to the window. One failing item must never stop the
        pump (it would end every later update, and Rescan with it), so each is guarded and the next
        round is always scheduled."""
        try:
            for _ in range(60):                        # at most this many per round: the window stays responsive
                try:
                    kind, *rest = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    if kind == "log":
                        self._append_log(rest[0])
                    elif kind == "done":
                        done, status, payload = rest
                        self._set_busy(False)
                        done(status, payload)
                    elif kind == "fastboot":
                        self._fastboot_ready(*rest)
                    elif kind == "call":
                        rest[0](*rest[1])
                    elif kind == "device":
                        self._device_seen(*rest)
                except Exception:
                    log.get("gui").exception("A queued update failed (%s)", kind)
                    if kind == "done":
                        self._set_busy(False)          # never leave the window stuck busy
        finally:
            self.root.after(100, self._pump)

    # ================================================================ state
    def _next_step(self) -> str:
        """The one thing to do now, in plain words."""
        if self.unlocked:
            return "Done. The bootloader is unlocked."
        if self.token is None:
            return "Next: sign in to your Mi Account (step 1)."
        state = self._state()
        if self.eligibility and self.eligibility.get("eligible"):
            return "Next: confirm, then unlock (step 4)."
        if state == "fastboot":
            return "Next: check eligibility (step 3)."
        if state == "device":
            return "Next: restart the phone into fastboot mode (step 2)."
        return "Next: connect your phone (step 2)."

    def _refresh(self):
        logged = self.token is not None
        ready = bool(self.eligibility and self.eligibility.get("eligible")) and not self.unlocked

        self.next_line.configure(text=self._next_step())
        self.f1.configure(text="1. Mi Account" + ("  \u2714 signed in" if logged else ""))
        self.login_btn.configure(state="disabled" if self.busy else "normal")
        self.signout_btn.configure(state="disabled" if self.busy else "normal")
        # once signed in, only the account line is left: no instructions, no dead button
        if logged != self._f1_logged:  # re-pack only on a change, not on every refresh
            self._f1_logged = logged
            for widget in (self.f1_note, self.f1_row, self.login_btn, self.signout_btn):
                widget.pack_forget()
            if logged:
                self.f1_row.pack(fill="x")
                self.signout_btn.pack(side="right")
                self.r1.pack_configure(padx=0)
            else:
                self.f1_note.pack(anchor="w")
                self.f1_row.pack(fill="x", pady=(8, 0))
                self.login_btn.pack(side="left", before=self.r1)
                self.r1.pack_configure(padx=10)

        can_check = logged and not self.unlocked and bool(self.device) and not self.busy
        self.check_btn.configure(state="normal" if can_check else "disabled")
        if self.unlocked:
            hint = ""
        elif not logged:
            hint = "Sign in first."
        elif not self.device:
            hint = "The phone must be in fastboot mode."
        else:
            hint = ""
        self.check_hint.configure(text=hint)
        self.f3.configure(text="3. Eligibility" + ("  \u2714 eligible" if ready or self.unlocked else ""))

        on = "normal" if ready else "disabled"
        self.chk.configure(state=on)
        self.name_entry.configure(state=on)
        match = bool(ready and self.eligibility and
                     self.name_var.get().strip().lower() == str(self.eligibility["product"]).lower())
        can_unlock = ready and self.confirm_var.get() and match and not self.busy
        self.unlock_btn.configure(state="normal" if can_unlock else "disabled")
        self.f4.configure(text="4. Unlock" + ("  \u2714 done" if self.unlocked else ""))

    # ============================================================ the phone
    def _prepare_fastboot(self):
        def work():
            try:
                self.q.put(("fastboot", fastboot.ready(), None))
            except SystemExit:
                self.q.put(("fastboot", None, "fastboot is not available on this system."))
            except Exception as err:
                self.q.put(("fastboot", None, str(err)))

        threading.Thread(target=work, daemon=True).start()

    def _fastboot_ready(self, how: Optional[str], error: Optional[str]):
        if error or not how:
            self.dev_dot.configure(fg=RED)
            self.dev_text.configure(text=error or "USB access is not available", foreground=RED)
            self._log(error or "USB access is not available")
            return
        self.fastboot = how
        self._log(f"Using {how}. No adb or fastboot program is needed.")
        self._render_status()
        self.root.after(500, self._poll_device)

    def _poll_device(self):
        if not self.fastboot:
            return
        try:
            self._scan()
            self._update_tip()
            if self._android_serial():                 # keep the extra details ready, and fresh while shown
                stale = time.monotonic() - self._more_at > MORE_REFRESH_S
                self._prefetch_more(force=self._more_open and stale)
        except Exception:
            log.get("gui").exception("Looking for the phone failed")
        finally:
            self.root.after(POLL_MS, self._poll_device)   # keep looking whatever happened this time

    def _rescan(self):
        """The Rescan button: look again now, even if the last look seems stuck."""
        if not self.fastboot:
            self._set_status("USB access is not ready yet; trying again...")
            self._prepare_fastboot()
            return
        if self.busy:
            self._set_status("Busy with another task; try again in a moment.")
            return
        if self._polling:
            if time.monotonic() - self._scan_started < 15:
                self._set_status("Already looking for the phone...")
                return
            self._polling = False                          # the last look took far too long: start over
            self._log("The last look took too long; looking again.")
        self._info.clear()                                 # read the phone's details afresh
        self._fbinfo.clear()
        self._set_status("Looking for the phone...")
        self._scan()

    def _update_tip(self):
        """After a while with no phone, say what usually fixes it."""
        waiting = self.device is None and self.android is None and self._none_since is not None \
            and time.time() - self._none_since > 20
        if waiting and not self.dev_tip.winfo_ismapped():
            self.dev_tip.configure(text="Still no phone. Use a data cable (not charge-only) in another USB port.")
            self.dev_tip.pack(anchor="w", padx=(22, 0), pady=(8, 0))
        elif not waiting and self.dev_tip.winfo_ismapped():
            self.dev_tip.pack_forget()

    def _scan(self):
        if not self.fastboot or self.busy or self._polling:
            return
        self._polling = True
        self._scan_started = time.monotonic()

        def work():
            serial = android = fbinfo = None
            try:
                found = fastboot.devices()
                usable = [d for d in found if d["accessible"]]
                if usable:
                    serial = usable[0]["serial"]
                elif found:  # in fastboot, but it cannot be opened
                    android = {"serial": found[0]["serial"], "state": "no-access", "mode": "fastboot",
                               "reason": found[0].get("reason")}
            except Exception:
                serial = None
            if serial is None and android is None:
                try:  # no phone in fastboot: is one running Android?
                    found = adb.devices()
                    if found:
                        ready = [d for d in found if d["state"] == "device"]
                        android = dict(ready[0] if ready else found[0])
                        if android["state"] == "device":
                            serial_ = android["serial"]
                            stale = time.monotonic() - self._info_at.get(serial_, 0) > INFO_REFRESH_S
                            if serial_ not in self._info or stale:       # battery, storage ... change: re-read
                                self._info[serial_] = adb.device_info(serial_)
                                self._info_at[serial_] = time.monotonic()
                                self._quick_audit(serial_, self._info[serial_])
                            android.update(self._info[serial_])
                except Exception:
                    android = None
            if android and android.get("state") == "no-access":  # say why, off the UI thread
                reason = android.get("reason") or usbio.BUSY
                android["adb_running"] = reason == usbio.BUSY and "adb" in usbio.blocking_programs()
                android["advice"] = usbio.no_access_advice(reason)
            if serial:
                try:
                    if serial not in self._fbinfo:
                        self._fbinfo[serial] = fastboot.info(serial)
                    fbinfo = self._fbinfo[serial]
                except Exception:
                    fbinfo = None
            self._polling = False
            self.q.put(("device", serial, android, fbinfo))

        def guarded():
            """A stuck USB call must not stop the looking for good: give up on it after 40 s, say so,
            and let the next scan try again."""
            try:
                watchdog.call_with_timeout(work, 40, "the phone scan")
            except watchdog.Stalled as err:
                self._log(f"{err} Trying again.")
            except Exception as err:
                log.get("gui").exception("Looking for the phone failed")
                self._log(f"Looking for the phone failed: {err}")
            finally:
                self._polling = False

        threading.Thread(target=guarded, daemon=True, name="scan").start()

    def _device_seen(self, serial: Optional[str], android: Optional[dict] = None, fb: Optional[dict] = None):
        if self.status.cget("text") == "Looking for the phone...":   # a Rescan finished
            self._set_status("Ready.")
        if serial == self.device and android == self.android and fb == self.fb_info:
            return  # nothing changed: no redraw
        was_connected = self.device is not None
        log.get("gui").debug("Phone state changed: fastboot=%s android=%s", serial,
                             {k: (android or {}).get(k) for k in ("serial", "state", "model", "reason")})
        self.device, self.android, self.fb_info = serial, android, fb
        self._none_since = None if (serial or android) else (self._none_since or time.time())
        self._render_status()
        if serial:
            self._log(f"Device detected in fastboot: {serial}")
        elif android and android["state"] == "device":
            self._log(f"Phone seen by adb: {android.get('model') or android['serial']}")
        elif not android:
            if was_connected:
                self._log("Device disconnected.")
            if self.eligibility is not None and not self.unlocked:
                self.eligibility = None
                self._show_check("", "", "", MUTED)
        self._refresh()

    @staticmethod
    def _phone_name(android: dict) -> str:
        """"POCO M2 Pro", not "POCO POCO M2 Pro" when the model already starts with the brand."""
        brand, model = (android.get("brand") or "").strip(), (android.get("model") or "").strip()
        if brand and model.lower().startswith(brand.lower()):
            return model
        return " ".join(x for x in (brand, model) if x)

    def _state(self) -> str:
        return "fastboot" if self.device else (self.android or {}).get("state", "none")

    def _status_for(self, state: str):
        """(dot colour, headline, what to do, action button or None). Short and plain."""
        android = self.android or {}
        if state == "fastboot":
            return GREEN, "Phone is in fastboot mode", "Ready to check. To leave without unlocking, restart it.", \
                self.leave_btn
        if state == "device":
            name = self._phone_name(android) or "Phone"
            return (ORANGE_DOT, f"{name} is on",
                    "To unlock, it must be in fastboot mode. Restarting into it is safe and erases nothing.",
                    self.fb_btn)
        if state == "no-access":
            reason = android.get("reason") or usbio.BUSY
            if reason == usbio.NO_DRIVER:
                return (AMBER, "Windows needs a driver for this phone",
                        "Install Google's USB driver, then reconnect the phone.", self.driver_btn)
            if reason == usbio.NO_PERMISSION:
                return AMBER, "This user can't open the phone", android.get("advice", ""), None
            return (AMBER, "Another program is using the phone", android.get("advice", ""),
                    self.stop_adb_btn if android.get("adb_running") else None)
        if state == "unauthorized":
            return (ORANGE_DOT, "Allow USB debugging on the phone",
                    "Unlock the phone and tap Allow on the prompt.", None)
        if state == "offline":
            return (ORANGE_DOT, "The phone isn't answering",
                    "Turn USB debugging off and on again, then reconnect it.", None)
        return (MUTED, "No phone found",
                "Connect it with a USB data cable. If it's off, hold Volume Down + Power to reach fastboot.", None)

    def _render_status(self) -> None:
        """Draw the phone's state. Called only when something changed."""
        state = self._state()
        colour, headline, detail, action = self._status_for(state)
        self.dev_dot.configure(fg=colour)
        self.dev_text.configure(text=headline, foreground=GREEN if colour == GREEN else "")
        self.dev_detail.configure(text=detail)
        for widget in (self.buttons, self.details):
            widget.pack_forget()
        row = ([action] if action is not None else []) + (self.tool_btns if state == "device" else [])
        self.buttons.set(row)
        self._paint_security_button()          # a different phone may have a different last result
        if row:
            self.buttons.pack(fill="x", padx=(22, 0), pady=(10, 0))
        pairs = [(k, v) for k, v in self._device_pairs() if v not in (None, "")]
        self._show_info(pairs)
        self._show_more()
        self.copy_btn.pack_forget()
        self.export_btn.pack_forget()
        if pairs:
            self.details.pack(fill="x", padx=(22, 0), pady=(10, 0))
            self.export_btn.pack(side="right", anchor="n", padx=(0, 8))  # beside Rescan, at the top
            self.copy_btn.pack(side="right", anchor="n", padx=(0, 8))

    def _show_info(self, pairs) -> None:
        for child in self.info_box.winfo_children():
            child.destroy()
        half = (len(pairs) + 1) // 2
        for col in (1, 3):
            self.info_box.columnconfigure(col, weight=1)
        for i, (label, value) in enumerate(pairs):
            row, col = i % half, (i // half) * 2
            ttk.Label(self.info_box, text=label, foreground=MUTED).grid(
                row=row, column=col, sticky="w", padx=(0 if col == 0 else 24, 12), pady=1)
            ttk.Label(self.info_box, text=str(value)).grid(row=row, column=col + 1, sticky="w", pady=1)

    def _device_pairs(self):
        serial, android, fb = self.device, self.android, self.fb_info
        if serial and fb:
            state = {"yes": "Already unlocked", "no": "Locked"}.get(str(fb.get("unlocked")).lower())
            mode = "fastbootd" if str(fb.get("userspace")).lower() == "yes" else "Fastboot (bootloader)"
            volts = fb.get("battery_voltage")
            return [
                ("Device", fb.get("product")), ("Mode", mode), ("Bootloader", state),
                ("Secure boot", {"yes": "On", "no": "Off"}.get(str(fb.get("secure")).lower())),
                ("Bootloader version", fb.get("bootloader_version")), ("Baseband", fb.get("baseband")),
                ("Variant", fb.get("variant")), ("Hardware revision", fb.get("hw_revision")),
                ("Anti-rollback", fb.get("anti_rollback")),
                ("Battery voltage", f"{volts} mV" if volts and str(volts).isdigit() else volts),
                ("Active slot", fb.get("slot")), ("Connection", fb.get("via")),
                ("Serial", fb.get("serial")),
            ]
        if android and android.get("state") == "device":
            lock = {True: "Locked", False: "Already unlocked"}.get(android.get("bootloader_locked"))
            battery, sdk, temp = android.get("battery"), android.get("sdk"), android.get("battery_temp_c")
            used, total = android.get("storage_used_gb"), android.get("storage_total_gb")
            return [
                ("Device", self._phone_name(android)), ("Codename", android.get("codename")),
                ("Android", f"{android.get('android')} (API {sdk})" if sdk else android.get("android")),
                ("HyperOS / MIUI", android.get("hyperos") or android.get("miui")),
                ("Build", android.get("build")), ("Security patch", android.get("security_patch")),
                ("Region", android.get("region") or android.get("variant")),
                ("Chipset", android.get("chipset") or android.get("platform")),
                ("Memory", f"{android['ram_gb']} GB" if android.get("ram_gb") else None),
                ("Storage", f"{used} of {total} GB used" if used is not None and total else None),
                ("Screen", android.get("screen")), ("Kernel", android.get("kernel")),
                ("Bootloader", lock),
                ("Verified boot", {"green": "Green (official)", "yellow": "Yellow", "orange": "Orange (unlocked)",
                                   "red": "Red"}.get(str(android.get("verified_boot")).lower(),
                                                     android.get("verified_boot"))),
                ("Encryption", {"encrypted": "On", "unencrypted": "Off"}.get(str(android.get("encryption")),
                                                                             android.get("encryption"))),
                ("Battery", None if battery is None else f"{battery}%" + (f", {temp:.0f} °C" if temp else "")),
                ("Serial", android["serial"]),
            ]
        return []

    def _device_key(self):
        if self.device:
            return ("fastboot", self.device)
        serial = self._android_serial()
        return ("android", serial) if serial else None

    def _toggle_more(self) -> None:
        self._more_open = not self._more_open
        self._show_more()

    def _show_more(self) -> None:
        """Show or hide the extra details; fetch them the first time. Hiding only hides: the rows stay
        built, so Show less is instant and Show more again is too (building them is the slow part)."""
        key = self._device_key()
        self.more_btn.configure(text="Show less" if self._more_open else "Show more",
                                icon="up" if self._more_open else "down", state="normal" if key else "disabled")
        if not (self._more_open and key):
            self.more_box.pack_forget()
            self.page.refit()                           # no blank gap or stale pixels where the rows were
            return
        if key not in self._more:
            for child in self.more_box.winfo_children():
                child.destroy()
            self._more_built = None
            self.more_box.pack(fill="x", before=self.more_btn, pady=(8, 0))
            Skeleton(self.more_box, rows=8, widths=(0.3, 0.55, 0.45, 0.62, 0.4, 0.3, 0.58, 0.5),
                     label="Reading details").pack(fill="x", pady=(6, 0))
            self._read_more(key)
            return
        built = (key, id(self._more[key]))
        if self._more_built != built:                  # new phone or new readings: build the rows once
            self._build_more(key)
            self._more_built = built
        self.more_box.pack(fill="x", before=self.more_btn, pady=(8, 0))

    def _build_more(self, key) -> None:
        """One text widget with all the sections: built in milliseconds, selectable, and it sizes itself."""
        for child in self.more_box.winfo_children():
            child.destroy()
        self._more_view = DetailsView(self.more_box, self.fonts, MUTED, page_background(self.more_box))
        self._more_view.pack(fill="x")
        self._more_view.set_sections(self._more[key])

    def _prefetch_more(self, force: bool = False) -> None:
        """Read the extra details in the background as soon as a phone is on, so Show more opens at once.
        With force=True re-read them (they change: Wi-Fi, battery, uptime)."""
        key = self._device_key()
        if not key or key[0] != "android" or self._prefetching or (key in self._more and not force):
            return
        self._prefetching = True
        serial = key[1]

        def work():
            try:
                result = watchdog.call_with_timeout(lambda: adb.more_details(serial), 40, "the phone")
                self.q.put(("call", self._more_ready, (key, result)))
            except Exception as err:
                log.get("gui").debug("Could not prefetch details: %s", err)
                self.q.put(("call", self._more_ready, (key, None)))

        threading.Thread(target=work, daemon=True, name="prefetch-details").start()

    def _more_ready(self, key, result) -> None:
        self._prefetching = False
        self._more_at = time.monotonic()
        if result is None or key != self._device_key():
            return
        changed = self._more.get(key) != result
        self._more[key] = result
        if self._more_open and changed:
            self._more_built = None
            self._show_more()

    def _read_more(self, key) -> None:
        mode, serial = key
        self._log("Reading all details from the phone (read-only)...")

        def work():
            return adb.more_details(serial) if mode == "android" else details.fastboot_details(serial)

        def done(status, result):
            if status == "error":
                self._more_open = False
                self._log(f"Could not read more details: {result}")
                messagebox.showerror("Show more", str(result))
            else:
                self._more[key] = result
            self._show_more()

        self._run(work, done, "Reading details from the phone...")

    def _copy_device(self):
        pairs = [(k, v) for k, v in self._device_pairs() if v not in (None, "")]
        if pairs:
            extra = details.as_text(self._more.get(self._device_key(), [])) if self._more_open else ""
            text = "\n".join(f"{k}: {v}" for k, v in pairs)
            self.root.clipboard_clear()
            self.root.clipboard_append(text + ("\n\n" + extra if extra else ""))
            self._set_status("Device details copied.")

    def _export_device(self) -> None:
        """Save the device details (and the extra details, once read) as text, CSV or Markdown."""
        pairs = [(k, v) for k, v in self._device_pairs() if v not in (None, "")]
        if not pairs:
            return
        types = [(f"{label} (*.{ext})", f"*.{ext}") for ext, label in export.FORMATS.items()]
        name = export.suggested_name("txt", self._phone_name(self.android or {}) or "phone")
        path = filedialog.asksaveasfilename(parent=self.root, title="Export device details", initialfile=name,
                                            defaultextension=".txt", filetypes=types)
        if not path:
            return
        fmt = Path(path).suffix.lstrip(".").lower()
        fmt = fmt if fmt in export.FORMATS else "txt"
        try:
            text = export.render(fmt, pairs, self._more.get(self._device_key(), []))
            Path(path).write_text(text, encoding="utf-8-sig" if fmt == "csv" else "utf-8", newline="\n")
        except (OSError, ValueError) as err:
            messagebox.showerror("Export device details", f"Could not save the file.\n\n{err}")
            return
        self._set_status(f"Saved {Path(path).name}")
        self._log(f"Device details exported to {path}")

    def _wireless_dialog(self) -> None:
        from miunlock.ui.wireless_dialog import WirelessDialog   # not needed until first opened
        if getattr(self, "_wireless", None) is not None and self._wireless.alive():
            self._wireless.focus()
        else:
            self._wireless = WirelessDialog(self)

    def _to_fastboot(self):
        serial = (self.android or {}).get("serial")
        if not serial:
            return
        if ":" in serial:                                  # connected over Wi-Fi
            messagebox.showinfo(
                "Connect the USB cable", "This phone is connected over Wi-Fi, and fastboot mode works over a USB "
                "cable only.\n\nPlug the phone into this computer with a USB cable, then choose this again.")
            self._log("Fastboot needs a USB cable: this phone is connected over Wi-Fi.")
            return
        self._log("Asking the phone to reboot into fastboot mode (nothing is erased)...")

        def work():
            adb.reboot_to_bootloader(serial)
            self._info.pop(serial, None)

        def done(status, result):
            if status == "error":
                self._log(f"Could not reboot to fastboot: {result}")
                messagebox.showerror("Reboot to fastboot", str(result))

        self._run(work, done, "Rebooting the phone into fastboot mode...")

    def _restart_dialog(self) -> None:
        """Restart or power off: pick the mode in one place (works in Android and in fastboot mode)."""
        if not (self._android_serial() or self.device):
            return
        from miunlock.ui.restart_dialog import RestartDialog
        if getattr(self, "_restart", None) is not None and self._restart.alive():
            self._restart.focus()
        else:
            self._restart = RestartDialog(self)

    def restart_to(self, mode: str) -> None:
        """Do what the restart dialog chose: "android", "recovery", "fastboot" or "off"."""
        if self.device:                                           # in fastboot mode: leave it
            self._reboot("recovery" if mode == "recovery" else "")
        elif mode == "fastboot":
            self._to_fastboot()
        elif mode == "off":
            self._power_off(confirm=False)
        else:
            self._restart_android("recovery" if mode == "recovery" else "", confirm=False)

    def _restart_android(self, mode: str, confirm: bool = True) -> None:
        """Restart a running phone normally ("") or into recovery mode. Nothing is erased."""
        serial = self._android_serial()
        if not serial:
            return
        where = "recovery mode" if mode == "recovery" else "Android"
        if confirm and not messagebox.askyesno(
                "Restart phone", f"Restart the phone into {where}?\n\nNothing is erased. Unsaved work on the "
                "phone is lost.", default="no"):
            return
        self._log(f"Restarting the phone into {where} (nothing is erased)...")

        def work():
            adb.reboot(mode, serial)
            self._info.pop(serial, None)

        def done(status, result):
            if status == "error":
                self._log(f"Could not restart: {result}")
                messagebox.showerror("Restart phone", str(result))

        self._run(work, done, f"Restarting the phone into {where}...")

    def _power_off(self, confirm: bool = True) -> None:
        serial = self._android_serial()
        if not serial or (confirm and not messagebox.askyesno(
                "Power off", "Shut the phone down?\n\nIt stays off until you press its power button.", default="no")):
            return
        self._log("Powering the phone off...")

        def work():
            adb.power_off(serial)
            self._info.pop(serial, None)

        def done(status, result):
            if status == "error":
                self._log(f"Could not power off: {result}")
                messagebox.showerror("Power off", str(result))

        self._run(work, done, "Powering the phone off...")

    def _connect_dialog(self) -> None:
        if not self._android_serial():
            return
        from miunlock.ui.connect_dialog import ConnectionsDialog  # not needed until first opened
        if getattr(self, "_connections", None) is not None and self._connections.alive():
            self._connections.focus()
        else:
            self._connections = ConnectionsDialog(self, self._android_serial(), self._phone_name(self.android or {}))

    def _log_dialog(self) -> None:
        if not self._android_serial():
            return
        from miunlock.ui.log_dialog import LogDialog  # not needed until first opened
        if getattr(self, "_logview", None) is not None and self._logview.alive():
            self._logview.focus()
        else:
            self._logview = LogDialog(self, self._android_serial(), self._phone_name(self.android or {}))

    # =============================================================== step 1
    def _login(self):
        self._log("Signing in...")
        self.r1.configure(text="Finish signing in in your browser...")

        def work():
            token = api.login(login_method="1", silent_if_cached=True)
            return token, api.get_account_zone(token)

        self._run(work, self._login_done, "Waiting for sign-in in your browser...")

    def _login_done(self, status: str, result):
        if status == "error":
            self.r1.configure(text=f"Sign-in didn't finish: {result}", foreground=RED)
            self._log(f"Sign-in failed: {result}")
            return
        self.token, self.zone = result
        who = mask_id(self.token["userId"])  # masked so screenshots don't expose the account ID
        self.r1.configure(text=f"Account {who} · data center: {self.zone}", foreground=MUTED)
        self._log(f"Signed in as {who} ({self.zone})")
        self._refresh()

    # =============================================================== step 2
    def _show_check(self, title: str, body: str, raw: str, colour: str):
        self.r2_title.configure(text=title, foreground=colour)
        self.r2_body.configure(text=body)
        self.r2_raw.configure(text=raw)
        for widget, has, pad in ((self.r2_title, title, (10, 0)), (self.r2_body, body, 0), (self.r2_raw, raw, (4, 0))):
            widget.pack_forget()
            if has:
                widget.pack(anchor="w", pady=pad)

    def _check(self):
        self.eligibility = None
        self._show_check("", "", "", MUTED)
        self.check_skel = Skeleton(self.f3, rows=3, widths=(0.4, 0.75, 0.55), label="Asking Xiaomi")
        self.check_skel.pack(fill="x", pady=(10, 0))
        self._log("Checking eligibility with Xiaomi...")
        self._run(lambda: api.check_unlock_eligibility(self.token, self.zone), self._check_done,
                  "Asking Xiaomi if this phone can be unlocked...")

    def _check_done(self, status: str, result):
        if self.check_skel is not None:
            self.check_skel.stop()
            self.check_skel.destroy()
            self.check_skel = None
        if status == "error":
            self._show_check("Couldn't check", str(result), "", RED)
            self._log(f"Check failed: {result}")
            return
        self._log(f"Xiaomi replied: { {k: v for k, v in result.items() if not k.startswith('_')} }")
        if result.get("eligible"):
            self.eligibility = result
            wipe = result.get("will_wipe_data")
            body = (f"Phone: {result['product']} · data center: {result['zone']}\n"
                    + ("This will ERASE all data on the phone." if wipe else "Xiaomi says this unlock will not erase data."))
            notice = result.get("notice")
            self._show_check("Ready to unlock", body, f"Xiaomi's notice: {notice}" if notice else "", GREEN)
            self.d3.configure(text=f"Phone: {result['product']}. Unlocking "
                                   f"{'erases all data on it' if wipe else 'will not erase data'} and cannot be undone.",
                              foreground=RED if wipe else MUTED)
            self.name_lbl.configure(text=f"Type the phone's name ({result['product']}) to confirm:")
            self.name_var.set("")
            self.confirm_var.set(False)
        else:
            hint = explain(result.get("code"), result.get("description"))
            raw = result.get("description") or result.get("error") or ""
            code = f"Code {result['code']}. " if result.get("code") else ""
            self._show_check(hint.title, hint.advice, f"{code}Xiaomi said: {raw}" if raw else "",
                             AMBER if hint.kind == "wait" else RED)
        self._refresh()

    # =============================================================== step 3
    def _set_r3(self, text: str, colour: str):
        self.r3.configure(text=text, foreground=colour)
        self.r3.pack_forget()
        if text:
            self.r3.pack(anchor="w", pady=(10, 0))

    def _unlock(self):
        # The button is only enabled when the box is ticked and the name matches,
        # but re-check here so nothing else can reach this path.
        if not (self.eligibility and self.confirm_var.get()
                and self.name_var.get().strip().lower() == str(self.eligibility["product"]).lower()):
            return
        self._set_r3("", MUTED)
        self._log("Unlocking... do not unplug the phone.")
        elig = self.eligibility
        self._run(lambda: api.perform_unlock(self.token, elig, confirm_wipe=True),
                  self._unlock_done, "Unlocking. Keep the phone connected...")

    def _unlock_done(self, status: str, result):
        if status == "error":
            self._set_r3(f"The unlock did not complete: {result}", RED)
            self._log(f"Unlock failed: {result}")
            return
        self.unlocked = True
        self._fbinfo.clear()
        self._set_r3("Bootloader unlocked. The phone is resetting; the first start can take several "
                     "minutes. If it stays on the fastboot screen, use Restart phone.", GREEN)
        self._log(f"Unlock finished: {result}")
        self.reboot_btn.pack(side="left", padx=10)
        self._refresh()

    def _reboot(self, mode: str = ""):
        """Leave fastboot mode: into Android (mode "") or recovery ("recovery"). Erases nothing."""
        if not self.fastboot or not self.device:
            return
        serial, where = self.device, "recovery mode" if mode == "recovery" else "Android"
        self._log(f"Leaving fastboot mode into {where}...")

        def done(status, result):
            if status == "error":
                self._log(f"Could not leave fastboot mode: {result}")
                messagebox.showerror("Restart phone", str(result))

        self._run(lambda: fastboot.reboot(serial, mode), done, f"Restarting the phone into {where}...")

    # ================================================================ menu
    def _sign_out(self):
        folder = Path.home() / ".miunlocksession"
        if not messagebox.askyesno(
                "Sign out", f"This deletes the saved session folder:\n\n{folder}\n\nIt does not end the session "
                "on Xiaomi's side. Check your signed-in devices on your Mi Account afterwards.\n\nDelete it?",
                default="no"):
            return
        store.delete_all()
        self.token = self.zone = self.eligibility = None
        self.r1.configure(text="Signed out. Saved session deleted.", foreground=MUTED)
        self._show_check("", "", "", MUTED)
        self._log("Saved session deleted.")
        self._refresh()

    def _stop_google_adb(self):
        if not messagebox.askyesno(
                "Stop Google's adb", "Google's adb server is running and holding the phone, so miunlock can't "
                "use it.\n\nStop it now? It starts again by itself the next time you use adb."):
            return

        def done(status, result):
            self._log("Stopped Google's adb server." if status == "ok" and result else f"adb: {result}")
            self._info.clear()
            self._scan()

        self._run(usbio.stop_google_adb, done, "Stopping Google's adb...")

    def _driver_help(self):
        DriverHelpDialog(self)

    def _show_log(self):
        path = log.log_path()
        if path is None:
            messagebox.showinfo("Log file", "Logging to a file is off: the program's folder is not writable.")
        elif messagebox.askyesno("Log file", f"The log is saved here:\n\n{path}\n\nIt never contains tokens. "
                                             "Open its folder?"):
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["explorer", "/select,", str(path)], creationflags=NO_WINDOW)
                else:
                    webbrowser.open(path.parent.as_uri())
            except Exception as err:
                self._log(f"Could not open the folder: {err}")

    # ============================================================= windows
    def _android_serial(self) -> Optional[str]:
        a = self.android
        return a["serial"] if a and a.get("state") == "device" else None

    def _backup_dialog(self):
        if self._android_serial():
            BackupDialog(self, self._android_serial(), self.android.get("model") or "")

    def security_result(self, serial: str, verdict: str) -> None:
        """Remember the last security check and colour its button: green all clear, amber review,
        red needs attention. A mark in the label says the same in words, so colour isn't alone."""
        self._security[serial] = verdict
        self._paint_security_button()

    def _quick_audit(self, serial: str, info: dict) -> None:
        """On a worker thread: the quick, local security look at a phone that has just been read. It sets
        the button's colour; a full check, when there is one, takes over."""
        try:
            setting = adb.Phone(serial).shell("settings get global package_verifier_enable", 8000)
            verdict = security.passive(info, setting).verdict
        except Exception as err:
            log.get("gui").debug("Quick security check failed: %s", err)
            return
        if self._passive.get(serial) != verdict:
            self._passive[serial] = verdict
            self.q.put(("call", self._paint_security_button, ()))

    def _paint_security_button(self) -> None:
        serial = self._android_serial() or ""
        verdict = self._security.get(serial) or self._passive.get(serial, "")
        kind, mark = {"Needs attention": ("danger", " ⚠"), "Some things to review": ("warn", " !")}.get(
            verdict, ("good", " ✔") if verdict else ("normal", ""))
        self.security_btn.configure(text="Security check..." + mark, kind=kind)
        self.buttons.relayout()

    def _security_dialog(self):
        if self._android_serial():
            SecurityDialog(self, self._android_serial())

    def _live_dialog(self):
        if not self._android_serial():
            return
        if self._live is not None and self._live.alive():
            self._live.focus()
        else:
            from miunlock.ui.live_dialog import LiveStatusDialog  # loads Pillow and the charts: not at start-up
            self._live = LiveStatusDialog(self, self._android_serial(), self._phone_name(self.android or {}))

    def _apps_dialog(self):
        if self._android_serial():
            AppManagerDialog(self, self._android_serial())

    def _open_guide(self):
        if self._guide is not None and self._guide.alive():
            self._guide.focus()
        else:
            self._guide = GuideWindow(self)

    def _about(self):
        from miunlock.ui.about_dialog import AboutDialog
        if getattr(self, "_about_win", None) is not None and self._about_win.alive():
            self._about_win.focus()
        else:
            self._about_win = AboutDialog(self)


def _enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main():
    log.setup(True if "--debug" in sys.argv[1:] else None)
    watchdog.install_crash_logging()          # background-thread errors and hard crashes go to the log file
    _enable_dpi_awareness()
    root = tk.Tk()
    app = App(root)
    guard = watchdog.UiWatchdog(root, on_stall=app.window_stalled)
    guard.start()                              # records what froze, if the window ever stops answering
    tidy = memory.Housekeeper(root, release=[app.release_memory])
    tidy.start()                               # garbage collection and a memory limit, for long sessions
    # Route anything the library prints into the Activity log (and keep printing safe when
    # there is no console, as in the windowed Windows build).
    stream = _LogStream(app._log)
    saved = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = stream
    try:
        root.mainloop()
    except Exception as err:  # last line of defence: say what happened instead of vanishing
        log.get("gui").exception("The window stopped with an unexpected error")
        sys.stdout, sys.stderr = saved
        try:
            messagebox.showerror("miunlock", f"miunlock hit an unexpected problem and has to close.\n\n{err}\n\n"
                                             f"Details were saved to {log.log_path()}.")
        except tk.TclError:
            pass
    finally:
        guard.stop()
        tidy.stop()
        sys.stdout, sys.stderr = saved


if __name__ == "__main__":
    main()
