"""Phone > Restart or power off: choose where the phone goes next. Nothing is erased by any choice."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from mitoolkit.adb_core import is_wireless
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button
from mitoolkit.ui.theme import MUTED

ANDROID_CHOICES = (
    ("android", "Android", "Restart normally."),
    ("recovery", "Recovery mode", "For updates, a factory reset from the phone, or a custom recovery."),
    ("fastboot", "Fastboot mode", "Needed to unlock. Works over a USB cable only."),
    ("off", "Power off", "It stays off until you press the power button."),
)
FASTBOOT_CHOICES = (
    ("android", "Cancel and start Android", "Leave fastboot mode and start normally. Nothing is changed."),
    ("recovery", "Recovery mode", "Leave fastboot mode and start recovery."),
)


class RestartDialog(Dialog):
    title = "Restart phone"
    resizable = False
    padding = 16

    def build(self) -> None:
        body = self.body
        in_fastboot = bool(self.app.device)
        ttk.Label(body, text="Where should the phone go?" if not in_fastboot else "Leave fastboot mode",
                  font=self.fonts.heading).pack(anchor="w")
        ttk.Label(body, foreground=MUTED, text="Nothing is erased by any of these. Unsaved work on the phone is lost."
                  ).pack(anchor="w", pady=(2, 10))
        wifi = is_wireless(self.app._android_serial() or "")
        choices = FASTBOOT_CHOICES if in_fastboot else ANDROID_CHOICES
        self.choice = tk.StringVar(value=choices[0][0])
        for key, label, note in choices:
            row = ttk.Frame(body)
            row.pack(fill="x", pady=3)
            radio = ttk.Radiobutton(row, text=label, value=key, variable=self.choice)
            radio.pack(anchor="w")
            if key == "fastboot" and wifi:
                note = "Not over Wi-Fi: plug in a USB cable first."
                radio.configure(state="disabled")
            ttk.Label(row, text=note, foreground=MUTED).pack(anchor="w", padx=(24, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        Button(buttons, text="Cancel", command=self.close).pack(side="right")
        self.go = Button(buttons, text="Restart", primary=True, command=self._go)
        self.go.pack(side="right", padx=6)
        self.choice.trace_add("write", lambda *_: self._label())
        self._label()

    def _label(self) -> None:
        self.go.configure(text="Power off" if self.choice.get() == "off" else "Restart")

    def _go(self) -> None:
        mode = self.choice.get()
        self.close()
        self.app.restart_to(mode)
