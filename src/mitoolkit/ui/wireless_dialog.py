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
from mitoolkit.ui.components.buttons import Button, segmented
from mitoolkit.ui.placement import fit_to_screen
from mitoolkit.ui.theme import MUTED, RED

QR_SIZE = 208               # pixels, square: big enough for a phone camera, small enough for a laptop screen

NOTE =("Wireless adb covers backup, apps, live status and the other tools. Fastboot mode and unlocking work "
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
        head = ttk.Frame(body)
        head.pack(fill="x")
        ttk.Label(head, text="Pair a new phone (no cable)", font=self.fonts.bold).pack(side="left")
        self.method = tk.StringVar(value="qr")
        self.method_bar = segmented(head, [("qr", "QR code"), ("code", "Pairing code")], self.method, self._show_method)
        self.method_bar.pack(side="right")
        ttk.Label(body, foreground=MUTED, wraplength=470, justify="left",
                  text="Android 11 or newer. Pairing makes the phone trust this computer, so it does not ask to "
                       "allow debugging again. On the phone: Settings > Developer options > Wireless debugging.").pack(
            anchor="w", pady=(4, 6))

        # --- pair with a QR code: the phone scans it, MiToolkit finds the phone on the network and pairs
        self.qr_panel = ttk.Frame(body)
        ttk.Label(self.qr_panel, foreground=MUTED, wraplength=470, justify="left",
                  text="Choose Pair device with QR code on the phone and scan the code shown here.").pack(anchor="w")
        qr_row = ttk.Frame(self.qr_panel)
        qr_row.pack(fill="x", pady=(8, 0))
        self.qr_canvas = tk.Canvas(qr_row, width=QR_SIZE, height=QR_SIZE, highlightthickness=0, background="white")
        self.qr_show = Button(qr_row, text="Show QR code", primary=True, command=self._pair_qr)
        self.qr_show.pack(side="left", anchor="n")
        self.qr_cancel = Button(qr_row, text="Cancel", command=self._qr_stop)

        # --- pair with the code shown on the phone
        self.code_panel = ttk.Frame(body)
        ttk.Label(self.code_panel, foreground=MUTED, wraplength=470, justify="left",
                  text="Choose Pair device with pairing code on the phone, keep that screen open, and enter the "
                       "address and the 6-digit code it shows.").pack(anchor="w")
        find = ttk.Frame(self.code_panel)
        find.pack(fill="x", pady=(6, 0))
        self.find_btn = Button(find, text="Find phones on Wi-Fi", command=self._find)
        self.find_btn.pack(side="left")
        pair = ttk.Frame(self.code_panel)
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
        self._qr_stop_event: Optional[threading.Event] = None
        self.pair_anchor = ttk.Separator(body)             # the pairing panels are placed above this line
        self.pair_anchor.pack(fill="x", pady=14)
        self._show_method()

        self.connect_box = ttk.Frame(body)                 # hidden while a QR code waits, so the window stays small
        self.connect_box.pack(fill="x")
        ttk.Label(self.connect_box, text="Connect by address", font=self.fonts.bold).pack(anchor="w")
        ttk.Label(self.connect_box, foreground=MUTED, wraplength=470, justify="left",
                  text="For a phone already set to Wi-Fi debugging. Example: 192.168.1.5").pack(
            anchor="w", pady=(2, 6))
        line = ttk.Frame(self.connect_box)
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

    def _work(self, label: str, work: Callable[[], Any], then: Callable[[Any], str], rescan: bool = True,
              on_error: Optional[Callable[[], None]] = None) -> None:
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
                if on_error is not None:
                    on_error()
            self._refresh()

        self.win.after(150, poll)

    def _action(self) -> None:
        if self._mode == "enable":
            phone = self._phone()
            if phone is not None:
                def enabled(target) -> str:
                    self.app.use_wireless()
                    return f"Connected over Wi-Fi at {target}. You can unplug the USB cable now (not for fastboot)."
                self._work("Switching the phone to Wi-Fi...", phone.enable_wireless, enabled)
        elif self._mode == "disconnect":
            serial = self.app._android_serial()

            def drop() -> str:
                adb_server.disconnect(serial)
                return serial
            self._work("Disconnecting...", drop, lambda s: f"Disconnected {s}.")

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

        def paired(result) -> str:
            self.pair_code.set("")                         # the code works once; do not leave it on screen
            return self._paired_message(result)
        self._work("Pairing...", lambda: self._connect_announced(adb_server.pair(address, code)), paired)

    @staticmethod
    def _connect_announced(target: str):
        """After pairing: connect to the address the phone announces for Wireless debugging. Returns (address, True)
        when connected, or (pairing address, False) when it could not be found (the person then connects by address)."""
        host = target.rsplit(":", 1)[0]
        try:                                               # the phone announces where to connect once it is paired
            for service in adb_server.mdns_services():
                if service["kind"] == "connect" and service["address"].startswith(host + ":"):
                    return adb_server.connect(service["address"]), True
        except AdbError:
            # Pairing itself worked. Finding or reaching the connect address failed (mDNS blocked on this
            # network, say), so the person is told to connect by address instead of seeing an error.
            pass
        return target, False

    def _paired_message(self, result) -> str:
        if result[1]:
            self.app.use_wireless()                        # the phone is on Wi-Fi now: list it
            return f"Paired and connected at {result[0]}. This computer is trusted, so no prompt on the phone."
        return "Paired. Now enter the IP address & port from the Wireless debugging screen below and press Connect."

    # ------------------------------------------------------------------------------------------- pairing by QR
    def _show_method(self) -> None:
        """Show the QR panel or the code panel, whichever is chosen. Leaving the QR panel stops waiting for a scan."""
        qr = self.method.get() == "qr"
        if not qr:
            self._qr_stop()
        self.code_panel.pack_forget()
        self.qr_panel.pack_forget()
        (self.qr_panel if qr else self.code_panel).pack(fill="x", before=self.pair_anchor)

    def _pair_qr(self) -> None:
        """Show a one-time QR code, then wait for the phone to scan it, find it on the network and pair."""
        if self._busy:
            return
        request = adb_server.pairing_qr()
        self.draw_qr(request["payload"])
        self.qr_canvas.pack(side="left", padx=(0, 12))
        self.qr_show.pack_forget()
        self.qr_cancel.pack(side="left", anchor="n")
        self.connect_box.pack_forget()
        self._refit()
        self._qr_stop_event = stop = threading.Event()

        def pair_by_scan():
            target = adb_server.wait_for_qr_pairing(request["name"], request["password"], stop)
            return self._connect_announced(target)

        def done(result) -> str:
            self._qr_reset()
            return self._paired_message(result)
        self._work("Waiting for the phone to scan the code...", pair_by_scan, done, on_error=self._qr_reset)

    def _qr_stop(self) -> None:
        if self._qr_stop_event is not None:
            self._qr_stop_event.set()                      # the wait ends within a couple of seconds
        self._qr_reset()

    def _qr_reset(self) -> None:
        """Back to the button: the code on screen is spent (it was scanned, cancelled or timed out)."""
        self._qr_stop_event = None
        if self.alive():
            self.qr_canvas.pack_forget()
            self.qr_cancel.pack_forget()
            self.qr_show.pack(side="left", anchor="n")
            self.connect_box.pack(fill="x", before=self.result)
            self._refit()

    def _refit(self) -> None:
        """Resize the window to its content (the QR code makes it taller, and it must still fit the screen)."""
        self.win.update_idletasks()
        fit_to_screen(self.win, self.win.winfo_reqwidth(), self.win.winfo_reqheight())

    def draw_qr(self, text: str) -> None:
        """Draw ``text`` as a QR code: black modules on white, with the quiet border scanners need."""
        import qrcode
        code = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
        code.add_data(text)
        code.make(fit=True)
        matrix = code.get_matrix()
        quiet = 4                                           # modules of white around it
        cell = max(2, QR_SIZE // (len(matrix) + 2 * quiet))
        canvas = self.qr_canvas
        canvas.delete("all")
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    canvas.create_rectangle((x + quiet) * cell, (y + quiet) * cell, (x + quiet + 1) * cell,
                                            (y + quiet + 1) * cell, fill="black", outline="black")

    def close(self) -> None:
        if self._qr_stop_event is not None:
            self._qr_stop_event.set()                      # do not leave a wait running after the window is gone
        super().close()

    def _connect(self) -> None:
        text = self.address.get()
        if adb_server.valid_address(text) is None:
            self._say("That is not an address. Use the phone's Wi-Fi address, like 192.168.1.5.", error=True)
            return
        self._work("Connecting...", lambda: adb_server.connect(text), lambda t: f"Connected over Wi-Fi at {t}.")
