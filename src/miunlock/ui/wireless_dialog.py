"""Phone > Wireless adb: use the phone over Wi-Fi instead of a cable (not for fastboot or unlocking)."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from miunlock import adb, adb_server
from miunlock.adb_usb import AdbError
from miunlock.ui.base import Dialog
from miunlock.ui.components.buttons import Button
from miunlock.ui.theme import MUTED, RED

NOTE = ("Wireless adb covers backup, apps, live status and the other tools. Fastboot mode and unlocking work "
        "over a USB cable only: the phone's bootloader has no Wi-Fi, so plug it in for those steps.")


class WirelessDialog(Dialog):
    title = "Wireless adb"
    resizable = False
    padding = 16

    def build(self) -> None:
        self._busy = False
        body = self.body
        ttk.Label(body, text="Use the phone over Wi-Fi", font=self.fonts.heading).pack(anchor="w")
        ttk.Label(body, text=NOTE, foreground=MUTED, wraplength=470, justify="left").pack(anchor="w", pady=(2, 12))

        self.state = ttk.Label(body, wraplength=470, justify="left")
        self.state.pack(anchor="w")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(8, 0))
        self.action = Button(row, text="Turn on Wi-Fi debugging", primary=True, command=self._action)
        self.action.pack(side="left")

        ttk.Separator(body).pack(fill="x", pady=14)
        ttk.Label(body, text="Connect by address", font=self.fonts.bold).pack(anchor="w")
        ttk.Label(body, foreground=MUTED, wraplength=470, justify="left",
                  text="For a phone already set to Wi-Fi debugging. Example: 192.168.1.5").pack(
            anchor="w", pady=(2, 6))
        line = ttk.Frame(body)
        line.pack(fill="x")
        self.address = tk.StringVar()
        entry = ttk.Entry(line, textvariable=self.address, width=24)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self._connect())
        self.connect_btn = Button(line, text="Connect", command=self._connect)
        self.connect_btn.pack(side="left", padx=8)

        self.result = ttk.Label(body, wraplength=470, justify="left")
        self.result.pack(anchor="w", pady=(8, 0))
        Button(body, text="Close", command=self.close).pack(anchor="e", pady=(10, 0))
        self._refresh()

    # ----------------------------------------------------------------- state
    def _phone(self) -> Optional[adb.Phone]:
        serial = self.app._android_serial()
        if not serial:
            return None
        try:
            return adb.Phone(serial)
        except (AdbError, adb.AdbError):
            return None

    def _refresh(self) -> None:
        serial = self.app._android_serial()
        if serial and ":" in serial:
            self.state.configure(text=f"Connected over Wi-Fi: {serial}", foreground="")
            self.action.configure(text="Disconnect")
            self._mode = "disconnect"
        elif serial:
            self.state.configure(text="The phone is connected by USB. Switch it to Wi-Fi to unplug the cable "
                                      "(it stays on until the phone restarts).", foreground="")
            self.action.configure(text="Turn on Wi-Fi debugging")
            self._mode = "enable"
        else:
            self.state.configure(text="No phone is connected by USB. Plug it in once to switch it to Wi-Fi, or "
                                      "connect by address below.", foreground=MUTED)
            self.action.configure(text="Turn on Wi-Fi debugging")
            self._mode = "none"
        self.action.configure(state="normal" if self._mode != "none" and not self._busy else "disabled")

    # --------------------------------------------------------------- actions
    def _say(self, text: str, error: bool = False) -> None:
        if self.alive():
            self.result.configure(text=text, foreground=RED if error else MUTED)

    def _work(self, label: str, work: Callable[[], str], then: Callable[[str], str]) -> None:
        """Run `work` off the window's thread; show `then(answer)` or its error when it finishes."""
        if self._busy:
            return
        self._busy = True
        self._say(label)
        self.action.configure(state="disabled")
        outcome: list = []

        def target() -> None:
            try:
                outcome.append(("ok", work()))
            except (AdbError, adb.AdbError) as err:
                outcome.append(("error", str(err)))
            except Exception as err:  # never let a worker thread die silently
                outcome.append(("error", f"Unexpected error: {err}"))

        threading.Thread(target=target, daemon=True).start()

        def poll() -> None:
            if not self.alive():
                return
            if not outcome:
                self.win.after(150, poll)
                return
            self._busy = False
            status, value = outcome[0]
            if status == "ok":
                self._say(then(value))
                self.app._log(then(value))
                self.app._rescan()
            else:
                self._say(value, error=True)
                self.app._log(f"Wireless adb: {value}")
            self._refresh()

        self.win.after(150, poll)

    def _action(self) -> None:
        if self._mode == "enable":
            phone = self._phone()
            if phone is not None:
                self._work("Switching the phone to Wi-Fi...", phone.enable_wireless,
                           lambda target: f"Connected over Wi-Fi at {target}. You can unplug the USB cable now "
                                          "(not for fastboot).")
        elif self._mode == "disconnect":
            serial = self.app._android_serial()
            self._work("Disconnecting...", lambda: (adb_server.disconnect(serial), serial)[1],
                       lambda s: f"Disconnected {s}.")

    def _connect(self) -> None:
        text = self.address.get()
        if adb_server.valid_address(text) is None:
            self._say("That is not an address. Use the phone's Wi-Fi address, like 192.168.1.5.", error=True)
            return
        self._work("Connecting...", lambda: adb_server.connect(text), lambda t: f"Connected over Wi-Fi at {t}.")
