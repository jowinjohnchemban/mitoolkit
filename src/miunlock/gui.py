"""
Simple Tkinter GUI for miunlock. Ships with Python -- no new dependency.

This is a thin window around api.py. The one thing it does NOT let you
skip: before the actual unlock runs, a real confirmation dialog appears
with the server's own data-wipe notice in it, and only clicking "Yes"
there sets confirm_wipe=True for that one call. There is no "don't ask
again" or auto-confirm option, on purpose -- see api.py's docstring for
why.
"""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

from miunlock import api


class MiUnlockGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("MiUnlockTool (standalone, hardened)")
        root.geometry("640x480")

        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._token: dict | None = None
        self._eligibility: dict | None = None

        top = tk.Frame(root)
        top.pack(fill="x", padx=10, pady=10)

        self.login_btn = tk.Button(top, text="1. Log in", command=self._on_login)
        self.login_btn.pack(side="left", padx=4)

        self.check_btn = tk.Button(top, text="2. Check eligibility", command=self._on_check, state="disabled")
        self.check_btn.pack(side="left", padx=4)

        self.unlock_btn = tk.Button(top, text="3. Unlock device...", command=self._on_unlock_clicked,
                                     state="disabled", fg="white", bg="#b00020")
        self.unlock_btn.pack(side="left", padx=4)

        self.status = tk.Label(root, text="Not logged in.", anchor="w")
        self.status.pack(fill="x", padx=10)

        self.log = scrolledtext.ScrolledText(root, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

        warn = tk.Label(
            root,
            text="Step 3 wipes the device's data permanently. A confirmation\n"
                 "dialog with the server's own notice appears before anything happens.",
            fg="#b00020",
        )
        warn.pack(pady=(0, 8))

        self.root.after(150, self._poll_queue)

    def _write(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text: str):
        self.status.configure(text=text)

    def _run_bg(self, fn, on_done):
        def worker():
            try:
                result = fn()
                self._queue.put((on_done, ("ok", result)))
            except api.UnlockError as e:
                self._queue.put((on_done, ("error", str(e))))
            except Exception as e:  # last-resort: never crash the GUI thread
                self._queue.put((on_done, ("error", f"Unexpected error: {e}")))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                callback, payload = self._queue.get_nowait()
                callback(*payload)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    # -- Step 1: login -----------------------------------------------------
    def _on_login(self):
        self._write("Logging in (reusing a saved session if one exists)...")
        self._write("If no saved session exists, your browser will open to Xiaomi's "
                     "own login page -- log in there, not in this window.")
        self.login_btn.configure(state="disabled")
        self._run_bg(lambda: api.login(silent_if_cached=True), self._login_done)

    def _login_done(self, status, result):
        self.login_btn.configure(state="normal")
        if status == "error":
            self._write(f"Login failed: {result}")
            self._set_status("Login failed.")
            return
        self._token = result
        self._write(f"Logged in. Account ID: {result['userId']}")
        self._set_status(f"Logged in as {result['userId']}.")
        self.check_btn.configure(state="normal")

    # -- Step 2: check eligibility ------------------------------------------
    def _on_check(self):
        if self._token is None:
            messagebox.showwarning("Not logged in", "Log in first.")
            return
        self._write("Checking unlock eligibility (make sure the phone is in fastboot mode)...")
        self.check_btn.configure(state="disabled")
        self.unlock_btn.configure(state="disabled")
        self._run_bg(lambda: api.check_unlock_eligibility(self._token), self._check_done)

    def _check_done(self, status, result):
        self.check_btn.configure(state="normal")
        if status == "error":
            self._write(f"Check failed: {result}")
            self._set_status("Eligibility check failed.")
            return
        self._eligibility = result
        shown = {k: v for k, v in result.items() if not k.startswith("_")}
        self._write("Server response:\n" + json.dumps(shown, indent=2))
        if result.get("eligible"):
            self._set_status(f"Eligible. Device: {result['product']}. "
                              f"Will wipe data: {result.get('will_wipe_data')}.")
            self.unlock_btn.configure(state="normal")
        else:
            self._set_status("Not eligible right now -- see the log above for the server's reason.")

    # -- Step 3: the destructive step ----------------------------------------
    def _on_unlock_clicked(self):
        if not self._eligibility or not self._eligibility.get("eligible"):
            messagebox.showwarning("Not eligible", "Run 'Check eligibility' first.")
            return

        notice = self._eligibility.get("notice", "")
        will_wipe = self._eligibility.get("will_wipe_data")
        product = self._eligibility.get("product")

        confirmed = messagebox.askyesno(
            "Confirm: this wipes the device",
            f"Device: {product}\n\n"
            f"Server notice: {notice}\n\n"
            f"Will clear user data: {'YES' if will_wipe else 'no'}\n\n"
            "This cannot be undone once it starts. Make sure you have "
            "backed up everything you care about.\n\n"
            "Proceed with the unlock now?",
            icon="warning",
            default="no",
        )
        if not confirmed:
            self._write("Unlock cancelled -- you clicked No.")
            return

        self._write("Confirmed. Fetching unlock token and running fastboot oem unlock...")
        self.unlock_btn.configure(state="disabled")
        self._run_bg(
            lambda: api.perform_unlock(self._token, self._eligibility, confirm_wipe=True),
            self._unlock_done,
        )

    def _unlock_done(self, status, result):
        if status == "error":
            self._write(f"Unlock failed: {result}")
            self._set_status("Unlock failed -- see log.")
            messagebox.showerror("Unlock failed", str(result))
            return
        self._write(f"Unlock result: {json.dumps(result, indent=2)}")
        self._set_status("Unlock command completed.")
        messagebox.showinfo("Done", "fastboot oem unlock completed. The device will now reboot/reset.")


def main():
    root = tk.Tk()
    MiUnlockGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
