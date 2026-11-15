"""
Tkinter GUI for miunlock. Ships with Python, so there is no extra dependency.

Three steps, top to bottom: sign in, connect the phone and check eligibility,
unlock. Each step is only usable once the one before it is done, and the screen
always says what it is waiting for.

The one destructive action, the unlock itself, needs two deliberate acts: tick a
box saying the data is backed up, and type the phone's name. Only then does the
button come alive, and only that button sets confirm_wipe=True. See api.py for why
the confirmation is never defaulted or inferred.
"""
from __future__ import annotations

import ctypes
import io
import datetime
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from miunlock import __version__, adb, api, bloat, drivers, fastboot, guide, log, usbio
from miunlock.auth import store
from miunlock.auth.redact import mask_id
from miunlock.hints import explain
from miunlock.system import NO_WINDOW

REPO = "https://github.com/jowinjohnchemban/miunlock"
DOCS = REPO + "/blob/main/docs/"

GREEN = "#1a7f37"
RED = "#b3261e"
AMBER = "#9a5b00"
MUTED = "#5f6368"
ORANGE_DOT = "#e8710a"
ACCENT = "#e8590c"
WARN_BG = "#fff4ce"
WARN_FG = "#5c4400"
BORDER = "#d0d0d0"


class _LogStream(io.TextIOBase):
    """Collects what the library prints (login progress, fastboot output) so it can
    be shown under "Details". Also keeps printing safe in a windowed program, where
    there is no console and sys.stdout would otherwise be None."""

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
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"miunlock {__version__}")
        root.geometry("780x700")
        root.minsize(560, 420)
        try:
            icon = Path(__file__).parent / "assets" / "logo.png"
            self._icon = tk.PhotoImage(file=str(icon))  # keep a reference
            root.iconphoto(True, self._icon)
        except Exception:  # the logo is cosmetic; never fail because of it
            pass

        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.token: Optional[dict] = None
        self.zone: Optional[str] = None
        self.fastboot: Optional[str] = None
        self.device: Optional[str] = None  # serial of the connected fastboot device
        self.eligibility: Optional[dict] = None
        self.unlocked = False
        self.busy = False
        self._polling = False
        self.android: Optional[dict] = None  # phone seen by adb while running Android
        self._info: dict = {}
        self._fbinfo: dict = {}
        self._none_since: Optional[float] = time.time()  # when we last started seeing no phone
        self.fb_info: Optional[dict] = None
        self._wrap_labels: list[ttk.Label] = []

        self._style()
        self._menu()
        self._layout()
        self._refresh()

        root.after(100, self._pump)
        root.after(300, self._prepare_fastboot)

    # ------------------------------------------------------------------ look
    def _style(self):
        base = tkfont.nametofont("TkDefaultFont")
        self.f_base = base
        self.f_bold = base.copy()
        self.f_bold.configure(weight="bold")
        self.f_title = base.copy()
        self.f_title.configure(size=base.cget("size") + 8, weight="bold")
        self.f_small = base.copy()
        self.f_small.configure(size=max(base.cget("size") - 1, 8))

        s = ttk.Style()
        if "vista" in s.theme_names():
            s.theme_use("vista")
        elif "clam" in s.theme_names():
            s.theme_use("clam")
        s.configure("Card.TFrame", relief="solid", borderwidth=1)
        s.configure("Primary.TButton", padding=(14, 6), font=self.f_bold)
        s.configure("TButton", padding=(10, 5))

    def _menu(self):
        bar = tk.Menu(self.root)
        file_menu = tk.Menu(bar, tearoff=0)
        file_menu.add_command(label="Sign out and delete saved session...", command=self._sign_out)
        file_menu.add_command(label="Show log file", command=self._show_log)
        file_menu.add_separator()
        if drivers.supported():
            file_menu.add_command(label="Install Google USB driver...", command=self._install_driver)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.destroy)
        bar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(bar, tearoff=0)
        help_menu.add_command(label="Step-by-step guide (F1)", command=self._open_guide)
        help_menu.add_command(label="Full unlock guide (web)", command=lambda: webbrowser.open(DOCS + "unlock-guide.md"))
        help_menu.add_command(label="Safety model", command=lambda: webbrowser.open(DOCS + "safety.md"))
        help_menu.add_command(label="Error codes", command=lambda: webbrowser.open(DOCS + "error-codes.md"))
        help_menu.add_command(label="FAQ", command=lambda: webbrowser.open(DOCS + "faq.md"))
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self._about)
        bar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=bar)

    def _wrap(self, parent, text="", **kw) -> ttk.Label:
        lab = ttk.Label(parent, text=text, justify="left", wraplength=640, **kw)
        self._wrap_labels.append(lab)
        return lab

    def _card(self, parent, number: str, title: str):
        card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        card.pack(fill="x", pady=(0, 10))
        head = ttk.Frame(card)
        head.pack(fill="x")
        badge = tk.Label(head, text=number, bg=ACCENT, fg="white", font=self.f_bold, width=2)
        badge.pack(side="left")
        ttk.Label(head, text=title, font=self.f_bold).pack(side="left", padx=10)
        status = ttk.Label(head, text="", font=self.f_bold)
        status.pack(side="right")
        body = ttk.Frame(card)
        body.pack(fill="x", pady=(8, 0))
        return card, body, status, badge

    def _layout(self):
        shell = ttk.Frame(self.root, padding=(18, 14, 8, 10))
        shell.pack(fill="both", expand=True)

        # Status bar: packed first so it always keeps its space at the bottom.
        bottom = ttk.Frame(shell)
        bottom.pack(fill="x", side="bottom", pady=(6, 0))
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=120)
        self.status = ttk.Label(bottom, text="Ready.", foreground=MUTED)
        self.status.pack(side="left")
        self.details_open = False
        self.details_btn = ttk.Button(bottom, text="Show details", command=self._toggle_details)
        self.details_btn.pack(side="right")

        # Everything else scrolls, so nothing is cut off on a small or scaled screen.
        self.scroll_wrap = ttk.Frame(shell)
        self.scroll_wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.scroll_wrap, highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(self.scroll_wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scrolled)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        outer = ttk.Frame(self.canvas, padding=(0, 0, 12, 0))
        self._content = outer
        self._content_id = self.canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>", lambda _e: self._sync_scroll())
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.root.bind_all("<MouseWheel>", self._on_wheel)
        self.root.bind_all("<Button-4>", self._on_wheel)  # Linux
        self.root.bind_all("<Button-5>", self._on_wheel)
        self.root.bind("<Control-q>", lambda _e: self.root.destroy())
        self.root.bind("<F1>", lambda _e: self._open_guide())

        ttk.Label(outer, text="miunlock", font=self.f_title).pack(anchor="w")
        ttk.Label(
            outer,
            text="Unlock the bootloader of Xiaomi, Redmi and POCO phones",
            foreground=MUTED,
        ).pack(anchor="w", pady=(0, 10))

        banner = tk.Frame(outer, bg=WARN_BG, padx=12, pady=8)
        banner.pack(fill="x", pady=(0, 12))
        tk.Label(
            banner,
            text="Unlocking erases the phone's data and can't be undone. Back up first.",
            bg=WARN_BG, fg=WARN_FG, font=self.f_bold, anchor="w",
        ).pack(side="left")
        link = tk.Label(banner, text="Open the guide (F1)", bg=WARN_BG, fg=WARN_FG, cursor="hand2", font=self.f_base)
        link.configure(font=tkfont.Font(font=self.f_base, underline=True))
        link.pack(side="right")
        link.bind("<Button-1>", lambda _e: self._open_guide())

        # Step 1 ---------------------------------------------------------
        self.c1, b1, self.s1, self.n1 = self._card(outer, "1", "Sign in to your Mi Account")
        self.d1 = self._wrap(
            b1,
            "Your browser opens Xiaomi's own login page. Sign in there. "
            "Your password is never typed into this program.",
        )
        self.d1.pack(anchor="w")
        row = ttk.Frame(b1)
        row.pack(fill="x", pady=(10, 0))
        self.login_btn = ttk.Button(row, text="Sign in with browser", style="Primary.TButton", command=self._login)
        self.login_btn.pack(side="left")
        self.r1 = self._wrap(row, "", foreground=MUTED)
        self.r1.pack(side="left", padx=12)

        # Step 2 ---------------------------------------------------------
        self.c2, b2, self.s2, self.n2 = self._card(outer, "2", "Connect your phone and check")
        self.d2 = self._wrap(
            b2,
            "Power the phone off, hold Volume Down + Power until the fastboot screen appears, "
            "then connect it with a USB data cable.",
        )
        self.d2.pack(anchor="w")
        drow = ttk.Frame(b2)
        drow.pack(fill="x", pady=(8, 0))
        self.dev_dot = tk.Label(drow, text="●", fg=MUTED, font=self.f_base)
        self.dev_dot.pack(side="left")
        self.dev_text = ttk.Label(drow, text="Preparing fastboot...", foreground=MUTED)
        self.dev_text.pack(side="left", padx=6)
        self.fb_btn = ttk.Button(drow, text="Reboot to fastboot", command=self._to_fastboot)
        self.rescan_btn = ttk.Button(drow, text="Rescan", command=self._scan)
        self.rescan_btn.pack(side="right")
        self.copy_btn = ttk.Button(drow, text="Copy info", command=self._copy_device)
        self.backup_btn = ttk.Button(drow, text="Back up files...", command=self._backup_dialog)
        self.apps_btn = ttk.Button(drow, text="Manage apps...", command=self._apps_dialog)
        self.dev_tip = self._wrap(b2, "", foreground=AMBER, font=self.f_small)
        self.dev_tip.pack_forget()
        self.info_box = ttk.Frame(b2)  # device details, filled in when a phone is seen
        row2 = ttk.Frame(b2)
        self._row2 = row2
        row2.pack(fill="x", pady=(10, 0))
        self.check_btn = ttk.Button(row2, text="Check eligibility", style="Primary.TButton", command=self._check)
        self.check_btn.pack(side="left")
        self.r2_title = ttk.Label(b2, text="", font=self.f_bold)
        self.r2_body = self._wrap(b2, "")
        self.r2_raw = self._wrap(b2, "", foreground=MUTED, font=self.f_small)

        # Step 3 ---------------------------------------------------------
        self.c3, b3, self.s3, self.n3 = self._card(outer, "3", "Unlock")
        self.d3 = self._wrap(b3, "Available once Xiaomi says the phone is eligible.", foreground=MUTED)
        self.d3.pack(anchor="w")
        self.confirm_var = tk.BooleanVar(value=False)
        self.name_var = tk.StringVar()
        self.confirm_var.trace_add("write", lambda *_: self._refresh())
        self.name_var.trace_add("write", lambda *_: self._refresh())
        self.chk = ttk.Checkbutton(
            b3, text="I have backed up my data and understand it will be erased.", variable=self.confirm_var
        )
        self.chk.pack(anchor="w", pady=(10, 0))
        nrow = ttk.Frame(b3)
        nrow.pack(fill="x", pady=(8, 0))
        self.name_lbl = ttk.Label(nrow, text="Type the phone's name to confirm:")
        self.name_lbl.pack(side="left")
        self.name_entry = ttk.Entry(nrow, textvariable=self.name_var, width=18)
        self.name_entry.pack(side="left", padx=8)
        row3 = ttk.Frame(b3)
        row3.pack(fill="x", pady=(12, 0))
        self.unlock_btn = tk.Button(
            row3, text="Unlock bootloader", command=self._unlock,
            bg=RED, fg="white", activebackground="#8c1d18", activeforeground="white",
            relief="flat", padx=16, pady=7, font=self.f_bold, cursor="hand2",
            disabledforeground="#e6b8b5",
        )
        self.unlock_btn.pack(side="left")
        self.reboot_btn = ttk.Button(row3, text="Reboot phone", command=self._reboot)
        self.r3 = self._wrap(b3, "")

        self.details_frame = ttk.Frame(shell)
        tools = ttk.Frame(self.details_frame)
        tools.pack(side="bottom", fill="x", pady=(4, 0))
        ttk.Button(tools, text="Copy", command=self._copy_details).pack(side="right")
        ttk.Button(tools, text="Clear", command=self._clear_details).pack(side="right", padx=6)
        self.details = tk.Text(self.details_frame, height=9, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(self.details_frame, command=self.details.yview)
        self.details.configure(yscrollcommand=sb.set)
        self.details.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # --------------------------------------------------------------- helpers
    def _on_canvas_resize(self, event):
        self.canvas.itemconfigure(self._content_id, width=event.width)
        width = max(event.width - 120, 320)
        for lab in self._wrap_labels:
            lab.configure(wraplength=width)
        self._sync_scroll()

    def _sync_scroll(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_scrolled(self, first, last):
        """Show the scrollbar only when there is something to scroll to."""
        self.vbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.vbar.pack_forget()
        elif not self.vbar.winfo_ismapped():
            self.vbar.pack(side="right", fill="y", before=self.canvas)

    def _on_wheel(self, event):
        # Let the details box scroll itself; scroll the page everywhere else.
        if str(event.widget).startswith(str(self.details_frame)):
            return
        if self.vbar.winfo_ismapped():
            step = -1 if (getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0) else 1
            self.canvas.yview_scroll(step * 3, "units")

    def _copy_details(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.details.get("1.0", "end").strip())
        self._set_status("Details copied to the clipboard.")

    def _clear_details(self):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.configure(state="disabled")

    def _log(self, text: str):
        self.q.put(("log", text))

    def _append_log(self, text: str):
        self.details.configure(state="normal")
        self.details.insert("end", text + "\n")
        self.details.see("end")
        self.details.configure(state="disabled")

    def _toggle_details(self):
        if self.details_open:
            self.details_frame.pack_forget()
            self.details_btn.configure(text="Show details")
        else:
            self.details_frame.pack(side="bottom", fill="x", pady=(8, 0), before=self.scroll_wrap)
            self.details_btn.configure(text="Hide details")
        self.details_open = not self.details_open

    def _set_status(self, text: str):
        self.status.configure(text=text)

    def _set_busy(self, busy: bool, text: str = ""):
        self.busy = busy
        if busy:
            self.progress.pack(side="right", padx=10, before=self.details_btn)
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
            except api.UnlockError as err:
                self.q.put(("done", done, "error", str(err)))
            except Exception as err:  # never let a worker thread kill the window
                self.q.put(("done", done, "error", f"Unexpected error: {err}"))

        threading.Thread(target=target, daemon=True).start()

    def _pump(self):
        try:
            while True:
                kind, *rest = self.q.get_nowait()
                if kind == "log":
                    self._append_log(rest[0])
                elif kind == "done":
                    done, status, payload = rest
                    self._set_busy(False)
                    done(status, payload)
                elif kind == "fastboot":
                    self._fastboot_ready(*rest)
                elif kind == "backup":
                    self._backup_progress(rest[0])
                elif kind == "device":
                    self._device_seen(rest[0], rest[1] if len(rest) > 1 else None,
                                      rest[2] if len(rest) > 2 else None)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _colour(self, widget, colour: str):
        widget.configure(foreground=colour)

    # ----------------------------------------------------------------- state
    def _refresh(self):
        logged = self.token is not None
        ready = bool(self.eligibility and self.eligibility.get("eligible")) and not self.unlocked

        # step 1
        if logged:
            self.s1.configure(text="✓ Signed in", foreground=GREEN)
            self.login_btn.configure(state="disabled")
        else:
            self.s1.configure(text="", foreground=MUTED)
            self.login_btn.configure(state="disabled" if self.busy else "normal")

        # step 2
        usable2 = logged and not self.unlocked
        self.check_btn.configure(state="normal" if (usable2 and self.device and not self.busy) else "disabled")
        if not logged:
            self.s2.configure(text="Sign in first", foreground=MUTED)
        elif self.eligibility is not None and self.eligibility.get("eligible"):
            self.s2.configure(text="✓ Eligible", foreground=GREEN)
        else:
            self.s2.configure(text="", foreground=MUTED)

        # badges: green = done, orange = do this next, grey = not yet
        self.n1.configure(bg=GREEN if logged else ACCENT)
        done2 = bool(self.eligibility and self.eligibility.get("eligible"))
        self.n2.configure(bg=GREEN if done2 else (ACCENT if logged else "#9aa0a6"))
        self.n3.configure(bg=GREEN if self.unlocked else (ACCENT if ready else "#9aa0a6"))

        # step 3
        on = "normal" if ready else "disabled"
        self.chk.configure(state=on)
        self.name_entry.configure(state=on)
        match = False
        if ready and self.eligibility:
            match = self.name_var.get().strip().lower() == str(self.eligibility["product"]).lower()
        can_unlock = ready and self.confirm_var.get() and match and not self.busy
        self.unlock_btn.configure(
            state="normal" if can_unlock else "disabled",
            bg=RED if can_unlock else "#d3aaa6",
            cursor="hand2" if can_unlock else "arrow",
        )
        if self.unlocked:
            self.s3.configure(text="✓ Done", foreground=GREEN)
        elif ready:
            self.s3.configure(text="Ready", foreground=AMBER)
        else:
            self.s3.configure(text="", foreground=MUTED)

    # --------------------------------------------------------------- fastboot
    def _prepare_fastboot(self):
        self.dev_text.configure(text="Preparing USB...")

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
        self.dev_text.configure(text="No phone detected. Waiting...", foreground=MUTED)
        self.root.after(500, self._poll_device)

    def _poll_device(self):
        if not self.fastboot:
            return
        self._scan()
        self._update_tip()
        self.root.after(2000, self._poll_device)

    def _update_tip(self):
        """After a while with no phone, say what usually fixes it."""
        waiting = self.device is None and self.android is None and self._none_since is not None \
            and time.time() - self._none_since > 20
        if waiting and not self.dev_tip.winfo_ismapped():
            tip = ("Still no phone. Use a data cable (not charge-only) in another USB port, and check the "
                   "phone shows the fastboot screen.")
            if sys.platform == "win32":
                tip += " On Windows try File > Install Google USB driver."
            self.dev_tip.configure(text=tip)
            self.dev_tip.pack(anchor="w", pady=(6, 0), after=self.dev_text.master)
        elif not waiting and self.dev_tip.winfo_ismapped():
            self.dev_tip.pack_forget()

    def _copy_device(self):
        pairs = self._device_pairs(self.device, self.android, self.fb_info)
        if pairs:
            text = "\n".join(f"{k}: {v}" for k, v in pairs if v not in (None, ""))
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._set_status("Device info copied (serial is masked).")

    def _scan(self):
        if not self.fastboot:
            return
        if not self.busy and not self._polling:
            self._polling = True

            def work():
                serial = None
                android = None
                try:
                    found = fastboot.devices()
                    usable = [d for d in found if d["accessible"]]
                    if usable:
                        serial = usable[0]["serial"]
                    elif found:  # in fastboot, but no driver or permission
                        android = {"serial": found[0]["serial"], "state": "no-access", "mode": "fastboot"}
                except Exception:
                    serial = None
                if serial is None and android is None:
                    try:  # no phone in fastboot: see whether one is running Android
                        found = adb.devices()
                        if found:
                            ready = [d for d in found if d["state"] == "device"]
                            android = dict(ready[0] if ready else found[0])
                            if android["state"] == "device":
                                if android["serial"] not in self._info:
                                    self._info[android["serial"]] = adb.device_info(android["serial"])
                                android.update(self._info[android["serial"]])
                    except Exception:
                        android = None
                fbinfo = None
                if serial:
                    try:
                        if serial not in self._fbinfo:
                            self._fbinfo[serial] = fastboot.info(serial)
                        fbinfo = self._fbinfo[serial]
                    except Exception:
                        fbinfo = None
                self._polling = False
                self.q.put(("device", serial, android, fbinfo))

            threading.Thread(target=work, daemon=True).start()

    def _show_info(self, pairs):
        """Show a small table of device facts (label, value), or hide it when empty."""
        for child in self.info_box.winfo_children():
            child.destroy()
        pairs = [(k, v) for k, v in pairs if v not in (None, "")]
        self.info_box.pack_forget()
        if not pairs:
            return
        for r, (label, value) in enumerate(pairs):
            ttk.Label(self.info_box, text=label, foreground=MUTED).grid(row=r, column=0, sticky="w", padx=(0, 14))
            ttk.Label(self.info_box, text=str(value)).grid(row=r, column=1, sticky="w")
        self.info_box.pack(fill="x", pady=(8, 0), before=self._row2)

    def _device_pairs(self, serial, android, fb):
        if serial and fb:
            state = {"yes": "Already unlocked", "no": "Locked"}.get(str(fb.get("unlocked")).lower())
            return [
                ("Device", fb.get("product")),
                ("Mode", "Fastboot"),
                ("Bootloader", state),
                ("Bootloader version", fb.get("bootloader_version")),
                ("Active slot", fb.get("slot")),
                ("Serial", mask_id(fb["serial"]) if fb.get("serial") else None),
            ]
        if android and android.get("state") == "device":
            lock = {True: "Locked", False: "Already unlocked"}.get(android.get("bootloader_locked"))
            ver = android.get("hyperos") or android.get("miui")
            battery = android.get("battery")
            return [
                ("Device", " ".join(x for x in (android.get("brand"), android.get("model")) if x)),
                ("Codename", android.get("codename")),
                ("Mode", "Android (adb)"),
                ("Android", android.get("android")),
                ("HyperOS / MIUI", ver),
                ("Security patch", android.get("security_patch")),
                ("Bootloader", lock),
                ("Battery", None if battery is None else f"{battery}%" + ("  (charge above 50% first)" if battery < 50 else "")),
                ("Serial", mask_id(android["serial"])),
            ]
        return []

    def _device_seen(self, serial: Optional[str], android: Optional[dict] = None, fb: Optional[dict] = None):
        if serial == self.device and android == self.android and fb == self.fb_info:
            return
        was_connected = self.device is not None
        self.device, self.android, self.fb_info = serial, android, fb
        pairs = self._device_pairs(serial, android, fb)
        self._show_info(pairs)
        self._none_since = None if (serial or android) else (self._none_since or time.time())
        if pairs:
            self.copy_btn.pack(side="right", padx=6, before=self.rescan_btn)
        else:
            self.copy_btn.pack_forget()
        if android and android.get("state") == "device" and not serial:
            self.backup_btn.pack(side="right", before=self.copy_btn if pairs else self.rescan_btn)
            self.apps_btn.pack(side="right", padx=6, before=self.backup_btn)
        else:
            self.backup_btn.pack_forget()
            self.apps_btn.pack_forget()
        self.fb_btn.pack_forget()
        if serial:
            self.dev_dot.configure(fg=GREEN)
            self.dev_text.configure(text=f"Phone detected in fastboot mode ({serial})", foreground=GREEN)
            self._log(f"Device detected in fastboot: {serial}")
        elif android and android["state"] == "device":
            name = android.get("model") or android["serial"]
            ver = android.get("hyperos") or android.get("miui") or ""
            lock = {True: ", bootloader locked", False: ", bootloader unlocked"}.get(android.get("bootloader_locked"), "")
            self.dev_dot.configure(fg=ORANGE_DOT)
            self.dev_text.configure(
                text=f"{name} is on (Android {android.get('android') or '?'} {ver}{lock}). It must be in fastboot mode.",
                foreground=MUTED)
            self.fb_btn.pack(side="left", padx=6)
            self._log(f"Phone seen by adb: {name}")
        elif android and android["state"] == "no-access":
            where = " in fastboot mode" if android.get("mode") == "fastboot" else ""
            self.dev_dot.configure(fg=ORANGE_DOT)
            self.dev_text.configure(text=f"Phone found{where}, but it can't be opened. " + usbio.no_access_advice(),
                                    foreground=AMBER)
        elif android and android["state"] == "unauthorized":
            self.dev_dot.configure(fg=ORANGE_DOT)
            self.dev_text.configure(
                text="Phone connected. Tap Allow on its \"Allow USB debugging?\" prompt.",
                foreground=MUTED)
        elif android:
            self.dev_dot.configure(fg=ORANGE_DOT)
            self.dev_text.configure(
                text="Phone connected, but adb can't talk to it. Turn USB debugging off and on, then reconnect.",
                foreground=MUTED)
        else:
            self.dev_dot.configure(fg=MUTED)
            self.dev_text.configure(text="No phone detected. Waiting...", foreground=MUTED)
            if was_connected:
                self._log("Device disconnected.")
            if self.eligibility is not None and not self.unlocked:
                self.eligibility = None
                self._show_check("", "", "", MUTED)
                self.r2_raw.configure(text="")
        self._refresh()

    def _to_fastboot(self):
        serial = (self.android or {}).get("serial")
        if not serial:
            return
        self._log("Asking the phone to reboot into fastboot mode (nothing is erased)...")
        self.fb_btn.configure(state="disabled")

        def work():
            adb.reboot_to_bootloader(serial)
            self._info.pop(serial, None)
            return None

        def done(status, result):
            self.fb_btn.configure(state="normal")
            if status == "error":
                self._log(f"Could not reboot to fastboot: {result}")
                messagebox.showerror("Reboot to fastboot", str(result))

        self._run(work, done, "Rebooting the phone into fastboot mode...")

    # ------------------------------------------------------------------ step 1
    def _login(self):
        self._log("Signing in...")
        self.r1.configure(text="Waiting for you to finish signing in in the browser window...")

        def work():
            token = api.login(login_method="1", silent_if_cached=True)
            return token, api.get_account_zone(token)

        self._run(work, self._login_done, "Waiting for sign-in in your browser...")

    def _login_done(self, status: str, result):
        if status == "error":
            self.r1.configure(text=f"Sign-in didn't complete: {result}", foreground=RED)
            self._log(f"Sign-in failed: {result}")
            return
        self.token, self.zone = result
        who = mask_id(self.token["userId"])  # masked so screenshots don't expose the account ID
        self.r1.configure(text=f"Account {who}  ·  data center: {self.zone}", foreground=MUTED)
        self._log(f"Signed in as {who} ({self.zone})")
        self._refresh()

    # ------------------------------------------------------------------ step 2
    def _show_check(self, title: str, body: str, raw: str, colour: str):
        """Show or clear the result of step 2. Empty parts are hidden so they take no room."""
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
        self._log("Checking eligibility with Xiaomi...")
        self._run(lambda: api.check_unlock_eligibility(self.token, self.zone), self._check_done,
                  "Asking Xiaomi if this phone can be unlocked...")

    def _check_done(self, status: str, result):
        if status == "error":
            self._show_check("Couldn't check", str(result), "", RED)
            self._log(f"Check failed: {result}")
            return
        shown = {k: v for k, v in result.items() if not k.startswith("_")}
        self._log(f"Xiaomi replied: {shown}")

        if result.get("eligible"):
            self.eligibility = result
            wipe = result.get("will_wipe_data")
            body = (
                f"Phone: {result['product']}  ·  data center: {result['zone']}\n"
                + ("This will ERASE all data on the phone." if wipe else "Xiaomi says this unlock will not erase data.")
            )
            notice = result.get("notice")
            self._show_check("Ready to unlock", body, f"Xiaomi's notice: {notice}" if notice else "", GREEN)
            self.d3.configure(
                text=f"Phone: {result['product']}. Unlocking {'erases all data on it' if wipe else 'will not erase data'} "
                     "and cannot be undone.",
                foreground=RED if wipe else MUTED,
            )
            self.name_lbl.configure(text=f"Type the phone's name ({result['product']}) to confirm:")
            self.name_var.set("")
            self.confirm_var.set(False)
        else:
            hint = explain(result.get("code"), result.get("description"))
            raw = result.get("description") or result.get("error") or ""
            code = f"Code {result['code']}. " if result.get("code") else ""
            self._show_check(
                hint.title, hint.advice, f"{code}Xiaomi said: {raw}" if raw else "",
                AMBER if hint.kind == "wait" else RED,
            )
        self._refresh()

    # ------------------------------------------------------------------ step 3
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
                  self._unlock_done, "Unlocking. Keep the phone connected and don't unplug it...")

    def _unlock_done(self, status: str, result):
        if status == "error":
            self._set_r3(f"The unlock did not complete: {result}", RED)
            self._log(f"Unlock failed: {result}")
            return
        self.unlocked = True
        self._fbinfo.clear()
        self._set_r3(
            "Bootloader unlocked. The phone is resetting; the first start can take several "
            "minutes. If it stays on the fastboot screen, use Reboot phone.",
            GREEN,
        )
        self._log(f"Unlock finished: {result}")
        self.reboot_btn.pack(side="left", padx=10)
        self._refresh()

    def _reboot(self):
        if not self.fastboot:
            return
        try:
            fastboot.reboot(self.device)
            self._log("Sent reboot command.")
        except Exception as err:
            self._log(f"Reboot failed: {err}")

    # -------------------------------------------------------------------- menu
    def _sign_out(self):
        folder = Path.home() / ".miunlocksession"
        if not messagebox.askyesno(
            "Sign out",
            f"This deletes the saved session folder:\n\n{folder}\n\n"
            "It does not end the session on Xiaomi's side. Check your signed-in devices "
            "on your Mi Account afterwards.\n\nDelete it?",
            default="no",
        ):
            return
        store.delete_all()
        self.token = self.zone = self.eligibility = None
        self.r1.configure(text="Signed out. Saved session deleted.", foreground=MUTED)
        self._show_check("", "", "", MUTED)
        self._log("Saved session deleted.")
        self._refresh()

    def _install_driver(self):
        if self.busy:
            return
        if not messagebox.askyesno(
            "Install Google USB driver",
            "This downloads Google's official Android USB driver (dl.google.com) and installs it\n"
            "with Windows' own installer. Windows will ask for administrator permission.\n\n"
            "Do this only if your phone is not detected. Continue?",
        ):
            return

        def done(status, result):
            if status == "error":
                self._log(f"USB driver: {result}")
                messagebox.showerror("Install Google USB driver", str(result))
            else:
                self._log(str(result))
                if messagebox.askyesno("Install Google USB driver", f"{result}\n\nOpen Device Manager now?"):
                    try:
                        subprocess.Popen(["mmc", "devmgmt.msc"], creationflags=NO_WINDOW)
                    except OSError as err:
                        self._log(f"Could not open Device Manager: {err}")

        self._run(lambda: drivers.install_usb_driver(self._log), done, "Installing the USB driver...")

    def _show_log(self):
        path = log.log_path()
        if path is None:
            messagebox.showinfo("Log file", "Logging to a file is off: the program's folder is not writable.")
        elif messagebox.askyesno("Log file", f"The log is saved here:\n\n{path}\n\nIt never contains tokens. Open its folder?"):
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["explorer", "/select,", str(path)], creationflags=NO_WINDOW)
                else:
                    webbrowser.open(path.parent.as_uri())
            except Exception as err:
                self._log(f"Could not open the folder: {err}")

    # ------------------------------------------------------------------ backup
    def _backup_dialog(self):
        serial = (self.android or {}).get("serial")
        if not serial:
            return
        win = tk.Toplevel(self.root)
        win.title("Back up files from the phone")
        win.transient(self.root)
        win.resizable(False, False)
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Copy files from the phone to this computer", font=self.f_bold).pack(anchor="w")
        ttk.Label(body, foreground=MUTED, justify="left", text=(
            "Nothing on the phone is changed or deleted. Keep the screen unlocked and allow file\n"
            "access if the phone asks. App data, contacts, SMS and chats are not covered: use\n"
            "Mi Cloud, Google or each app's own backup for those (see the guide).")).pack(anchor="w", pady=(2, 10))

        vars_ = {}
        for key, (label, _folders) in adb.BACKUP_SETS.items():
            v = tk.BooleanVar(value=key in ("photos", "documents"))
            vars_[key] = v
            ttk.Checkbutton(body, text=label, variable=v).pack(anchor="w")

        name = (self.android.get("model") or "phone").replace(" ", "-")
        default = Path.home() / "miunlock-backup" / f"{name}-{datetime.date.today().isoformat()}"
        dest_var = tk.StringVar(value=str(default))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(12, 0))
        ttk.Label(row, text="Save to:").pack(side="left")
        ttk.Entry(row, textvariable=dest_var, width=48).pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=lambda: dest_var.set(
            filedialog.askdirectory(parent=win, initialdir=str(Path.home())) or dest_var.get())).pack(side="left")

        self._bk_label = ttk.Label(body, text="", foreground=MUTED, wraplength=520, justify="left")
        self._bk_label.pack(anchor="w", pady=(10, 0))
        bar = ttk.Progressbar(body, mode="indeterminate")
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        cancel_event = threading.Event()
        self._bk_cancel = cancel_event
        start = ttk.Button(buttons, text="Start backup", style="Primary.TButton")
        close = ttk.Button(buttons, text="Close", command=lambda: (cancel_event.set(), win.destroy()))
        close.pack(side="right")
        start.pack(side="right", padx=6)

        def begin():
            chosen = [k for k, v in vars_.items() if v.get()]
            if not chosen:
                messagebox.showinfo("Back up", "Tick at least one thing to copy.", parent=win)
                return
            cancel_event.clear()
            start.configure(state="disabled")
            bar.pack(fill="x", pady=(8, 0))
            bar.start(12)
            dest = dest_var.get().strip()

            def work():
                return adb.backup_files(serial, dest, chosen, self._bk_log, cancel_event)

            def done(status, result):
                bar.stop()
                bar.pack_forget()
                start.configure(state="normal")
                if status == "error":
                    msg = f"Backup did not finish: {result}"
                elif result.get("cancelled"):
                    msg = f"Cancelled. Files copied so far are in {result['dest']}"
                else:
                    msg = (f"Done. {result['files']} files ({result['bytes'] / 1e6:.1f} MB) from "
                           f"{len(result['copied'])} folder(s) saved to {result['dest']}")
                    if result.get("failed_files"):
                        msg += f". {result['failed_files']} file(s) could not be read"
                    if result["skipped"]:
                        msg += f"  (not found or failed: {', '.join(result['skipped'])})"
                self._bk_label.configure(text=msg, foreground=RED if status == "error" else GREEN)
                self._log(msg)

            self._run(work, done, "Backing up files from the phone...")

        start.configure(command=begin)

    # ------------------------------------------------------------ app manager
    def _apps_dialog(self):
        serial = (self.android or {}).get("serial")
        if not serial:
            return
        win = tk.Toplevel(self.root)
        win.title("Manage apps")
        win.geometry("900x600")
        win.minsize(640, 400)
        win.transient(self.root)
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)

        tk.Label(body, bg=WARN_BG, fg=WARN_FG, justify="left", anchor="w", padx=10, pady=6, wraplength=840,
                 text="Tick the apps to remove, then click Remove ticked. Preinstalled apps are only removed "
                      "for your user and can be restored here. Unlocking the bootloader resets the phone and "
                      "brings them all back, so debloat after unlocking, or if you are not unlocking."
                 ).pack(fill="x")

        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(10, 6))
        ttk.Label(bar, text="Show:").pack(side="left")
        view_var = tk.StringVar(value="Known bloat")
        view = ttk.Combobox(bar, textvariable=view_var, state="readonly", width=24,
                            values=["Known bloat", "All preinstalled", "Installed by you", "Removed (restorable)", "Everything"])
        view.pack(side="left", padx=6)
        ttk.Label(bar, text="Search:").pack(side="left", padx=(12, 0))
        search_var = tk.StringVar()
        ttk.Entry(bar, textvariable=search_var, width=28).pack(side="left", padx=6)
        count_lbl = ttk.Label(bar, text="Loading apps from the phone...", foreground=MUTED)
        count_lbl.pack(side="right")

        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        cols = ("mark", "name", "package", "rating", "status", "note")
        tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="browse")
        for col, title, width, stretch in (("mark", "", 34, False), ("name", "App", 170, False),
                                           ("package", "Package", 250, True), ("rating", "Rating", 100, False),
                                           ("status", "Status", 90, False), ("note", "Note", 260, True)):
            tree.heading(col, text=title)
            tree.column(col, width=width, stretch=stretch, anchor="center" if col == "mark" else "w")
        ysb = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        for tag, colour in (("recommended", GREEN), ("advanced", AMBER), ("avoid", RED), ("unknown", MUTED)):
            tree.tag_configure(tag, foreground=colour)

        status_lbl = ttk.Label(body, text="", foreground=MUTED, wraplength=840, justify="left")
        status_lbl.pack(fill="x", pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))

        apps: list = []
        marked: set = set()

        def label(app) -> tuple:
            name, rating, note = bloat.describe(app["package"], app["system"])
            status = "Removed" if not app["installed"] else ("Disabled" if app["disabled"] else "Installed")
            return name, rating, note, status

        def shown(app) -> bool:
            name, rating, _note, _status = label(app)
            v = view_var.get()
            if v == "Known bloat" and not (app["package"] in bloat.KNOWN and rating != "avoid" and app["installed"]):
                return False
            if v == "All preinstalled" and not (app["system"] and app["installed"]):
                return False
            if v == "Installed by you" and app["system"]:
                return False
            if v == "Removed (restorable)" and app["installed"]:
                return False
            q = search_var.get().strip().lower()
            return not q or q in app["package"].lower() or q in name.lower()

        def fill(*_):
            tree.delete(*tree.get_children())
            order = {r: i for i, r in enumerate(bloat.RATINGS)}
            rows = [a for a in apps if shown(a)]
            rows.sort(key=lambda a: (order[label(a)[1]], a["package"]))
            for a in rows:
                name, rating, note, status = label(a)
                tree.insert("", "end", iid=a["package"], tags=(rating,),
                            values=("\u2611" if a["package"] in marked else "\u2610", name, a["package"],
                                    rating.capitalize(), status, note))
            count_lbl.configure(text=f"{len(rows)} shown, {len(marked)} ticked")

        def toggle_row(row):
            if not row:
                return
            marked.symmetric_difference_update({row})
            tree.set(row, "mark", "\u2611" if row in marked else "\u2610")
            count_lbl.configure(text=f"{len(tree.get_children())} shown, {len(marked)} ticked")

        tree.bind("<Button-1>", lambda e: toggle_row(tree.identify_row(e.y)))
        tree.bind("<space>", lambda _e: toggle_row(tree.focus()))
        view.bind("<<ComboboxSelected>>", fill)
        search_var.trace_add("write", fill)

        def tick_recommended():
            for a in apps:
                if a["installed"] and bloat.describe(a["package"], a["system"])[1] == "recommended":
                    marked.add(a["package"])
            fill()

        def act(restore: bool):
            chosen = sorted(marked)
            by_pkg = {a["package"]: a for a in apps}
            if restore:
                chosen = [p for p in chosen if not by_pkg[p]["installed"]]
            else:
                chosen = [p for p in chosen if by_pkg[p]["installed"]]
            if not chosen:
                messagebox.showinfo("Manage apps", "Tick at least one "
                                    + ("removed app to restore." if restore else "installed app to remove."), parent=win)
                return
            if not restore:
                risky = [p for p in chosen if bloat.describe(p, by_pkg[p]["system"])[1] in ("avoid", "advanced", "unknown")]
                yours = [p for p in chosen if not by_pkg[p]["system"]]
                text = f"Remove {len(chosen)} app(s) for your user?"
                if risky:
                    text += ("\n\nThese can affect the phone or the unlock:\n  " + "\n  ".join(risky[:12])
                             + ("\n  ..." if len(risky) > 12 else ""))
                if yours:
                    text += f"\n\n{len(yours)} of them were installed by you and will be uninstalled, not just hidden."
                if not messagebox.askyesno("Remove apps", text, default="no" if risky else "yes",
                                           icon="warning" if risky else "question", parent=win):
                    return

            def work():
                done_ok, failed = [], []
                for pkg in chosen:
                    try:
                        (adb.restore_for_user if restore else adb.uninstall_for_user)(pkg, serial)
                        done_ok.append(pkg)
                        self._log(("Restored " if restore else "Removed ") + pkg)
                    except adb.AdbError as err:
                        failed.append(pkg)
                        self._log(f"Could not {'restore' if restore else 'remove'} {pkg}: {err}")
                return done_ok, failed, adb.list_packages(serial)

            def done(status, result):
                if status == "error":
                    status_lbl.configure(text=str(result), foreground=RED)
                    return
                ok, failed, fresh = result
                apps[:] = fresh
                marked.difference_update(ok)
                fill()
                verb = "Restored" if restore else "Removed"
                status_lbl.configure(
                    text=f"{verb} {len(ok)} app(s)." + (f" {len(failed)} failed: {', '.join(failed[:6])}" if failed else ""),
                    foreground=RED if failed else GREEN)

            self._run(work, done, ("Restoring" if restore else "Removing") + " apps...")

        ttk.Button(buttons, text="Tick recommended", command=tick_recommended).pack(side="left")
        ttk.Button(buttons, text="Clear ticks", command=lambda: (marked.clear(), fill())).pack(side="left", padx=6)
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="Restore ticked", command=lambda: act(True)).pack(side="right", padx=6)
        ttk.Button(buttons, text="Remove ticked", style="Primary.TButton", command=lambda: act(False)).pack(side="right")

        def loaded(status, result):
            if status == "error":
                count_lbl.configure(text="")
                status_lbl.configure(text=f"Could not read the app list: {result}", foreground=RED)
                return
            apps[:] = result
            fill()

        self._run(lambda: adb.list_packages(serial), loaded, "Reading the app list from the phone...")

    def _bk_log(self, text: str):
        self.q.put(("log", text))
        self.q.put(("backup", text))

    def _backup_progress(self, text: str):
        try:
            if getattr(self, "_bk_label", None) is not None and self._bk_label.winfo_exists():
                self._bk_label.configure(text=text, foreground=MUTED)
        except tk.TclError:
            pass

    def _open_guide(self):
        """Offline step-by-step guide in its own window; one copy at a time."""
        win = getattr(self, "_guide_win", None)
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_force()
            return
        win = self._guide_win = tk.Toplevel(self.root)
        win.title("miunlock guide")
        win.geometry("760x520")
        win.minsize(520, 340)
        win.transient(self.root)
        win.bind("<Escape>", lambda _e: win.destroy())

        body = ttk.Frame(win, padding=10)
        body.pack(fill="both", expand=True)
        side = tk.Listbox(body, width=30, exportselection=False, activestyle="none",
                          borderwidth=0, highlightthickness=1, highlightbackground=BORDER)
        side.pack(side="left", fill="y")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        sbar = ttk.Scrollbar(right)
        sbar.pack(side="right", fill="y")
        text = tk.Text(right, wrap="word", padx=14, pady=10, borderwidth=0, highlightthickness=0,
                       font=self.f_base, yscrollcommand=sbar.set, cursor="arrow", spacing3=6)
        text.pack(side="left", fill="both", expand=True)
        sbar.configure(command=text.yview)
        text.tag_configure("h", font=self.f_title, spacing3=10)
        text.tag_configure("b", lmargin1=18, lmargin2=36)
        text.tag_configure("w", background=WARN_BG, foreground=WARN_FG, font=self.f_bold,
                           lmargin1=8, lmargin2=8, rmargin=8, spacing1=4, spacing3=10)

        def show(index: int):
            title, blocks = guide.TOPICS[index]
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("end", title + "\n", "h")
            for kind, content in blocks:
                if kind == "b":
                    text.insert("end", "\u2022  " + content + "\n", "b")
                elif kind == "w":
                    text.insert("end", "\u26a0  " + content + "\n", "w")
                else:
                    text.insert("end", content + "\n")
            text.configure(state="disabled")
            text.yview_moveto(0)

        for title, _ in guide.TOPICS:
            side.insert("end", "  " + title)

        def pick(i: int):
            side.selection_clear(0, "end")
            side.selection_set(i)
            side.see(i)
            show(i)

        def on_pick(_e=None):
            sel = side.curselection()
            if sel:
                show(sel[0])

        def step(delta: int):
            sel = side.curselection()
            pick(min(max((sel[0] if sel else 0) + delta, 0), len(guide.TOPICS) - 1))

        side.bind("<<ListboxSelect>>", on_pick)
        pick(0)

        nav = ttk.Frame(win, padding=(10, 0, 10, 10))
        nav.pack(fill="x")
        ttk.Button(nav, text="Close", command=win.destroy).pack(side="right")
        ttk.Button(nav, text="Next \u25b6", command=lambda: step(1)).pack(side="right", padx=6)
        ttk.Button(nav, text="\u25c0 Back", command=lambda: step(-1)).pack(side="right")
        ttk.Button(nav, text="Open full guide in browser",
                   command=lambda: webbrowser.open(DOCS + "unlock-guide.md")).pack(side="left")

    def _about(self):
        messagebox.showinfo(
            "About miunlock",
            f"miunlock {__version__}\n\n"
            "A standalone, hardened fork derived from MiUnlockTool and migate by offici5l.\n"
            "Apache License 2.0. Not affiliated with Xiaomi.\n\n" + REPO,
        )


def _enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main():
    log.setup()
    _enable_dpi_awareness()
    root = tk.Tk()
    app = App(root)
    # Route anything the library prints into "Details" (and keep printing safe when
    # there is no console, as in the windowed Windows build).
    stream = _LogStream(app._log)
    saved = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = stream
    try:
        root.mainloop()
    finally:
        sys.stdout, sys.stderr = saved


if __name__ == "__main__":
    main()
