"""Phone > Wireless adb: use the phone over Wi-Fi instead of a cable (not for fastboot or unlocking)."""
from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from mitoolkit import adb, adb_server
from mitoolkit.adb_usb import AdbError
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button
from mitoolkit.ui.theme import MUTED, RED

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
        ttk.Label(body, text="Pair a new phone (no cable)", font=self.fonts.bold).pack(anchor="w")
        ttk.Label(body, foreground=MUTED, wraplength=470, justify="left",
                  text="Android 11 or newer. On the phone open Settings > Developer options > Wireless debugging > "
                       "Pair device with pairing code, and leave that screen open. Pairing makes the phone trust "
                       "this computer, so it does not ask to allow debugging again.").pack(anchor="w", pady=(2, 6))
        find = ttk.Frame(body)
        find.pack(fill="x")
        self.find_btn = Button(find, text="Find phones on Wi-Fi", command=self._find)
        self.find_btn.pack(side="left")
        pair = ttk.Frame(body)
        pair.pack(fill="x", pady=(8, 0))
        self.pair_address = tk.StringVar()
        self.pair_code = tk.StringVar()
        ttk.Label(pair, text="Pairing address").grid(row=0, column=0, sticky="w")
        ttk.Label(pair, text="Pairing code").grid(row=0, column=1, sticky="w", padx=(10, 0))
        pair_entry = ttk.Entry(pair, textvariable=self.pair_address, width=24)
        pair_entry.grid(row=1, column=0, sticky="w")
        code_entry = ttk.Entry(pair, textvariable=self.pair_code, width=10)
        code_entry.grid(row=1, column=1, sticky="w", padx=(10, 0))
        code_entry.bind("<Return>", lambda _e: self._pair())
        self.pair_btn = Button(pair, text="Pair", command=self._pair)
        self.pair_btn.grid(row=1, column=2, padx=8)

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
        elif (self.app.android or {}).get("state") == "unauthorized":
            self.state.configure(text="The phone is asking you to allow this computer. Tap Allow on its screen and "
                                      "tick \"Always allow from this computer\".", foreground="")
            self.action.configure(text="Turn on Wi-Fi debugging")
            self._mode = "none"
        else:
            self.state.configure(text="No phone is connected by USB. Plug it in once to switch it to Wi-Fi, pair "
                                      "it below, or connect by address.", foreground=MUTED)
            self.action.configure(text="Turn on Wi-Fi debugging")
            self._mode = "none"
        self.action.configure(state="normal" if self._mode != "none" and not self._busy else "disabled")

    # --------------------------------------------------------------- actions
    def _say(self, text: str, error: bool = False) -> None:
        if self.alive():
            self.result.configure(text=text, foreground=RED if error else MUTED)

    def _work(self, label: str, work: Callable[[], Any], then: Callable[[Any], str], rescan: bool = True) -> None:
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
                message = then(value)
                self._say(message)
                self.app._log(message)
                if rescan:
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

    def _find(self) -> None:
        """Look for phones that announce Wireless debugging or the pairing screen, and fill the addresses in."""
        def found(services) -> str:
            pairing = [s for s in services if s["kind"] == "pairing"]
            connect = [s for s in services if s["kind"] == "connect"]
            if pairing:
                self.pair_address.set(pairing[0]["address"])
            if connect and not self.address.get():
                self.address.set(connect[0]["address"])
            if pairing:
                return f"Found the pairing screen at {pairing[0]['address']}. Type the 6-digit code from the phone."
            if connect:
                return f"Found a phone with Wireless debugging on at {connect[0]['address']}. Press Connect."
            return ("No phone found. Open Pair device with pairing code on the phone (and keep it open), or type "
                    "the address shown there.")
        self._work("Looking for phones on this Wi-Fi network...", adb_server.mdns_services, found, rescan=False)

    def _pair(self) -> None:
        address, code = self.pair_address.get(), self.pair_code.get()
        if adb_server.valid_address(address, require_port=True) is None:
            self._say("Use the pairing address shown on the phone, with its port, like 192.168.1.5:41234.", error=True)
            return
        if not re.fullmatch(r"\d{6}", code.strip()):
            self._say("The pairing code is the 6 digits shown on the phone.", error=True)
            return

        def pair_and_connect():
            target = adb_server.pair(address, code)
            host = target.rsplit(":", 1)[0]
            try:                                           # the phone announces where to connect once it is paired
                for service in adb_server.mdns_services():
                    if service["kind"] == "connect" and service["address"].startswith(host + ":"):
                        return adb_server.connect(service["address"]), True
            except AdbError:
                pass
            return target, False

        def paired(result) -> str:
            self.pair_code.set("")                         # the code works once; do not leave it on screen
            if result[1]:
                return f"Paired and connected at {result[0]}. This computer is trusted, so no prompt on the phone."
            return ("Paired. Now enter the IP address & port from the Wireless debugging screen below and press "
                    "Connect.")
        self._work("Pairing...", pair_and_connect, paired)

    def _connect(self) -> None:
        text = self.address.get()
        if adb_server.valid_address(text) is None:
            self._say("That is not an address. Use the phone's Wi-Fi address, like 192.168.1.5.", error=True)
            return
        self._work("Connecting...", lambda: adb_server.connect(text), lambda t: f"Connected over Wi-Fi at {t}.")
