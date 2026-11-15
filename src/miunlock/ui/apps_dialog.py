"""App manager (debloat): list apps, tick, remove for the user, restore."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List, Set, Tuple

from miunlock import adb, bloat
from miunlock.ui.base import Dialog
from miunlock.ui.theme import AMBER, GREEN, MUTED, RED, WARN_BG, WARN_FG

TICKED, UNTICKED = "☑", "☐"


class AppRow:
    """One app as the manager shows it."""

    def __init__(self, data: dict):
        self.package: str = data["package"]
        self.system: bool = data["system"]
        self.installed: bool = data["installed"]
        self.disabled: bool = data["disabled"]
        self.name, self.rating, self.note = bloat.describe(self.package, self.system)

    @property
    def status(self) -> str:
        if not self.installed:
            return "Removed"
        return "Disabled" if self.disabled else "Installed"

    @property
    def risky(self) -> bool:
        return self.rating in ("avoid", "advanced", "unknown")

    def matches(self, view: str, query: str) -> bool:
        if view == "Known bloat" and not (self.package in bloat.KNOWN and self.rating != "avoid" and self.installed):
            return False
        if view == "All preinstalled" and not (self.system and self.installed):
            return False
        if view == "Installed by you" and self.system:
            return False
        if view == "Removed (restorable)" and self.installed:
            return False
        q = query.strip().lower()
        return not q or q in self.package.lower() or q in self.name.lower()


class AppManagerDialog(Dialog):
    title = "Manage apps"
    size = "900x600"
    min_size = (640, 400)

    VIEWS = ["Known bloat", "All preinstalled", "Installed by you", "Removed (restorable)", "Everything"]
    COLUMNS = (("mark", "", 34, False), ("name", "App", 170, False), ("package", "Package", 250, True),
               ("rating", "Rating", 100, False), ("status", "Status", 90, False), ("note", "Note", 260, True))

    def __init__(self, app, serial: str):
        self.serial = serial
        self.apps: Dict[str, AppRow] = {}
        self.marked: Set[str] = set()
        super().__init__(app)
        self.reload()

    # ------------------------------------------------------------------ layout
    def build(self) -> None:
        body = self.body
        tk.Label(body, bg=WARN_BG, fg=WARN_FG, justify="left", anchor="w", padx=10, pady=6, wraplength=840,
                 text="Tick the apps to remove, then click Remove ticked. Preinstalled apps are only removed "
                      "for your user and can be restored here. Unlocking the bootloader resets the phone and "
                      "brings them all back, so debloat after unlocking, or if you are not unlocking.").pack(fill="x")

        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(10, 6))
        ttk.Label(bar, text="Show:").pack(side="left")
        self.view = tk.StringVar(value=self.VIEWS[0])
        combo = ttk.Combobox(bar, textvariable=self.view, state="readonly", width=24, values=self.VIEWS)
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", self.fill)
        ttk.Label(bar, text="Search:").pack(side="left", padx=(12, 0))
        self.query = tk.StringVar()
        self.query.trace_add("write", self.fill)
        ttk.Entry(bar, textvariable=self.query, width=28).pack(side="left", padx=6)
        self.count = ttk.Label(bar, text="Loading apps from the phone...", foreground=MUTED)
        self.count.pack(side="right")

        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in self.COLUMNS], show="headings", selectmode="browse")
        for col, title, width, stretch in self.COLUMNS:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=stretch, anchor="center" if col == "mark" else "w")
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        for tag, colour in (("recommended", GREEN), ("advanced", AMBER), ("avoid", RED), ("unknown", MUTED)):
            self.tree.tag_configure(tag, foreground=colour)
        self.tree.bind("<Button-1>", lambda e: self.toggle(self.tree.identify_row(e.y)))
        self.tree.bind("<space>", lambda _e: self.toggle(self.tree.focus()))

        self.status = ttk.Label(body, text="", foreground=MUTED, wraplength=840, justify="left")
        self.status.pack(fill="x", pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Tick recommended", command=self.tick_recommended).pack(side="left")
        ttk.Button(buttons, text="Clear ticks", command=self.clear_ticks).pack(side="left", padx=6)
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        ttk.Button(buttons, text="Restore ticked", command=lambda: self.apply(restore=True)).pack(side="right", padx=6)
        ttk.Button(buttons, text="Remove ticked", style="Primary.TButton",
                   command=lambda: self.apply(restore=False)).pack(side="right")

    # -------------------------------------------------------------------- data
    def set_apps(self, data: List[dict]) -> None:
        self.apps = {d["package"]: AppRow(d) for d in data}
        self.marked &= set(self.apps)
        self.fill()

    def reload(self) -> None:
        def loaded(status, result):
            if not self.alive():
                return
            if status == "error":
                self.count.configure(text="")
                self.status.configure(text=f"Could not read the app list: {result}", foreground=RED)
                return
            self.set_apps(result)

        self.app.run(lambda: adb.list_packages(self.serial), loaded, "Reading the app list from the phone...")

    def visible(self) -> List[AppRow]:
        order = {r: i for i, r in enumerate(bloat.RATINGS)}
        rows = [a for a in self.apps.values() if a.matches(self.view.get(), self.query.get())]
        return sorted(rows, key=lambda a: (order[a.rating], a.package))

    def fill(self, *_args) -> None:
        self.tree.delete(*self.tree.get_children())
        rows = self.visible()
        for a in rows:
            self.tree.insert("", "end", iid=a.package, tags=(a.rating,),
                             values=(TICKED if a.package in self.marked else UNTICKED, a.name, a.package,
                                     a.rating.capitalize(), a.status, a.note))
        self._count(len(rows))

    def _count(self, shown: int) -> None:
        self.count.configure(text=f"{shown} shown, {len(self.marked)} ticked")

    # ----------------------------------------------------------------- actions
    def toggle(self, package: str) -> None:
        if not package:
            return
        self.marked.symmetric_difference_update({package})
        self.tree.set(package, "mark", TICKED if package in self.marked else UNTICKED)
        self._count(len(self.tree.get_children()))

    def tick_recommended(self) -> None:
        self.marked |= {a.package for a in self.apps.values() if a.installed and a.rating == "recommended"}
        self.fill()

    def clear_ticks(self) -> None:
        self.marked.clear()
        self.fill()

    def chosen(self, restore: bool) -> List[AppRow]:
        return [self.apps[p] for p in sorted(self.marked) if p in self.apps and self.apps[p].installed != restore]

    def confirm_removal(self, rows: List[AppRow]) -> bool:
        risky = [a.package for a in rows if a.risky]
        yours = [a for a in rows if not a.system]
        text = f"Remove {len(rows)} app(s) for your user?"
        if risky:
            text += ("\n\nThese can affect the phone or the unlock:\n  " + "\n  ".join(risky[:12])
                     + ("\n  ..." if len(risky) > 12 else ""))
        if yours:
            text += f"\n\n{len(yours)} of them were installed by you and will be uninstalled, not just hidden."
        return messagebox.askyesno("Remove apps", text, default="no" if risky else "yes",
                                   icon="warning" if risky else "question", parent=self.win)

    def apply(self, restore: bool) -> None:
        rows = self.chosen(restore)
        if not rows:
            messagebox.showinfo("Manage apps", "Tick at least one "
                                + ("removed app to restore." if restore else "installed app to remove."), parent=self.win)
            return
        if not restore and not self.confirm_removal(rows):
            return
        action = adb.restore_for_user if restore else adb.uninstall_for_user
        verb = "Restored" if restore else "Removed"

        def work() -> Tuple[list, list, list]:
            ok, failed = [], []
            for row in rows:
                try:
                    action(row.package, self.serial)
                    ok.append(row.package)
                    self.app.log(f"{verb} {row.package}")
                except adb.AdbError as err:
                    failed.append(row.package)
                    self.app.log(f"Could not {verb.lower()[:-1]} {row.package}: {err}")
            return ok, failed, adb.list_packages(self.serial)

        def done(status, result) -> None:
            if not self.alive():
                return
            if status == "error":
                self.status.configure(text=str(result), foreground=RED)
                return
            ok, failed, fresh = result
            self.marked -= set(ok)
            self.set_apps(fresh)
            self.status.configure(
                text=f"{verb} {len(ok)} app(s)." + (f" {len(failed)} failed: {', '.join(failed[:6])}" if failed else ""),
                foreground=RED if failed else GREEN)

        self.app.run(work, done, ("Restoring" if restore else "Removing") + " apps...")
