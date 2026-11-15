"""The window's menu bar: File, Unlock, Phone, View, Help.

Follows each platform's habits: Alt+letter mnemonics and Ctrl shortcuts on Windows and Linux,
the Command key on macOS. Entries that cannot work right now (no phone, signed out, busy) are
greyed out each time a menu opens, and their keyboard shortcuts do nothing while greyed.

The unlock itself is deliberately not in any menu: it erases the phone, so it is only
reachable through the guarded button (tick the box, type the phone's name).
"""
from __future__ import annotations

import sys
import tkinter as tk
import webbrowser
from typing import Callable, List, Optional, Tuple

from mitoolkit import drivers, log, settings, updater
from mitoolkit.ui.theme import DOCS, REPO

MAC = sys.platform == "darwin"
MOD_EVENT = "Command" if MAC else "Control"
MOD_TEXT = "⌘" if MAC else "Ctrl+"


class MenuBar:
    """Builds the bar for `app` (the gui.App) and keeps its entries in step with the app's state."""

    def __init__(self, app):
        self.app = app
        self._entries: List[Tuple[tk.Menu, int, Callable[[], bool]]] = []
        root = app.root
        bar = tk.Menu(root, tearoff=0)
        if not MAC:
            # A native menu bar has no padding setting, so "File" would touch the window edge.
            # A blank, disabled first entry gives it breathing room (the macOS bar is the system's).
            bar.add_command(label=" " * 3, state="disabled")
        self._file(bar)
        self._unlock(bar)
        self._phone(bar)
        self._view(bar)
        self._help(bar)
        root.config(menu=bar)

    # ------------------------------------------------------------- helpers
    def _add(self, menu: tk.Menu, label: str, command: Callable[[], None], key: Optional[str] = None,
             shortcut: Optional[str] = None, enabled: Callable[[], bool] = lambda: True) -> None:
        """Add an entry. `&` in the label marks its Alt mnemonic. `key` is the event name
        (without the modifier, e.g. "q" or "F5") and `shortcut` the text shown beside it."""
        underline = label.find("&")
        label = label.replace("&", "", 1)
        kwargs = {"label": label, "command": command}
        if underline >= 0 and not MAC:
            kwargs["underline"] = underline
        if shortcut:
            kwargs["accelerator"] = shortcut
        menu.add_command(**kwargs)
        self._entries.append((menu, menu.index("end"), enabled))
        if key:
            self.app.root.bind_all(f"<{key}>", lambda _e: self._fire(command, enabled))

    @staticmethod
    def _fire(command: Callable[[], None], enabled: Callable[[], bool]) -> str:
        if enabled():
            command()
        return "break"

    def _menu(self, bar: tk.Menu, label: str) -> tk.Menu:
        underline = label.find("&")
        menu = tk.Menu(bar, tearoff=0, postcommand=self.refresh)
        kwargs = {"label": label.replace("&", "", 1), "menu": menu}
        if underline >= 0 and not MAC:
            kwargs["underline"] = underline
        bar.add_cascade(**kwargs)
        return menu

    @staticmethod
    def _ctrl(letter: str) -> Tuple[str, str]:
        """(event, text shown) for a modifier+letter shortcut, e.g. Ctrl+L or Command-L."""
        return f"{MOD_EVENT}-{letter.lower()}", f"{MOD_TEXT}{letter.upper()}"

    def refresh(self) -> None:
        """Grey out the entries that cannot work right now. Runs whenever a menu opens."""
        for menu, index, enabled in self._entries:
            try:
                ok = bool(enabled())
            except Exception:  # a broken predicate must never break the menu
                ok = False
            menu.entryconfigure(index, state="normal" if ok else "disabled")

    # --------------------------------------------------------------- state
    def _idle(self) -> bool:
        return not self.app.busy

    def _signed_in(self) -> bool:
        return self.app.token is not None

    def _on_android(self) -> bool:
        return self._idle() and self.app._android_serial() is not None

    def _in_fastboot(self) -> bool:
        return self._idle() and bool(self.app.fastboot) and bool(self.app.device)

    # --------------------------------------------------------------- menus
    def _file(self, bar: tk.Menu) -> None:
        app, m = self.app, self._menu(bar, "&File")
        key, text = self._ctrl("l")
        self._add(m, "&Activity Log", app._toggle_details, key, text)
        m.add_separator()
        self._add(m, "&Sign Out and Delete Saved Session", app._sign_out)
        m.add_separator()
        key, text = self._ctrl("q")
        self._add(m, "&Quit", app.root.destroy, key, text)

    def _unlock(self, bar: tk.Menu) -> None:
        app, m = self.app, self._menu(bar, "&Unlock")
        self._add(m, "&Sign In to Mi Account", app._login, enabled=lambda: self._idle() and not self._signed_in())
        # no Ctrl+E: Tk text fields use it ("end of line"), so it would also fire while typing
        self._add(m, "Check &Eligibility", app._check,
                  enabled=lambda: (self._signed_in() and self._idle() and bool(app.device) and not app.unlocked))

    def _phone(self, bar: tk.Menu) -> None:
        app, m = self.app, self._menu(bar, "&Phone")
        self._add(m, "&Rescan", app._rescan, "F5", "F5", enabled=self._idle)
        m.add_separator()
        self._add(m, "Re&start or Power Off", app._restart_dialog,
                  enabled=lambda: self._on_android() or self._in_fastboot())
        m.add_separator()
        self._add(m, "&Back Up Files", app._backup_dialog, enabled=self._on_android)
        self._add(m, "Manage &Apps", app._apps_dialog, enabled=self._on_android)
        self._add(m, "Security &Check", app._security_dialog, enabled=self._on_android)
        self._add(m, "&Live Status", app._live_dialog, enabled=self._on_android)
        self._add(m, "C&onnections and Signal", app._connect_dialog, enabled=self._on_android)
        self._add(m, "Log V&iewer", app._log_dialog, enabled=self._on_android)
        m.add_separator()
        self._add(m, "&Wi-Fi Connection", app._wireless_dialog, enabled=self._idle)
        self._add(m, "Copy Device &Details", app._copy_device, enabled=lambda: bool(app._device_pairs()))
        self._add(m, "&Export Device Details", app._export_device, enabled=lambda: bool(app._device_pairs()))
        self._add(m, "Stop &Google's ADB", app._stop_google_adb,
                  enabled=lambda: self._idle() and bool((app.android or {}).get("adb_running")))

    def _view(self, bar: tk.Menu) -> None:
        app, m = self.app, self._menu(bar, "&View")
        text = MOD_TEXT
        self._add(m, "&Larger Text", lambda: app._zoom(+1), f"{MOD_EVENT}-equal", "⌘+" if MAC else f"{text}Plus")
        self._add(m, "&Smaller Text", lambda: app._zoom(-1), f"{MOD_EVENT}-minus", "⌘-" if MAC else f"{text}Minus")
        self._add(m, "&Normal Text Size", lambda: app._zoom(0), f"{MOD_EVENT}-Key-0", f"{text}0")
        # the same keys on the numeric keypad, and "+" typed with Shift
        for event, step in ((f"{MOD_EVENT}-plus", 1), (f"{MOD_EVENT}-KP_Add", 1), (f"{MOD_EVENT}-KP_Subtract", -1)):
            app.root.bind_all(f"<{event}>", lambda _e, d=step: app._zoom(d))

    def _help(self, bar: tk.Menu) -> None:
        app, m = self.app, self._menu(bar, "&Help")
        self._add(m, "&Step-by-Step Guide", app._open_guide, "F1", "F1")
        if drivers.supported():
            self._add(m, "&USB Driver Help", app._driver_help)
        m.add_separator()
        docs = tk.Menu(m, tearoff=0)
        for label, page in (("Full Unlock Guide", "unlock-guide.md"), ("Safety Model", "safety.md"),
                            ("Error Codes", "error-codes.md"), ("FAQ", "faq.md")):
            docs.add_command(label=label, command=lambda p=page: webbrowser.open(DOCS + p))
        m.add_cascade(label="Online Documentation", menu=docs, **({} if MAC else {"underline": 0}))
        self._add(m, "Report a &Problem", lambda: webbrowser.open(REPO + "/issues"))
        self._add(m, "&AI Agent Connection", app._agent_dialog)
        self.debug_var = tk.BooleanVar(value=log.debug_enabled())
        m.add_checkbutton(label="Debug Logging", variable=self.debug_var, command=lambda: log.set_debug(
            self.debug_var.get()), **({} if MAC else {"underline": 0}))
        m.add_separator()
        self._add(m, "Check and &Fix Problems", app._doctor_dialog)
        self._add(m, "Check for &Updates", app._update_dialog)
        self.auto_var = tk.BooleanVar(value=updater.auto_enabled())
        m.add_checkbutton(label="Check for Updates Automatically", variable=self.auto_var, command=lambda: settings.set(
            "auto_update_check", self.auto_var.get()))
        m.add_separator()
        self._add(m, "&About MiToolkit", app._about)
