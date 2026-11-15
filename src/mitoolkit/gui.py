"""
Tkinter GUI for mitoolkit: one plain window with the system's native look.

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
import logging
import queue
import sys
import threading
import time
from collections import deque
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional

from mitoolkit import (adb, adb_server, api, build, details, export, fastboot, log, memory, platform_tools, security,
                       shutdown, updater, usbio, watchdog)
from mitoolkit.adb_core import is_wireless
from mitoolkit.auth import store
from mitoolkit.auth.redact import mask_id
from mitoolkit.errors import MitoolkitError
from mitoolkit.hints import explain
from mitoolkit.ui.activity_window import ActivityLog, ActivityWindow
from mitoolkit.ui.apps_dialog import AppManagerDialog
from mitoolkit.ui.backup_dialog import BackupDialog
from mitoolkit.ui.base import fit_to_screen
from mitoolkit.ui.components.button_row import ButtonRow
from mitoolkit.ui.components.buttons import Button, ModernButton
from mitoolkit.ui.components.mode_switch import ModeSwitch
from mitoolkit.ui.driver_dialog import DriverHelpDialog
from mitoolkit.ui.guide_window import GuideWindow
from mitoolkit.ui.menu import MenuBar
from mitoolkit.ui.components.details_view import DetailsView
from mitoolkit.ui.components.scroll_page import ScrollPage
from mitoolkit.ui.components.shapes import page_background
from mitoolkit.ui.components.skeleton import Skeleton
from mitoolkit.ui.security_dialog import SecurityDialog
from mitoolkit.ui.theme import (AMBER, GREEN, MUTED, ORANGE_DOT, RED, Fonts, apply_theme, scale_fonts)


POLL_MS = 1000           # how often the window looks for the phone: an unplugged phone shows within a second
WIFI_PROBE_S = 12       # in Wireless mode: how often the network is searched for phones
AGENT_CONNECTED_S = 120  # the status bar says an AI agent is connected for this long after it last used a tool
AGENT_DOING = {"list_devices": "looking for phones", "reboot_to_fastboot": "restarting the phone into fastboot mode",
               "login": "signing in", "check_eligibility": "checking eligibility with Xiaomi",
               "security_check": "running the security check", "device_details": "reading the phone's details",
               "connections": "reading the phone's connections", "doctor": "checking the setup",
               "read_log": "reading the log", "version": "reading the version"}
AGENT_DONE = {"list_devices": "looking for phones", "reboot_to_fastboot": "restarting the phone",
              "login": "signing in", "check_eligibility": "checking eligibility", "security_check": "the security check",
              "device_details": "reading the details", "connections": "reading the connections",
              "doctor": "checking the setup", "read_log": "reading the log", "version": "reading the version"}
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
        root.title(f"MiToolkit {build.full_version()}")
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
        self._link_mode = "usb"                 # "usb" or "wifi" (a plain copy of link_var that threads may read)
        self._wifi_found: Optional[dict] = None    # a phone seen on the network that is not paired yet
        self._wifi_probing = False
        self._wifi_probe_at = 0.0
        self._fb_links: dict = {}               # fastboot serial -> how it is plugged in (for the footer)
        self._agent = None                      # the MCP server for AI agents, while it is on (see mcp_http.py)
        self._agent_win = None
        self._agent_calls: deque = deque(maxlen=20)       # (time, tool) of what agents used, newest last
        self._agent_last = -1e9                           # when an agent last connected or used a tool (monotonic seconds)
        self._agent_asking = False                        # an agent is waiting for the person to answer a question
        self._agent_active = 0                            # tools an agent is running now
        self._shown_layout = None               # what the Phone section holds now (see _render_status)
        self._info_names: tuple = ()            # the labels of the details grid, and its value cells
        self._info_cells: list = []
        self._more_icon = ""
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
        from mitoolkit.ui.components import render
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
        self.link_info = ttk.Label(bar, text="", foreground=MUTED)     # how the phone is connected: its USB port or Wi-Fi address
        self.link_info.pack(side="right", padx=(12, 0))
        # Left of it, while the AI agent connection is on (MCP in the app): a dot and the agent's name. Green when an
        # agent is connected, amber while it waits for the person's answer, grey while the connection just waits.
        self.agent_box = ttk.Frame(bar)
        self.agent_dot = tk.Canvas(self.agent_box, width=10, height=10, highlightthickness=0, borderwidth=0,
                                   bg=page_background(bar))
        self.agent_dot.pack(side="left", padx=(0, 5))
        self._agent_dot_item = self.agent_dot.create_oval(1, 1, 9, 9, fill=MUTED, outline="")
        self.agent_info = ttk.Label(self.agent_box, text="", foreground=MUTED)
        self.agent_info.pack(side="left")

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
        self._wrap(page, "Unlocking erases all data on the phone and can't be undone. Step 2 has a Back Up Files "
                         "button: use it first.", foreground=MUTED).pack(anchor="w", pady=(0, 10))

        # 1. Mi Account
        self.f1 = self._section(page, "1. Mi Account")
        self.f1_note = self._wrap(self.f1, "Opens Xiaomi's own login page. Your password is never entered here.",
                                  foreground=MUTED)
        self.f1_note.pack(anchor="w")
        self.f1_row = ttk.Frame(self.f1)
        self.f1_row.pack(fill="x", pady=(8, 0))
        self.login_btn = Button(self.f1_row, text="Sign In", icon="user", command=self._login)
        self.login_btn.pack(side="left")
        self.r1 = self._wrap(self.f1_row, "", foreground=MUTED)
        self.r1.pack(side="left", padx=10)
        self.signout_btn = Button(self.f1_row, text="Sign Out", command=self._sign_out)   # shown once signed in

        # 2. Phone
        self.f2 = self._section(page, "2. Phone")
        head = ttk.Frame(self.f2)
        head.pack(fill="x")
        # The row is one line, everything centred on it: the phone's name on the left; on the right the tools as quiet
        # icon buttons (their names show as tooltips), and between them how the phone is reached.
        self.rescan_btn = Button(head, text="Rescan", icon="refresh", kind="quiet", compact=True, command=self._rescan)
        self.rescan_btn.pack(side="right")
        # How the phone is reached: a cable (the default) or Wi-Fi. Wireless mode looks for phones on the network.
        self.link_var = tk.StringVar(value="usb")
        self.link = ModeSwitch(head, self.link_var, ("usb", "USB"), ("wifi", "Wi-Fi"), command=self._link_changed)
        self.link.pack(side="right", padx=(10, 6))
        self.dev_dot = tk.Label(head, text="\u25cf", fg=MUTED, bg=self.bg, font=self.f_base)
        self.dev_dot.pack(side="left")
        self.dev_text = ttk.Label(head, text="Looking for a phone", font=self.f_bold, justify="left")
        self.dev_text.pack(side="left", padx=6, fill="x")
        self.dev_detail = self._wrap(self.f2, "", foreground=MUTED)
        self.dev_detail.pack(anchor="w", padx=(22, 0), pady=(2, 0))
        # One aligned row of equal-width buttons: the main action first (bold), then the tools
        # that work while the phone runs Android.
        self.buttons = ButtonRow(self.f2)
        self.stop_adb_btn = Button(self.buttons, text="Stop Google's ADB", primary=True, command=self._stop_google_adb)
        self.driver_btn = Button(self.buttons, text="Driver Help", primary=True, command=self._driver_help)
        self.leave_btn = Button(self.buttons, text="Restart Phone", icon="power", command=self._restart_dialog)
        self.wifi_btn = Button(self.buttons, text="Pair or Connect", primary=True, icon="wifi",
                               command=self._wireless_dialog)
        self.fb_btn = Button(self.buttons, text="Reboot to Fastboot", primary=True, icon="power", command=self._to_fastboot)
        self.tool_btns = [Button(self.buttons, text=text, icon=icon, command=cmd) for text, icon, cmd in (
            ("Back Up Files", "save", self._backup_dialog), ("Manage Apps", "apps", self._apps_dialog),
            ("Security Check", "shield", self._security_dialog), ("Live Status", "chart", self._live_dialog),
            ("Connections", "wifi", self._connect_dialog))]
        self.security_btn = self.tool_btns[2]       # takes the colour of the last security check
        self._security: dict = {}                    # serial -> verdict of the last full check
        self._passive: dict = {}                     # serial -> verdict of the quick check made on connecting
        self.dev_tip = self._wrap(self.f2, "", foreground=AMBER)
        self.details = ttk.Frame(self.f2)
        self.info_box = ttk.Frame(self.details)
        self.info_box.pack(fill="x")
        self.more_box = ttk.Frame(self.details)  # "Show More": filled on demand
        # "Show More" is an expander bar (a flat, full-width row with a chevron), not a button
        self.more_btn = Button(self.details, text="Show More", icon="down", kind="flat", command=self._toggle_more)
        self.more_btn.pack(fill="x", pady=(8, 0))
        # Copy details sits at the top of the section, beside Rescan, while there are details to copy
        self.copy_btn = Button(head, text="Copy Details", icon="copy", kind="quiet", compact=True,
                               command=self._copy_device)
        self.export_btn = Button(head, text="Export Details", icon="save", kind="quiet", compact=True,
                                 command=self._export_device)

        # 3. Eligibility
        self.f3 = self._section(page, "3. Eligibility")
        row2 = ttk.Frame(self.f3)
        row2.pack(fill="x")
        self.check_btn = Button(row2, text="Check Eligibility", command=self._check)
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
        self.unlock_btn = Button(row3, text="Erase Phone and Unlock", icon="lock", kind="danger", command=self._unlock)
        self.unlock_btn.pack(side="left")
        self.reboot_btn = Button(row3, text="Restart Phone", command=self._reboot)
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
            except MitoolkitError as err:
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
            return "Step 1: Sign in to your Mi Account."
        state = self._state()
        if self.eligibility and self.eligibility.get("eligible"):
            return "Step 4: Confirm, then unlock."
        if state == "fastboot":
            return "Step 3: Check eligibility."
        if state == "device":
            return "Step 2: Restart the phone into fastboot mode."
        return "Step 2: Connect your phone."

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
            self._set_status("USB access is not ready yet; trying again.")
            self._prepare_fastboot()
            return
        if self.busy:
            self._set_status("Busy with another task; try again in a moment.")
            return
        if self._polling:
            if time.monotonic() - self._scan_started < 15:
                self._set_status("Already looking for the phone.")
                return
            self._polling = False                          # the last look took far too long: start over
            self._log("The last look took too long; looking again.")
        self._info.clear()                                 # read the phone's details afresh
        self._fbinfo.clear()
        self._wifi_probe_at = 0.0                          # and, in Wireless mode, search the network again now
        self._set_status("Looking for the phone")
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

    def _adb_devices(self, wifi: bool) -> list:
        """Phones adb sees, for the chosen way of connecting: the ones on a cable, or the ones on Wi-Fi (their
        serial is an address like 192.168.1.5:5555)."""
        if wifi and not adb_server.running():
            return []                    # the network search starts Google's adb; meanwhile do not claim a USB phone
        return [d for d in adb.devices() if is_wireless(d["serial"]) == wifi]

    def _wifi_candidate(self) -> dict:
        """What to show in Wireless mode when no phone is connected yet: it is looking, there is a phone that needs
        pairing, or Google's adb (which Wi-Fi needs) is not installed. Starts a network search when one is due."""
        if not platform_tools.find("adb"):
            return {"serial": "", "state": "wifi-no-adb"}
        now = time.monotonic()
        if not self._wifi_probing and now - self._wifi_probe_at >= WIFI_PROBE_S:
            self._wifi_probing, self._wifi_probe_at = True, now
            threading.Thread(target=self._probe_wifi, daemon=True, name="wifi-search").start()
        found = self._wifi_found
        if found:
            return {"serial": found["address"], "state": "wifi-pair", "model": found.get("name", "")}
        return {"serial": "", "state": "wifi-search"}

    def _probe_wifi(self) -> None:
        """Search the network for phones with Wireless debugging on, and connect to those that trust this computer."""
        try:
            results = adb_server.discover_and_connect()
            pairing = [r for r in results if r["state"] == "needs-pairing"]
            self._wifi_found = pairing[0] if pairing else None
            if any(r["state"] == "connected" for r in results):
                self._wifi_probe_at = 0.0                      # it is listed by the next look: no need to wait
        except Exception as err:
            log.get("gui").debug("Looking for phones on Wi-Fi failed: %s", err)
            self._wifi_found = None
        finally:
            self._wifi_probing = False

    def use_wireless(self) -> None:
        """A phone was just connected over Wi-Fi: switch to Wireless mode so it is listed (USB mode shows cable phones
        only). The windows that connected it ask for a rescan themselves."""
        if self._link_mode != "wifi":
            self.link_var.set("wifi")
            self._link_mode = "wifi"
            self._info.clear()

    def _cable_plugged_in(self) -> None:
        """A phone was plugged in while the selector said Wi-Fi and nothing answered there: switch to USB, where it is,
        instead of saying the phone is not answering. (Setting the variable does not run the selector's command, so
        this does not start another scan; the next regular one finds the phone.)"""
        if self._link_mode == "wifi":
            self.link_var.set("usb")
            self._link_mode = "usb"
            self._info.clear()
            self._log("The phone is plugged in with a USB cable: switched to USB.")

    def expect_wifi_phone(self) -> None:
        """A phone was just paired: search the network again at once and try it again even if it was refused a moment
        ago (it is trusted now). The Wi-Fi search connects it as soon as it announces itself."""
        self._wifi_found, self._wifi_probe_at = None, 0.0
        adb_server._tried.clear()

    def _link_changed(self) -> None:
        """USB / Wireless switch: look for phones the chosen way. Leaving Wireless stops the adb server MiToolkit
        started for it, so the cable path has the phone to itself."""
        mode = self.link_var.get()
        self._link_mode = mode
        self._wifi_found, self._wifi_probe_at = None, 0.0
        self._info.clear()
        self._log("Looking for phones on Wi-Fi." if mode == "wifi" else "Looking for phones on the cable (USB mode).")
        if mode == "usb":
            threading.Thread(target=adb_server.stop_started, daemon=True, name="adb-release").start()
        self._set_status("Looking for the phone")
        self._polling = False
        self._scan()

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
                    self._fb_links[serial] = usable[0].get("link") or "USB"
                elif found:  # in fastboot, but it cannot be opened
                    android = {"serial": found[0]["serial"], "state": "no-access", "mode": "fastboot",
                               "reason": found[0].get("reason")}
            except Exception:
                serial = None
            if serial is None and android is None:
                wifi = self._link_mode == "wifi"
                try:  # no phone in fastboot: is one running Android? (over the cable, or Wi-Fi in Wireless mode)
                    found = self._adb_devices(wifi)
                    if wifi and not any(d["state"] == "device" for d in found):
                        cable = [d for d in adb.devices() if not is_wireless(d["serial"]) and d["state"] == "device"]
                        if cable:       # plugged in while looking on Wi-Fi: the cable is the better link, use it
                            wifi, found = False, cable
                            self.call_soon(self._cable_plugged_in)
                    if not found and wifi:
                        android = self._wifi_candidate()
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
                    android = self._wifi_candidate() if wifi else None
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

    def _link_text(self) -> str:
        """The footer's right side: how the phone is connected. A cable phone shows its USB port (bus and port, like
        1-3), a Wi-Fi phone its address and port, a phone in fastboot its USB port and the mode."""
        if self.device:
            return f"{self._fb_links.get(self.device, 'USB')}, fastboot"
        return (self.android or {}).get("link", "")

    def _device_seen(self, serial: Optional[str], android: Optional[dict] = None, fb: Optional[dict] = None):
        if self.status.cget("text") == "Looking for the phone":   # a Rescan finished
            self._set_status("Ready.")
        if serial == self.device and android == self.android and fb == self.fb_info:
            return  # nothing changed: no redraw
        was_connected = self.device is not None
        log.get("gui").debug("Phone state changed: fastboot=%s android=%s", serial,
                             {k: (android or {}).get(k) for k in ("serial", "state", "model", "reason")})
        self.device, self.android, self.fb_info = serial, android, fb
        self.link_info.configure(text=self._link_text())
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
            if is_wireless(android.get("serial", "")):       # fastboot has no Wi-Fi: say so before the button is pressed
                return (ORANGE_DOT, f"{name} is on",
                        "Connected over Wi-Fi. To unlock, it must be in fastboot mode, which needs a USB cable: plug "
                        "the phone in and choose USB. Restarting into fastboot is safe and erases nothing.",
                        self.fb_btn)
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
        if state == "wifi-pair":
            return (ORANGE_DOT, "A phone with Wireless debugging is on this network",
                    "It has not been paired with this computer yet. Pair it once with a QR code or the code on "
                    "its Wireless debugging screen.", self.wifi_btn)
        if state == "wifi-search":
            return (MUTED, "Looking for phones on Wi-Fi",
                    "On the phone: Settings > Developer options > Wireless debugging, switched on, on the same "
                    "Wi-Fi as this computer. A new phone is paired once, with a QR code or a code.", self.wifi_btn)
        if state == "wifi-no-adb":
            return (AMBER, "Wireless needs Google's adb",
                    "Install Android's platform-tools (they provide adb), then click Rescan. USB works without it.", None)
        if state == "unauthorized":
            if is_wireless(str(android.get("serial", ""))):                # connected over Wi-Fi
                return (ORANGE_DOT, "Allow debugging on the phone",
                        "Unlock the phone, tap Allow and tick \"Always allow from this computer\". To skip this "
                        "prompt for good, pair it once in Phone > Wi-Fi connection.", None)
            return (ORANGE_DOT, "Allow USB debugging on the phone",
                    "Unlock the phone, tap Allow and tick \"Always allow from this computer\".", None)
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
        row = ([action] if action is not None else []) + (self.tool_btns if state == "device" else [])
        pairs = [(k, v) for k, v in self._device_pairs() if v not in (None, "")]
        self._show_info(pairs)                 # new readings change the text in place: nothing is torn down
        self._show_more()
        # The sections are laid out again only when what they hold changed (a different row of buttons, details
        # appearing or going). A refresh that only brings new readings must not flicker the window.
        layout = (tuple(id(b) for b in row), bool(pairs))
        if layout != self._shown_layout:
            self._shown_layout = layout
            for widget in (self.buttons, self.details):
                widget.pack_forget()
            self.buttons.set(row)
            if row:
                self.buttons.pack(fill="x", padx=(22, 0), pady=(10, 0))
            self.copy_btn.pack_forget()
            self.export_btn.pack_forget()
            if pairs:
                self.details.pack(fill="x", padx=(22, 0), pady=(10, 0))
                self.export_btn.pack(side="right")           # left of the selector: Copy, Export, then USB | Wi-Fi
                self.copy_btn.pack(side="right")
        self._paint_security_button()          # a different phone may have a different last result

    def _show_info(self, pairs) -> None:
        """The details grid. With the same rows as before only the values that changed are rewritten, in place (a
        refresh every few seconds must not rebuild the grid: that flickers and moves the page)."""
        names = tuple(label for label, _value in pairs)
        if names == self._info_names and self._info_cells:
            for cell, (_label, value) in zip(self._info_cells, pairs):
                if cell.cget("text") != str(value):
                    cell.configure(text=str(value))
            return
        for child in self.info_box.winfo_children():
            child.destroy()
        self._info_names, self._info_cells = names, []
        half = (len(pairs) + 1) // 2
        for col in (1, 3):
            self.info_box.columnconfigure(col, weight=1)
        for i, (label, value) in enumerate(pairs):
            row, col = i % half, (i // half) * 2
            ttk.Label(self.info_box, text=label, foreground=MUTED).grid(
                row=row, column=col, sticky="w", padx=(0 if col == 0 else 24, 12), pady=1)
            cell = ttk.Label(self.info_box, text=str(value))
            cell.grid(row=row, column=col + 1, sticky="w", pady=1)
            self._info_cells.append(cell)

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
                # the phone's own serial; over Wi-Fi the connection's name is an address, which is shown as its own row
                ("Serial", android.get("serialno") or (None if is_wireless(android["serial"]) else android["serial"])),
                ("Wi-Fi address", android["serial"] if is_wireless(android["serial"]) else None),
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
        text, icon, state = ("Show Less" if self._more_open else "Show More", "up" if self._more_open else "down",
                             "normal" if key else "disabled")
        if (self.more_btn.cget("text"), self.more_btn.cget("state")) != (text, state) or self._more_icon != icon:
            self._more_icon = icon                         # only when it changed: a refresh must not repaint it
            self.more_btn.configure(text=text, icon=icon, state=state)
        if not (self._more_open and key):
            if self.more_box.winfo_manager():              # only when it is showing: no refit on every refresh
                self.more_box.pack_forget()
                self.page.refit()                          # no blank gap or stale pixels where the rows were
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
        built = (key, repr(self._more[key]))           # by content: re-reading the same values changes nothing
        if self._more_built != built:                  # new phone or new readings: build the rows once
            self._build_more(key)
            self._more_built = built
        if not self.more_box.winfo_manager():
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
        self._log("Reading all details from the phone (read-only).")

        def work():
            return adb.more_details(serial) if mode == "android" else details.fastboot_details(serial)

        def done(status, result):
            if status == "error":
                self._more_open = False
                self._log(f"Could not read more details: {result}")
                messagebox.showerror("Show More", str(result))
            else:
                self._more[key] = result
            self._show_more()

        self._run(work, done, "Reading details from the phone")

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
        from mitoolkit.ui.wireless_dialog import WirelessDialog   # not needed until first opened
        if getattr(self, "_wireless", None) is not None and self._wireless.alive():
            self._wireless.focus()
        else:
            self._wireless = WirelessDialog(self)

    # ------------------------------------------------------------------------------- AI agents (MCP in the app)
    def _agent_dialog(self) -> None:
        from mitoolkit.ui.agent_dialog import AgentDialog
        if self._agent_win is not None and self._agent_win.alive():
            self._agent_win.focus()
        else:
            self._agent_win = AgentDialog(self)

    def agent_start(self):
        """Let an AI agent connect to this window (see mcp_http.py). Returns the server; a second call returns the same."""
        from mitoolkit import mcp_http                       # not loaded until an agent is allowed in
        if self._agent is None:
            self._agent = mcp_http.McpHttpServer(approve=self._agent_approve, on_call=self._agent_called,
                                                 on_client=self._agent_met, on_done=self._agent_done).start()
            self._log("AI agent connection is on. Agents can read and check; unlocking is not offered to them.")
            self._agent_tick()
        return self._agent

    def agent_stop(self) -> None:
        if self._agent is not None:
            server, self._agent = self._agent, None
            server.stop()
            self._log("AI agent connection is off.")
        self._agent_status()

    def _agent_called(self, tool: str) -> None:
        """An agent used a tool (called on the server's thread): the Activity log and the window's list say which."""
        self._agent_calls.append((time.strftime("%H:%M:%S"), tool))
        self._agent_last = time.monotonic()
        self._log(f"{self._agent_name()} used {tool}.")
        self.call_soon(self._agent_working, tool, True)

    def _agent_working(self, tool: str, start: bool, data=None, failed: bool = False) -> None:
        """The window follows what an agent does (UI thread). When it starts a tool the status bar says what it is
        doing, with the progress bar; when it finishes the window shows the result the way it would for the person:
        a new look at the phone, the Security Check colour, the eligibility answer."""
        self._agent_status()
        who = self._agent_name()
        if start:
            self._agent_active += 1
            if not self.busy:
                self.progress.pack(side="right", padx=10)
                self.progress.start(12)
                self._set_status(f"{who} is {AGENT_DOING.get(tool, 'using ' + tool)}")
            return
        self._agent_active = max(0, self._agent_active - 1)
        if not self._agent_active and not self.busy:
            self.progress.stop()
            self.progress.pack_forget()
            self._set_status(f"{who} finished {AGENT_DONE.get(tool, tool)}." if not failed
                             else f"{who}'s request did not go through.")
        if failed or not isinstance(data, dict):
            return
        if tool in ("list_devices", "reboot_to_fastboot"):
            self._info.clear()                               # look at the phone again at once, as Rescan does
            if not self.busy and not self._polling:
                self._scan()
        elif tool == "security_check" and data.get("verdict") and self._android_serial():
            self.security_result(self._android_serial(), str(data["verdict"]))
        # Eligibility is deliberately not copied into step 3: the unlock step uses Xiaomi's answer with fields an agent never
        # receives, and unlocking is a person's decision. The person presses Check Eligibility to see it themselves.

    def _agent_done(self, tool: str, data, failed: bool) -> None:
        """An agent's tool finished (called on the server's thread)."""
        self.call_soon(self._agent_working, tool, False, data, failed)

    def _agent_met(self, name: str) -> None:
        """An agent said who it is when it connected (called on the server's thread)."""
        self._agent_last = time.monotonic()
        self._log(f"{name or 'An AI agent'} connected.")
        self.call_soon(self._agent_status)

    def _agent_name(self) -> str:
        return (self._agent.client if self._agent is not None else "") or "An AI agent"

    def _agent_status(self) -> None:
        """The right of the status bar: nothing while the connection is off; while it is on, a dot and words. Green and
        the agent's name for a couple of minutes after it connected or last used a tool, amber while it waits for
        the person's answer, grey ("on") while no agent is using it."""
        try:
            if self._agent is None:
                self._agent_asking = False
                self.agent_box.pack_forget()
                self.agent_info.configure(text="")
                return
            name = (self._agent.client or "AI agent")
            if self._agent_asking:
                text, colour = f"{name} is waiting for your answer", AMBER
            elif time.monotonic() - self._agent_last < AGENT_CONNECTED_S:
                text, colour = f"{name} connected", GREEN
            else:
                text, colour = "AI agent connection on", MUTED
            self.agent_info.configure(text=text, foreground=colour)
            self.agent_dot.itemconfigure(self._agent_dot_item, fill=colour)
            if not self.agent_box.winfo_manager():
                self.agent_box.pack(side="right", padx=(12, 0))      # packed after the link text: left of it
        except tk.TclError:
            pass                                             # the window is closing

    def _agent_tick(self) -> None:
        """While the connection is on, let "connected" fade back to "on" when the agent goes quiet."""
        self._agent_status()
        if self._agent is not None:
            self.root.after(5000, self._agent_tick)

    def _agent_approve(self, tool: str, arguments: dict) -> bool:
        """An agent asks for something that changes the phone or uses the saved sign-in: ask the person, in the window,
        and wait for the answer (one minute at most; no answer is a no). Called on the server's thread."""
        from mitoolkit import mcp_http
        what = mcp_http.APPROVAL.get(tool, tool)
        who = self._agent_name()
        answer: list = []
        done = threading.Event()

        def ask() -> None:
            self.root.deiconify()
            self.root.lift()
            try:
                answer.append(messagebox.askyesno("AI agent request", f"{who} wants to {what}.\n\nAllow it?",
                                                  icon="question", default="no", parent=self.root))
            finally:
                self._agent_asking = False
                self._agent_status()
                done.set()
        self._agent_asking = True                            # the status bar turns amber until the person answers
        self.call_soon(self._agent_status)
        self.call_soon(ask)
        allowed = done.wait(60) and bool(answer and answer[0])
        self._agent_asking = False
        return allowed

    def _to_fastboot(self):
        serial = (self.android or {}).get("serial")
        if not serial:
            return
        if is_wireless(serial):                            # connected over Wi-Fi
            messagebox.showinfo(
                "Connect the USB cable", "This phone is connected over Wi-Fi, and fastboot mode works over a USB "
                "cable only.\n\nPlug the phone into this computer with a USB cable, then choose this again.")
            self._log("Fastboot needs a USB cable: this phone is connected over Wi-Fi.")
            return
        self._log("Asking the phone to reboot into fastboot mode (nothing is erased).")

        def work():
            adb.reboot_to_bootloader(serial)
            self._info.pop(serial, None)

        def done(status, result):
            if status == "error":
                self._log(f"Could not reboot to fastboot: {result}")
                messagebox.showerror("Reboot to Fastboot", str(result))

        self._run(work, done, "Rebooting the phone into fastboot mode")

    def _restart_dialog(self) -> None:
        """Restart or power off: pick the mode in one place (works in Android and in fastboot mode)."""
        if not (self._android_serial() or self.device):
            return
        from mitoolkit.ui.restart_dialog import RestartDialog
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
                "Restart Phone", f"Restart the phone into {where}?\n\nNothing is erased. Unsaved work on the "
                "phone is lost.", default="no"):
            return
        self._log(f"Restarting the phone into {where} (nothing is erased).")

        def work():
            adb.reboot(mode, serial)
            self._info.pop(serial, None)

        def done(status, result):
            if status == "error":
                self._log(f"Could not restart: {result}")
                messagebox.showerror("Restart Phone", str(result))

        self._run(work, done, f"Restarting the phone into {where}")

    def _power_off(self, confirm: bool = True) -> None:
        serial = self._android_serial()
        if not serial or (confirm and not messagebox.askyesno(
                "Power Off", "Shut the phone down?\n\nIt stays off until you press its power button.", default="no")):
            return
        self._log("Powering the phone off")

        def work():
            adb.power_off(serial)
            self._info.pop(serial, None)

        def done(status, result):
            if status == "error":
                self._log(f"Could not power off: {result}")
                messagebox.showerror("Power Off", str(result))

        self._run(work, done, "Powering the phone off")

    def _connect_dialog(self) -> None:
        if not self._android_serial():
            return
        from mitoolkit.ui.connect_dialog import ConnectionsDialog  # not needed until first opened
        if getattr(self, "_connections", None) is not None and self._connections.alive():
            self._connections.focus()
        else:
            self._connections = ConnectionsDialog(self, self._android_serial(), self._phone_name(self.android or {}))

    def _log_dialog(self) -> None:
        if not self._android_serial():
            return
        from mitoolkit.ui.log_dialog import LogDialog  # not needed until first opened
        if getattr(self, "_logview", None) is not None and self._logview.alive():
            self._logview.focus()
        else:
            self._logview = LogDialog(self, self._android_serial(), self._phone_name(self.android or {}))

    # =============================================================== step 1
    def _login(self):
        self._log("Signing in.")
        self.r1.configure(text="Finish signing in in your browser.")

        def work():
            token = api.login(login_method="1", silent_if_cached=True)
            return token, api.get_account_zone(token)

        self._run(work, self._login_done, "Waiting for sign-in in your browser")

    def _login_done(self, status: str, result):
        if status == "error":
            self.r1.configure(text=f"Sign-in didn't finish: {result}", foreground=RED)
            self._log(f"Sign-in failed: {result}")
            return
        self.token, self.zone = result
        who = mask_id(self.token["userId"])  # masked so screenshots don't expose the account ID
        self.r1.configure(text=f"Account {who}, data center: {self.zone}", foreground=MUTED)
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
        self._log("Checking eligibility with Xiaomi")
        self._run(lambda: api.check_unlock_eligibility(self.token, self.zone), self._check_done,
                  "Asking Xiaomi if this phone can be unlocked")

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
            body = (f"Phone: {result['product']}, data center: {result['zone']}\n"
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
        self._log("Unlocking. Do not unplug the phone.")
        elig = self.eligibility
        self._run(lambda: api.perform_unlock(self.token, elig, confirm_wipe=True),
                  self._unlock_done, "Unlocking. Keep the phone connected")

    def _unlock_done(self, status: str, result):
        if status == "error":
            self._set_r3(f"The unlock did not complete: {result}", RED)
            self._log(f"Unlock failed: {result}")
            return
        self.unlocked = True
        self._fbinfo.clear()
        self._set_r3("Bootloader unlocked. The phone is resetting; the first start can take several "
                     "minutes. If it stays on the fastboot screen, use Restart Phone.", GREEN)
        self._log(f"Unlock finished: {result}")
        self.reboot_btn.pack(side="left", padx=10)
        self._refresh()

    def _reboot(self, mode: str = ""):
        """Leave fastboot mode: into Android (mode "") or recovery ("recovery"). Erases nothing."""
        if not self.fastboot or not self.device:
            return
        serial, where = self.device, "recovery mode" if mode == "recovery" else "Android"
        self._log(f"Leaving fastboot mode into {where}.")

        def done(status, result):
            if status == "error":
                self._log(f"Could not leave fastboot mode: {result}")
                messagebox.showerror("Restart Phone", str(result))

        self._run(lambda: fastboot.reboot(serial, mode), done, f"Restarting the phone into {where}")

    # ================================================================ menu
    def _sign_out(self):
        folder = Path.home() / ".mitoolkitsession"
        if not messagebox.askyesno(
                "Sign Out", f"This deletes the saved session folder:\n\n{folder}\n\nIt does not end the session "
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
                "Stop Google's ADB", "Google's adb server is running and holding the phone, so MiToolkit can't "
                "use it.\n\nStop it now? It starts again by itself the next time you use adb. If it was started "
                "with administrator rights, the system asks for your permission first."):
            return

        def done(status, result):
            self._log(f"{result}" if status == "ok" else f"Could not stop Google's adb: {result}")
            self._info.clear()
            self._scan()

        from mitoolkit import doctor
        self._run(lambda: doctor.with_admin("stop-adb"), done, "Stopping Google's adb")

    def _driver_help(self):
        DriverHelpDialog(self)

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
        self.security_btn.configure(text="Security Check" + mark, kind=kind)
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
            from mitoolkit.ui.live_dialog import LiveStatusDialog  # loads Pillow and the charts: not at start-up
            self._live = LiveStatusDialog(self, self._android_serial(), self._phone_name(self.android or {}))

    def _apps_dialog(self):
        if self._android_serial():
            AppManagerDialog(self, self._android_serial())

    def _open_guide(self):
        if self._guide is not None and self._guide.alive():
            self._guide.focus()
        else:
            self._guide = GuideWindow(self)

    def _doctor_dialog(self) -> None:
        from mitoolkit.ui.doctor_dialog import DoctorDialog
        if getattr(self, "_doctor", None) is not None and self._doctor.alive():
            self._doctor.focus()
        else:
            self._doctor = DoctorDialog(self)

    def start_self_check(self) -> None:
        """At start-up, quietly: repair what is safe to repair (permissions on private files, a damaged settings
        file, files left by an update) and say so in the Activity log. Nothing that needs a decision runs here."""
        from mitoolkit import doctor

        def work():
            try:
                for message in doctor.auto_fix():
                    self._log(f"Fixed automatically: {message}")
            except Exception as err:
                log.get("gui").debug("Start-up self check failed: %s", err)

        threading.Thread(target=work, daemon=True, name="self-check").start()

    def _update_dialog(self, release=None) -> None:
        from mitoolkit.ui.update_dialog import UpdateDialog
        if getattr(self, "_updates", None) is not None and self._updates.alive():
            self._updates.focus()
        else:
            self._updates = UpdateDialog(self, release or getattr(self, "_found_release", None))

    def start_update_check(self) -> None:
        """Once a day, quietly: look for a newer release. If there is one, say so in the status line (the
        Check for updates window has the details). A failure says nothing. Turn it off in the Help menu."""
        if not updater.check_due():
            return

        def work():
            try:
                release = updater.latest()
            except Exception as err:
                log.get("gui").debug("Update check failed: %s", err)
                return
            updater.mark_checked()
            if updater.is_newer(release):
                self.q.put(("call", self._update_available, (release,)))

        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _update_available(self, release) -> None:
        self._found_release = release
        self._log(f"Update available: {release.tag} (Help > Check for updates).")
        self._set_status(f"Update available: {release.tag}. Help > Check for updates.")

    def _about(self):
        from mitoolkit.ui.about_dialog import AboutDialog
        if getattr(self, "_about_win", None) is not None and self._about_win.alive():
            self._about_win.focus()
        else:
            self._about_win = AboutDialog(self)


class ActivityHandler(logging.Handler):
    """Warnings and errors that are written to the log file also show in the Activity log, so there is one place to
    look in the app. The same scrubbing as the file applies: tokens are hidden before anything is shown."""

    def __init__(self, add: Callable[[str], None]):
        super().__init__(level=logging.WARNING)
        self._add = add
        self.addFilter(log.Scrubber())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._add(f"{record.levelname.title()}: {record.getMessage()}")
        except Exception:
            self.handleError(record)


def _enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            # an older Windows without this call: the window is then scaled by the system, which is fine
            pass


def main():
    log.setup(True if "--debug" in sys.argv[1:] else None)
    shutdown.register()                       # also at exit, if the window is not closed in the usual way
    watchdog.install_crash_logging()          # background-thread errors and hard crashes go to the log file
    _enable_dpi_awareness()
    root = tk.Tk()
    app = App(root)
    activity = ActivityHandler(app._log)       # warnings and errors from the log file show in the Activity log too
    log.get().addHandler(activity)
    updater.cleanup()                          # remove the copy a previous update left behind
    root.after(1500, app.start_self_check)     # repairs what is safe to repair, and says so in the Activity log
    root.after(4000, app.start_update_check)   # once a day, after the window is up
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
            messagebox.showerror("MiToolkit", f"MiToolkit hit an unexpected problem and has to close.\n\n{err}\n\n"
                                              f"Details were saved to {log.log_path()}.")
        except tk.TclError:
            # the window system itself is gone: the error is already in the log file
            pass
    finally:
        guard.stop()
        tidy.stop()
        log.get().removeHandler(activity)
        sys.stdout, sys.stderr = saved
        shutdown.run()                         # the window is closed: let go of the phones, stop the adb we started


if __name__ == "__main__":
    main()
