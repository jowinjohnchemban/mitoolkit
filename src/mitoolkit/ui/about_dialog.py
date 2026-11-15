"""Help > About: what this is, which version, and where to get help. Short on purpose."""
from __future__ import annotations

import platform
import sys
import webbrowser

from tkinter import ttk

from mitoolkit import build
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button
from mitoolkit.ui.theme import MUTED, REPO


def version_text() -> str:
    """What a bug report needs: the program, Python and the system."""
    return f"MiToolkit {build.full_version()}\nPython {sys.version.split()[0]}\n{platform.platform()}"


class AboutDialog(Dialog):
    title = "About MiToolkit"
    resizable = False
    padding = 20

    def build(self) -> None:
        body = self.body
        ttk.Label(body, text="MiToolkit", font=self.fonts.heading).pack(anchor="w")
        ttk.Label(body, text=build.full_version(), foreground=MUTED).pack(anchor="w")
        ttk.Label(body, wraplength=360, justify="left", text=(
            "Unlock the bootloader of Xiaomi, Redmi and POCO phones with Xiaomi's own service, and look "
            "after the phone before and after: details, live status, connections, backup, apps and a "
            "security check.")).pack(anchor="w", pady=(10, 0))
        ttk.Label(body, wraplength=360, justify="left", foreground=MUTED,
                  text="Apache License 2.0. Not affiliated with Xiaomi.").pack(anchor="w", pady=(10, 0))

        links = ttk.Frame(body)
        links.pack(fill="x", pady=(14, 0))
        Button(links, text="Credits", command=lambda: webbrowser.open(REPO + "/blob/main/CREDITS.md")).pack(side="left")
        Button(links, text="Website", command=lambda: webbrowser.open(REPO)).pack(side="left", padx=6)
        Button(links, text="Copy Version Info", command=self._copy).pack(side="left")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(14, 0))
        Button(row, text="Close", primary=True, command=self.close).pack(side="right")

    def _copy(self) -> None:
        self.win.clipboard_clear()
        self.win.clipboard_append(version_text())
        self.app._set_status("Version information copied.")
