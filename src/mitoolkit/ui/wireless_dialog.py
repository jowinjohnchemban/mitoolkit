"""Phone > Wi-Fi connection: use the phone over Wi-Fi instead of a cable (not for fastboot or unlocking).

The window has one fixed size that fits a small screen, so nothing jumps when the panel changes, and Close is in a
bar at the bottom that is always visible. Pairing has two ways side by side: a QR code the phone scans, or the code
shown on the phone.
"""
from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from mitoolkit import adb, adb_server
from mitoolkit.adb_core import is_wireless
from mitoolkit.adb_usb import AdbError
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button, segmented
from mitoolkit.ui.components.placeholder import placeholder
from mitoolkit.ui.theme import MUTED, RED

QR_SIZE = 208               # pixels at 96 dpi, square: big enough for a phone camera, small enough for a laptop screen
WRAP = 452                  # text width that fits the window with its padding (never wider: it would be clipped)

NOTE = ("Backup, apps, live status and the other tools work over Wi-Fi. Fastboot and unlocking need a USB cable: "
        "the phone's bootloader has no Wi-Fi.")
QR_STEPS = ("1.  On the phone open Settings > Developer options > Wireless debugging.\n"
            "2.  Tap Pair device with QR code.\n"
            "3.  Scan the code shown here.")
CODE_STEPS = ("On the phone open Settings > Developer options > Wireless debugging > Pair device with pairing code, "
              "and keep that screen open. Then press Find Phones, or type the address and the 6-digit code it shows.")


class WirelessDialog(Dialog):
    title = "Wi-Fi Connection"
    resizable = False
    padding = 16

    def build(self) -> None:
        self._busy = False
        self._mode = "none"
        self._qr_stop_event: Optional[threading.Event] = None
        body = self.body
        k = max(1.0, self.win.winfo_fpixels("1i") / 96.0)
        self._qr_px = round(QR_SIZE * k)

        # Close lives in a bar at the bottom, packed first so it is never pushed off the window
        bar = ttk.Frame(body)
        bar.pack(side="bottom", fill="x", pady=(10, 0))
        Button(bar, text="Close", command=self.close).pack(side="right")
        self.result = ttk.Label(bar, wraplength=WRAP - 90, justify="left")           # the one status line
        self.result.pack(side="left", fill="x", expand=True)
        ttk.Separator(body).pack(side="bottom", fill="x")

        ttk.Label(body, text="Wi-Fi Connection", font=self.fonts.heading).pack(anchor="w")
        ttk.Label(body, text=NOTE, foreground=MUTED, wraplength=WRAP, justify="left").pack(anchor="w", pady=(2, 10))

        # what is connected now, with the one action that fits it (hidden when there is none)
        self.status_row = ttk.Frame(body)
        self.status_row.pack(fill="x")
        self.state = ttk.Label(self.status_row, wraplength=WRAP, justify="left")
        self.state.pack(anchor="w")
        self.action = Button(self.status_row, text="Switch to Wi-Fi", primary=True, command=self._action)

        ttk.Separator(body).pack(fill="x", pady=12)
        head = ttk.Frame(body)
        head.pack(fill="x")
        ttk.Label(head, text="Pair a New Phone", font=self.fonts.bold).pack(side="left")
        self.method = tk.StringVar(value="qr")
        self.method_bar = segmented(head, [("qr", "QR Code"), ("code", "Pairing Code")], self.method, self._show_method)
        self.method_bar.pack(side="right")
        ttk.Label(body, foreground=MUTED, wraplength=WRAP, justify="left",
                  text="Needs Android 11 or newer. Pairing is needed once: after it the phone trusts this computer and "
                       "does not ask again.").pack(anchor="w", pady=(4, 8))

        self.panels = ttk.Frame(body)                       # both panels live here; it is as tall as the taller one
        self.panels.pack(fill="x")
        self._build_qr_panel()
        self._build_code_panel()
        self.panels.update_idletasks()
        self.panels.configure(height=max(self.qr_panel.winfo_reqheight(), self.code_panel.winfo_reqheight()))
        self.panels.pack_propagate(False)

        ttk.Separator(body).pack(fill="x", pady=12)
        ttk.Label(body, text="Connect by Address", font=self.fonts.bold).pack(anchor="w")
        line = ttk.Frame(body)
        line.pack(fill="x", pady=(6, 0))
        self.address = tk.StringVar()
        entry = ttk.Entry(line, textvariable=self.address, width=24)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self._connect())
        placeholder(entry, self.address, "192.168.1.xx")
        self.connect_btn = Button(line, text="Connect", command=self._connect)
        self.connect_btn.pack(side="left", padx=8)
        ttk.Label(line, text="The phone's address. It must be paired already.", foreground=MUTED).pack(side="left")
        self._refresh()
        self._show_method()
        self.win.after(60, self._focus_first)

    def _build_qr_panel(self) -> None:
        self.qr_panel = ttk.Frame(self.panels)
        # the code (or its placeholder) keeps its place, so the window never changes size
        self.qr_canvas = tk.Canvas(self.qr_panel, width=self._qr_px, height=self._qr_px, highlightthickness=0,
                                   background="white")
        self.qr_canvas.pack(side="left", padx=(0, 16), anchor="n")
        side = ttk.Frame(self.qr_panel)
        side.pack(side="left", fill="both", expand=True)
        ttk.Label(side, text=QR_STEPS, wraplength=WRAP - self._qr_px - 24, justify="left").pack(anchor="w")
        buttons = ttk.Frame(side)
        buttons.pack(anchor="w", pady=(14, 0))
        self.qr_show = Button(buttons, text="Show QR Code", primary=True, command=self._pair_qr)
        self.qr_show.pack(side="left")
        self.qr_cancel = Button(buttons, text="Cancel", command=self._qr_stop)
        self.qr_note = ttk.Label(side, foreground=MUTED, wraplength=WRAP - self._qr_px - 24, justify="left")
        self.qr_note.pack(anchor="w", pady=(10, 0))
        self._placeholder()

    def _build_code_panel(self) -> None:
        self.code_panel = ttk.Frame(self.panels)
        ttk.Label(self.code_panel, foreground=MUTED, wraplength=WRAP, justify="left", text=CODE_STEPS).pack(anchor="w")
        find = ttk.Frame(self.code_panel)
        find.pack(fill="x", pady=(10, 0))
        self.find_btn = Button(find, text="Find Phones", command=self._find)
        self.find_btn.pack(side="left")
        pair = ttk.Frame(self.code_panel)
        pair.pack(fill="x", pady=(10, 0))
        self.pair_address = tk.StringVar()
        self.pair_code = tk.StringVar()
        only_digits = (self.win.register(lambda value: value == "" or (value.isdigit() and len(value) <= 6)), "%P")
        ttk.Label(pair, text="Pairing Address").grid(row=0, column=0, sticky="w")
        ttk.Label(pair, text="Pairing Code").grid(row=0, column=1, sticky="w", padx=(12, 0))
        pair_entry = ttk.Entry(pair, textvariable=self.pair_address, width=24)
        pair_entry.grid(row=1, column=0, sticky="w")
        self.code_entry = ttk.Entry(pair, textvariable=self.pair_code, width=9, validate="key", validatecommand=only_digits)
        self.code_entry.grid(row=1, column=1, sticky="w", padx=(12, 0))
        self.code_entry.bind("<Return>", lambda _e: self._pair())
        pair_entry.bind("<Return>", lambda _e: self.code_entry.focus_set())
        self.pair_btn = Button(pair, text="Pair", primary=True, command=self._pair)
        self.pair_btn.grid(row=1, column=2, padx=(10, 0))
        placeholder(pair_entry, self.pair_address, "192.168.1.xx:41234")
        placeholder(self.code_entry, self.pair_code, "6 digits")

    def _focus_first(self) -> None:
        """The keyboard starts on the main action of what is showing."""
        if self.alive():
            (self.qr_show if self.method.get() == "qr" else self.find_btn).focus_set()

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
        if serial and is_wireless(serial):
            self.state.configure(text=f"Connected over Wi-Fi: {serial}", foreground="")
            self.action.configure(text="Disconnect")
            self._mode = "disconnect"
        elif serial:
            self.state.configure(text="This phone is connected by USB. Switch it to Wi-Fi to unplug the cable "
                                      "(it stays on until the phone restarts).", foreground="")
            self.action.configure(text="Switch to Wi-Fi")
            self._mode = "enable"
        elif (self.app.android or {}).get("state") == "unauthorized":
            self.state.configure(text="The phone is asking you to allow this computer. Tap Allow on its screen and "
                                      "tick \"Always allow from this computer\".", foreground="")
            self._mode = "none"
        else:
            self.state.configure(text="No phone is connected over Wi-Fi yet. Pair one below, or connect by address.",
                                 foreground=MUTED)
            self._mode = "none"
        if self._mode == "none" or self._busy:           # no action that fits: no button, rather than a dead one
            self.action.pack_forget()
        else:
            self.action.pack(anchor="w", pady=(8, 0))
        # while something runs the other actions are greyed, not silently ignored (Cancel stays available)
        for button in (self.find_btn, self.pair_btn, self.connect_btn, self.qr_show):
            button.configure(state="disabled" if self._busy else "normal")

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
        self._refresh()
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
                self.app._log(f"Wi-Fi connection: {value}")
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
                self._work("Switching the phone to Wi-Fi", phone.enable_wireless, enabled)
        elif self._mode == "disconnect":
            serial = self.app._android_serial()

            def drop() -> str:
                adb_server.disconnect(serial)
                return serial
            self._work("Disconnecting", drop, lambda s: f"Disconnected {s}.")

    def _find(self) -> None:
        """Look for phones that announce Wireless debugging or the pairing screen, and fill the addresses in."""
        def found(services) -> str:
            pairing = [s for s in services if s["kind"] == "pairing"]
            connect = [s for s in services if s["kind"] == "connect"]
            if pairing:
                self.pair_address.set(pairing[0]["address"])
                self.code_entry.focus_set()
            if connect and not self.address.get():
                self.address.set(connect[0]["address"])
            if pairing:
                return f"Found the pairing screen at {pairing[0]['address']}. Type the 6-digit code from the phone."
            if connect:
                return f"Found a phone with Wireless debugging on at {connect[0]['address']}. Press Connect."
            return ("No phone found. Open Pair device with pairing code on the phone and keep it open, or type "
                    "the address shown there. Some networks hide phones from this computer (a PC on a cable and a "
                    "phone on Wi-Fi often cannot see each other): typing the address always works.")
        self._work("Looking for phones on this Wi-Fi network", adb_server.mdns_services, found, rescan=False)

    def _pair(self) -> None:
        address, code = self.pair_address.get(), self.pair_code.get()
        if adb_server.valid_address(address, require_port=True) is None:
            self._say("Use the pairing address shown on the phone, with its port, like 192.168.1.xx:41234.", error=True)
            return
        if not re.fullmatch(r"\d{6}", code.strip()):
            self._say("The pairing code is the 6 digits shown on the phone.", error=True)
            return

        def paired(result) -> str:
            self.pair_code.set("")                         # the code works once; do not leave it on screen
            return self._paired_message(result)
        self._work("Pairing", lambda: self._connect_announced(adb_server.pair(address, code)), paired)

    @staticmethod
    def _connect_announced(target: str, wait: float = 30.0, poll: float = 1.5):
        """After pairing: connect to the phone's Wireless debugging port. It is announced on the network a few seconds
        after pairing; where the network does not deliver announcements (a PC on a cable and a phone on Wi-Fi often
        cannot hear each other) the port is looked for on the phone's address instead. Keeps trying for up to ``wait``
        seconds. Returns (address, True) when connected, or (pairing address, False) when it did not work out."""
        import time
        host = target.rsplit(":", 1)[0]
        end = time.monotonic() + wait
        while True:
            try:
                for service in adb_server.mdns_services():
                    if service["kind"] == "connect" and service["address"].startswith(host + ":"):
                        return adb_server.connect(service["address"]), True
            except AdbError:
                # mDNS is slow to start or blocked: the direct search below covers it
                pass
            try:
                return adb_server.find_on_host(host), True
            except AdbError:
                # the phone is not listening yet (it starts a few seconds after pairing): try again until time is up
                pass
            if time.monotonic() >= end:
                return target, False
            time.sleep(poll)

    def _paired_message(self, result) -> str:
        self.app.use_wireless()                            # the phone is on Wi-Fi now: list it as soon as it connects
        self.app.expect_wifi_phone()                       # and look for it again right away
        if result[1]:
            return f"Paired and connected at {result[0]}. This computer is trusted, so no prompt on the phone."
        return ("Paired. MiToolkit keeps looking and connects as soon as the phone is ready. If it does not, enter "
                "the IP address & port from the Wireless debugging screen below and press Connect.")

    # ------------------------------------------------------------------------------------------- pairing by QR
    def _show_method(self) -> None:
        """Show the QR panel or the code panel, whichever is chosen. Leaving the QR panel stops waiting for a scan."""
        qr = self.method.get() == "qr"
        if not qr:
            self._qr_stop()
        self.code_panel.pack_forget()
        self.qr_panel.pack_forget()
        (self.qr_panel if qr else self.code_panel).pack(fill="both", expand=True)
        self._focus_first()

    def _pair_qr(self) -> None:
        """Show a one-time QR code, then wait for the phone to scan it, find it on the network and pair."""
        if self._busy:
            return
        request = adb_server.pairing_qr()
        self.draw_qr(request["payload"])
        self.qr_show.pack_forget()
        self.qr_cancel.pack(side="left")
        self.qr_note.configure(text="Waiting for the phone to scan the code. It is valid for 2 minutes.")
        self._qr_stop_event = stop = threading.Event()

        def pair_by_scan():
            target = adb_server.wait_for_qr_pairing(request["name"], request["password"], stop)
            return self._connect_announced(target)

        def done(result) -> str:
            self._qr_reset()
            return self._paired_message(result)
        self._work("Waiting for the phone to scan the code", pair_by_scan, done, on_error=self._qr_reset)

    def _qr_stop(self) -> None:
        if self._qr_stop_event is not None:
            self._qr_stop_event.set()                      # the wait ends within a couple of seconds
        self._qr_reset()

    def _qr_reset(self) -> None:
        """Back to the button: the code on screen is spent (it was scanned, cancelled or timed out)."""
        self._qr_stop_event = None
        if self.alive():
            self._placeholder()
            self.qr_cancel.pack_forget()
            self.qr_show.pack(side="left")
            self.qr_note.configure(text="")

    def _placeholder(self) -> None:
        """An empty, dashed frame where the code will appear."""
        c, n = self.qr_canvas, self._qr_px
        c.delete("all")
        c.create_rectangle(8, 8, n - 8, n - 8, outline="#c3c8d0", dash=(5, 4), width=2)
        c.create_text(n / 2, n / 2, text="The QR Code\nAppears Here", fill="#6b7280", justify="center",
                      font=self.fonts.base)

    def draw_qr(self, text: str) -> None:
        """Draw ``text`` as a QR code: black modules on white, with the quiet border scanners need."""
        import qrcode
        code = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
        code.add_data(text)
        code.make(fit=True)
        matrix = code.get_matrix()
        quiet = 4                                           # modules of white around it
        cell = max(2, self._qr_px // (len(matrix) + 2 * quiet))
        offset = (self._qr_px - cell * (len(matrix) + 2 * quiet)) // 2            # centred in the white square
        canvas = self.qr_canvas
        canvas.delete("all")
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    canvas.create_rectangle(offset + (x + quiet) * cell, offset + (y + quiet) * cell,
                                            offset + (x + quiet + 1) * cell, offset + (y + quiet + 1) * cell,
                                            fill="black", outline="black")

    def close(self) -> None:
        if self._qr_stop_event is not None:
            self._qr_stop_event.set()                      # do not leave a wait running after the window is gone
        super().close()

    def _connect(self) -> None:
        text = self.address.get()
        if adb_server.valid_address(text) is None:
            self._say("That is not an address. Use the phone's Wi-Fi address, like 192.168.1.xx.", error=True)
            return

        def connected(target) -> str:
            self.app.use_wireless()
            return f"Connected over Wi-Fi at {target}."
        label = "Connecting" if ":" in text else "Looking for the phone's port, which takes a few seconds"
        self._work(label, lambda: adb_server.connect(text), connected)
