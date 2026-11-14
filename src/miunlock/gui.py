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
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable, Optional

from miunlock import __version__, api
from miunlock.auth.redact import mask_id
from miunlock.fastboot import get_fastboot
from miunlock.hints import explain
from miunlock.system import NO_WINDOW

REPO = "https://github.com/jowinjohnchemban/miunlock"
DOCS = REPO + "/blob/main/docs/"

GREEN = "#1a7f37"
RED = "#b3261e"
AMBER = "#9a5b00"
MUTED = "#5f6368"
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
        root.geometry("780x660")
        root.minsize(700, 560)

        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.token: Optional[dict] = None
        self.zone: Optional[str] = None
        self.fastboot: Optional[str] = None
        self.device: Optional[str] = None  # serial of the connected fastboot device
        self.eligibility: Optional[dict] = None
        self.unlocked = False
        self.busy = False
        self._polling = False
        self._wrap_labels: list[ttk.Label] = []

        self._style()
        self._menu()
        self._layout()
        self._refresh()

        root.bind("<Configure>", self._on_resize)
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
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.root.destroy)
        bar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(bar, tearoff=0)
        help_menu.add_command(label="Unlock guide", command=lambda: webbrowser.open(DOCS + "unlock-guide.md"))
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
        outer = ttk.Frame(self.root, padding=(18, 14))
        outer.pack(fill="both", expand=True)

        # Status bar: packed first so it always keeps its space at the bottom.
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", side="bottom", pady=(6, 0))
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=120)
        self.status = ttk.Label(bottom, text="Ready.", foreground=MUTED)
        self.status.pack(side="left")
        self.details_open = False
        self.details_btn = ttk.Button(bottom, text="Show details", command=self._toggle_details)
        self.details_btn.pack(side="right")

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
        link = tk.Label(banner, text="Read the guide", bg=WARN_BG, fg=WARN_FG, cursor="hand2", font=self.f_base)
        link.configure(font=tkfont.Font(font=self.f_base, underline=True))
        link.pack(side="right")
        link.bind("<Button-1>", lambda _e: webbrowser.open(DOCS + "unlock-guide.md"))

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
        row2 = ttk.Frame(b2)
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

        self.details_frame = ttk.Frame(outer)
        self.details = tk.Text(self.details_frame, height=9, wrap="word", state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(self.details_frame, command=self.details.yview)
        self.details.configure(yscrollcommand=sb.set)
        self.details.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # --------------------------------------------------------------- helpers
    def _on_resize(self, event):
        if event.widget is self.root:
            width = max(event.width - 130, 400)
            for lab in self._wrap_labels:
                lab.configure(wraplength=width)

    def _log(self, text: str):
        self.q.put(("log", text))

    def _append_log(self, text: str):
        self.details.configure(state="normal")
        self.details.insert("end", text + "\n")
        self.details.see("end")
        self.details.configure(state="disabled")

    def _toggle_details(self):
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if self.details_open:
            self.details_frame.pack_forget()
            self.details_btn.configure(text="Show details")
            self.root.geometry(f"{w}x{max(h - 190, 560)}")
        else:
            self.details_frame.pack(fill="both", expand=True, pady=(8, 0))
            self.details_btn.configure(text="Hide details")
            self.root.geometry(f"{w}x{h + 190}")
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
                elif kind == "device":
                    self._device_seen(rest[0])
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
        self._log("Looking for fastboot (it is downloaded on first use)...")
        self.dev_text.configure(text="Preparing fastboot (first run may download it)...")

        def work():
            try:
                self.q.put(("fastboot", get_fastboot(), None))
            except SystemExit:
                self.q.put(("fastboot", None, "fastboot is not available on this system."))
            except Exception as err:
                self.q.put(("fastboot", None, f"Could not set up fastboot: {err}"))

        threading.Thread(target=work, daemon=True).start()

    def _fastboot_ready(self, path: Optional[str], error: Optional[str]):
        if error or not path:
            self.dev_dot.configure(fg=RED)
            self.dev_text.configure(text=error or "fastboot not found", foreground=RED)
            self._log(error or "fastboot not found")
            return
        self.fastboot = path
        self._log(f"Using fastboot at {path}")
        self.dev_text.configure(text="No phone detected. Waiting...", foreground=MUTED)
        self.root.after(500, self._poll_device)

    def _poll_device(self):
        if not self.fastboot:
            return
        if not self.busy and not self._polling:
            self._polling = True

            def work():
                serial = None
                try:
                    out = subprocess.run(
                        [self.fastboot, "devices"], capture_output=True, text=True,
                        timeout=8, creationflags=NO_WINDOW,
                    ).stdout
                    for line in out.splitlines():
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == "fastboot":
                            serial = parts[0]
                            break
                except Exception:
                    serial = None
                self._polling = False
                self.q.put(("device", serial))

            threading.Thread(target=work, daemon=True).start()
        self.root.after(2000, self._poll_device)

    def _device_seen(self, serial: Optional[str]):
        if serial == self.device:
            return
        self.device = serial
        if serial:
            self.dev_dot.configure(fg=GREEN)
            self.dev_text.configure(text=f"Phone detected in fastboot mode ({serial})", foreground=GREEN)
            self._log(f"Device detected: {serial}")
        else:
            self.dev_dot.configure(fg=MUTED)
            self.dev_text.configure(text="No phone detected. Waiting...", foreground=MUTED)
            self._log("Device disconnected.")
            if self.eligibility is not None and not self.unlocked:
                self.eligibility = None
                self._show_check("", "", "", MUTED)
                self.r2_raw.configure(text="")
        self._refresh()

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
            subprocess.run([self.fastboot, "reboot"], capture_output=True, text=True,
                           timeout=15, creationflags=NO_WINDOW)
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
        shutil.rmtree(folder, ignore_errors=True)
        self.token = self.zone = self.eligibility = None
        self.r1.configure(text="Signed out. Saved session deleted.", foreground=MUTED)
        self._show_check("", "", "", MUTED)
        self._log("Saved session deleted.")
        self._refresh()

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
