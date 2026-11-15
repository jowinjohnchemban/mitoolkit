"""Help > AI agent connection: let an AI agent use this MiToolkit (MCP in the app), with the address, the token and the
settings to copy. Off until the person turns it on; the token changes every time."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from mitoolkit import mcp_http
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.components.buttons import Button
from mitoolkit.ui.theme import GREEN, MUTED

WRAP = 460
NOTE = ("Let an AI agent, or any program that speaks MCP, use this MiToolkit: it can read what the phone reports and "
        "run the checks on the phone that is connected here. It cannot unlock the phone. Anything that changes the "
        "phone, or uses your saved sign-in, asks you first in this window.")
WARNING = ("The token changes every time you turn this on. Anyone who has it can use these tools while this is on, "
           "so keep it to yourself. It works on this computer only.")


class AgentDialog(Dialog):
    title = "AI Agent Connection"
    resizable = False
    padding = 16

    def build(self) -> None:
        body = self.body
        ttk.Label(body, text="AI Agent Connection", font=self.fonts.heading).pack(anchor="w")
        ttk.Label(body, text=NOTE, foreground=MUTED, wraplength=WRAP, justify="left").pack(anchor="w", pady=(2, 10))

        bar = ttk.Frame(body)
        bar.pack(side="bottom", fill="x", pady=(12, 0))
        Button(bar, text="Close", command=self.close).pack(side="right")
        self.copied = ttk.Label(bar, foreground=GREEN)
        self.copied.pack(side="left")
        ttk.Separator(body).pack(side="bottom", fill="x")

        row = ttk.Frame(body)
        row.pack(fill="x")
        self.switch = Button(row, text="Turn On", primary=True, command=self._toggle)
        self.switch.pack(side="left")
        self.state = ttk.Label(row, text="Off")
        self.state.pack(side="left", padx=12)

        # the fields keep their place whether it is on or off, so the window never changes size
        form = ttk.Frame(body)
        form.pack(fill="x", pady=(12, 0))
        form.columnconfigure(1, weight=1)
        self.address, self.token = tk.StringVar(), tk.StringVar()
        self.copy_buttons = []
        for i, (label, var, what) in enumerate((("Address", self.address, "the address"), ("Token", self.token, "the token"))):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
            ttk.Entry(form, textvariable=var, state="readonly", width=44).grid(row=i, column=1, sticky="ew", pady=3)
            button = Button(form, text="Copy", command=lambda v=var, w=what: self._copy(v.get(), w))
            button.grid(row=i, column=2, padx=(8, 0), pady=3)
            self.copy_buttons.append(button)
        # one choice and one button: the settings text for the client you use (any MCP client reads the first)
        more = ttk.Frame(body)
        more.pack(fill="x", pady=(8, 0))
        ttk.Label(more, text="Settings For").pack(side="left", padx=(0, 10))
        self.format = tk.StringVar(value=mcp_http.FORMATS[0][1])
        self.format_box = ttk.Combobox(more, textvariable=self.format, state="readonly", width=26,
                                       values=[name for _key, name in mcp_http.FORMATS])
        self.format_box.pack(side="left")
        self.settings_btn = Button(more, text="Copy Settings", command=self._copy_settings)
        self.settings_btn.pack(side="left", padx=8)
        self.copy_buttons.append(self.settings_btn)
        ttk.Label(body, text=WARNING, foreground=MUTED, wraplength=WRAP, justify="left").pack(anchor="w", pady=(10, 0))

        ttk.Label(body, text="Recent Use", font=self.fonts.bold).pack(anchor="w", pady=(12, 2))
        self.recent = tk.Text(body, height=5, width=60, wrap="none", borderwidth=1, relief="solid", state="disabled",
                              font=self.fonts.small, takefocus=0)
        self.recent.pack(fill="x")
        self._refresh()
        self._poll()
        self.win.after(60, self.switch.focus_set)

    # ----------------------------------------------------------------------------------------------- state
    def _server(self):
        return self.app._agent

    def _toggle(self) -> None:
        if self._server() is None:
            try:
                self.app.agent_start()
            except OSError as err:
                self.state.configure(text=f"Could not turn it on ({err.strerror or err.__class__.__name__}).")
                return
        else:
            self.app.agent_stop()
        self._refresh()

    def _refresh(self) -> None:
        server = self._server()
        on = server is not None
        self.switch.configure(text="Turn Off" if on else "Turn On")
        self.state.configure(text="On: agents on this computer can connect" if on else "Off", foreground=GREEN if on else "")
        self.address.set(server.url if on else "")
        self.token.set(server.token if on else "")
        for button in self.copy_buttons:
            button.configure(state="normal" if on else "disabled")
        self.copied.configure(text="")

    def _poll(self) -> None:
        """Keep the list of what agents used up to date while the window is open."""
        if not self.alive():
            return
        lines = [f"{stamp}  {tool}" for stamp, tool in self.app._agent_calls]
        text = "\n".join(lines[-5:]) if lines else "Nothing yet."
        self.recent.configure(state="normal")
        self.recent.delete("1.0", "end")
        self.recent.insert("1.0", text)
        self.recent.configure(state="disabled")
        if self._server() is None and self.switch.cget("text") == "Turn Off":     # turned off elsewhere (closing)
            self._refresh()
        self.win.after(1000, self._poll)

    # ----------------------------------------------------------------------------------------------- copying
    def _copy(self, text: str, what: str) -> None:
        if not text:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(text)
        self.copied.configure(text=f"Copied {what}.")

    def _copy_settings(self) -> None:
        """Copy the settings text for the chosen client."""
        server = self._server()
        if server is None:
            return
        name = self.format.get()
        key = next((k for k, label in mcp_http.FORMATS if label == name), mcp_http.FORMATS[0][0])
        self._copy(server.settings(key), f"the settings for {name}")
        if key in mcp_http.FORMAT_NOTES:
            self.copied.configure(text=mcp_http.FORMAT_NOTES[key])
