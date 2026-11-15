"""Help > USB driver help: the steps, and links to Google's download page and Device Manager."""
from __future__ import annotations

from tkinter import ttk

from mitoolkit import drivers
from mitoolkit.ui.components.buttons import Button
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.theme import MUTED


class DriverHelpDialog(Dialog):
    title = "USB driver for Windows"
    resizable = False
    padding = 16

    def build(self) -> None:
        body = self.body
        ttk.Label(body, text="Install Google's USB driver", font=self.fonts.heading).pack(anchor="w")
        ttk.Label(body, foreground=MUTED, wraplength=520, justify="left",
                  text="Needed only if Windows shows the phone with a yellow mark, or mitoolkit says it "
                       "can't open it.").pack(anchor="w", pady=(2, 10))
        for i, step in enumerate(drivers.STEPS, 1):
            row = ttk.Frame(body)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"{i}.", font=self.fonts.bold, width=3).pack(side="left", anchor="n")
            ttk.Label(row, text=step, wraplength=480, justify="left").pack(side="left", fill="x")
        ttk.Label(body, text=drivers.NOTE, foreground=MUTED, font=self.fonts.small, wraplength=520,
                  justify="left").pack(anchor="w", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        Button(buttons, text="Open Google's download page", primary=True,
               command=drivers.open_download_page).pack(side="left")
        Button(buttons, text="Open Device Manager", command=self._device_manager).pack(side="left", padx=6)
        Button(buttons, text="Close", command=self.close).pack(side="right")

    def _device_manager(self) -> None:
        try:
            drivers.open_device_manager()
        except OSError as err:
            self.app.log(f"Could not open Device Manager: {err}")
