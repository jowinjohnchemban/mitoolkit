"""App manager (debloat): pick apps to remove for your user, or bring removed ones back.

Layout: tabs with counts (Suggested / All preinstalled / Installed by you / Removed), a list
with a tick box per app, a panel explaining the selected app, and one action button that
says exactly what it will do ("Remove 3 apps", "Restore 1 app").
"""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Dict, List, Set, Tuple
from urllib.parse import quote

from mitoolkit import adb, bloat
from mitoolkit.ui.components.buttons import Button, segmented
from mitoolkit.ui.components.search import SearchBox, rank
from mitoolkit.ui.base import Dialog
from mitoolkit.ui.theme import AMBER, GREEN, MUTED, RED

TICKED, UNTICKED = "☑", "☐"
COLOURS = {"recommended": GREEN, "optional": "", "advanced": AMBER, "avoid": RED, "unknown": MUTED}


class AppRow:
    """One app as the manager shows it."""

    def __init__(self, data: dict):
        self.package: str = data["package"]
        self.system: bool = data["system"]
        self.installed: bool = data["installed"]
        self.disabled: bool = data["disabled"]
        self.name, self.rating, self.note = bloat.describe(self.package, self.system)

    @property
    def label(self) -> str:
        return self.name or self.package

    @property
    def rating_label(self) -> str:
        return bloat.LABELS[self.rating][0]

    @property
    def status(self) -> str:
        if not self.installed:
            return "Removed"
        return "Disabled" if self.disabled else "Installed"

    @property
    def risky(self) -> bool:
        return self.rating in ("avoid", "advanced", "unknown")

    def in_tab(self, tab: str) -> bool:
        if tab == "suggested":
            return self.installed and self.package in bloat.KNOWN and self.rating in ("recommended", "optional")
        if tab == "system":
            return self.installed and self.system
        if tab == "yours":
            return self.installed and not self.system
        if tab == "removed":
            return not self.installed
        return True

    def matches(self, query: str) -> bool:
        q = query.strip().lower()
        return not q or q in self.package.lower() or q in self.name.lower()


class AppManagerDialog(Dialog):
    title = "Manage apps"
    size = "1000x640"
    min_size = (760, 460)

    TABS = (("suggested", "Suggested"), ("system", "All preinstalled"), ("yours", "Installed by you"),
            ("removed", "Removed"))

    def __init__(self, app, serial: str):
        self.serial = serial
        self.apps: Dict[str, AppRow] = {}
        self.marked: Set[str] = set()
        self._result_shown = False  # keep "Removed 3 apps." visible until the next change
        super().__init__(app)
        self.reload()

    # ------------------------------------------------------------------ layout
    def build(self) -> None:
        body = self.body
        ttk.Label(body, text="Remove apps you don't need", font=self.fonts.heading).pack(anchor="w")
        ttk.Label(body, foreground=MUTED, justify="left", text=(
            "Tick apps and click Remove. Preinstalled apps are only hidden for you and can be restored from the "
            "Removed tab. Note: unlocking the bootloader or a factory reset brings them all back.")).pack(
            anchor="w", fill="x")
        self._wrap_on_resize(body.winfo_children()[-1])

        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(10, 4))
        self.tab = tk.StringVar(value="suggested")
        self.tabs = segmented(bar, self.TABS, self.tab, self._tab_changed)
        self.tabs.pack(side="left")
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self.fill())
        SearchBox(bar, self.query, "Search apps", width=300, suggest=self._suggest).pack(side="right")

        legend = ttk.Frame(body)
        legend.pack(fill="x", pady=(2, 6))
        for rating in bloat.RATINGS:
            ttk.Label(legend, text="● " + bloat.LABELS[rating][0], foreground=COLOURS[rating] or "").pack(
                side="left", padx=(0, 14))

        panes = ttk.PanedWindow(body, orient="horizontal")
        panes.pack(fill="both", expand=True)
        table = ttk.Frame(panes)
        self.tree = ttk.Treeview(table, columns=("mark", "app", "rating", "status"), show="headings",
                                 selectmode="browse")
        for col, title, width, stretch, anchor in (("mark", "", 34, False, "center"), ("app", "App", 260, True, "w"),
                                                   ("rating", "Rating", 120, False, "w"),
                                                   ("status", "Status", 90, False, "w")):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=stretch, anchor=anchor)
        ysb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        for rating, colour in COLOURS.items():
            if colour:
                self.tree.tag_configure(rating, foreground=colour)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", lambda _e: self.toggle(self.tree.focus()))
        self.tree.bind("<space>", lambda _e: self.toggle(self.tree.focus()))
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_details())
        panes.add(table, weight=3)

        side = ttk.Frame(panes, padding=(12, 0, 0, 0))
        self.d_name = ttk.Label(side, text="", font=self.fonts.bold, wraplength=280, justify="left")
        self.d_name.pack(anchor="w")
        self.d_pkg = ttk.Label(side, text="Select an app to see what it is.", foreground=MUTED,
                               wraplength=280, justify="left")
        self.d_pkg.pack(anchor="w", pady=(2, 8))
        self.d_rating = ttk.Label(side, text="", font=self.fonts.bold)
        self.d_rating.pack(anchor="w")
        self.d_meaning = ttk.Label(side, text="", wraplength=280, justify="left")
        self.d_meaning.pack(anchor="w", pady=(2, 8))
        self.d_note = ttk.Label(side, text="", foreground=MUTED, wraplength=280, justify="left")
        self.d_note.pack(anchor="w")
        self.d_lookup = Button(side, text="Look it up on the web", command=self._look_up)
        side.bind("<Configure>", lambda e: [w.configure(wraplength=max(e.width - 20, 120)) for w in
                                            (self.d_name, self.d_pkg, self.d_meaning, self.d_note)])
        panes.add(side, weight=1)

        self.status = ttk.Label(body, text="", foreground=MUTED, justify="left")
        self.status.pack(fill="x", pady=(6, 0))
        self._wrap_on_resize(self.status)

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        self.tick_all_btn = Button(buttons, text="Tick all in this tab", command=self.tick_all)
        self.tick_all_btn.pack(side="left")
        Button(buttons, text="Clear ticks", command=self.clear_ticks).pack(side="left", padx=6)
        Button(buttons, text="Close", command=self.close).pack(side="right")
        self.action_btn = Button(buttons, text="Remove", primary=True, command=self.apply)
        self.action_btn.pack(side="right", padx=6)
        self.win.after(50, self.tree.focus_set)  # keyboard users start here
        self._update_action()

    def _wrap_on_resize(self, label) -> None:
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(e.width - 10, 200)))

    # -------------------------------------------------------------------- data
    def set_apps(self, data: List[dict]) -> None:
        self.apps = {d["package"]: AppRow(d) for d in data}
        self.marked &= set(self.apps)
        for key, text in self.TABS:
            n = sum(1 for a in self.apps.values() if a.in_tab(key))
            self.tabs.set_label(key, f"{text} ({n})")
        self.fill()

    def reload(self) -> None:
        self.status.configure(text="Reading the app list from the phone...", foreground=MUTED)

        def loaded(status, result):
            if not self.alive():
                return
            if status == "error":
                self._result_shown = True
                self.status.configure(text=f"Could not read the app list: {result}", foreground=RED)
                return
            self.set_apps(result)

        self.app.run(lambda: adb.list_packages(self.serial), loaded, "Reading the app list from the phone...")

    def visible(self) -> List[AppRow]:
        order = {r: i for i, r in enumerate(bloat.RATINGS)}
        rows = [a for a in self.apps.values() if a.in_tab(self.tab.get()) and a.matches(self.query.get())]
        return sorted(rows, key=lambda a: (order[a.rating], a.label.lower()))

    def _suggest(self, text: str):
        """Names to offer while typing: app names (or package names) with the package beside them."""
        return rank(text, ((a.label, a.package if a.name else "") for a in self.apps.values()))

    def fill(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for a in self.visible():
            self.tree.insert("", "end", iid=a.package, tags=(a.rating,),
                             values=(TICKED if a.package in self.marked else UNTICKED,
                                     a.label if not a.name else f"{a.name}  ({a.package})",
                                     a.rating_label, a.status))
        self._update_action()

    # ----------------------------------------------------------------- details
    def show_details(self) -> None:
        sel = self.tree.selection()
        a = self.apps.get(sel[0]) if sel else None
        if a is None:
            return
        self.d_name.configure(text=a.label)
        self.d_pkg.configure(text=f"{a.package}\n{'Preinstalled' if a.system else 'Installed by you'} · {a.status}")
        self.d_rating.configure(text=a.rating_label, foreground=COLOURS[a.rating] or "")
        self.d_meaning.configure(text=bloat.LABELS[a.rating][1])
        self.d_note.configure(text=a.note)
        self.d_lookup.pack(anchor="w", pady=(10, 0))

    def _look_up(self) -> None:
        sel = self.tree.selection()
        if sel:
            webbrowser.open("https://www.google.com/search?q=" + quote(f'"{sel[0]}" android app'))

    # ----------------------------------------------------------------- ticking
    def _on_click(self, event) -> None:
        if self.tree.identify_column(event.x) == "#1":  # the tick box column
            self.toggle(self.tree.identify_row(event.y))

    def toggle(self, package: str) -> None:
        if not package:
            return
        a = self.apps[package]
        if package not in self.marked and a.rating == "avoid" and a.installed:
            if not messagebox.askyesno("Keep this app", f"{a.label} is needed by the system or for unlocking. "
                                       "Tick it anyway?", default="no", icon="warning", parent=self.win):
                return
        self._result_shown = False
        self.marked.symmetric_difference_update({package})
        self.tree.set(package, "mark", TICKED if package in self.marked else UNTICKED)
        self._update_action()

    def tick_all(self) -> None:
        self.marked |= {a.package for a in self.visible() if a.rating != "avoid"}
        self.fill()

    def clear_ticks(self) -> None:
        self.marked.clear()
        self.fill()

    def _restoring(self) -> bool:
        return self.tab.get() == "removed"

    def chosen(self) -> List[AppRow]:
        restore = self._restoring()
        return [self.apps[p] for p in sorted(self.marked) if p in self.apps and self.apps[p].installed != restore]

    def _update_action(self) -> None:
        n = len(self.chosen())
        verb = "Restore" if self._restoring() else "Remove"
        self.action_btn.configure(text=f"{verb} {n} app{'s' if n != 1 else ''}" if n else verb,
                                  state="normal" if n else "disabled")
        self.tick_all_btn.configure(text="Tick all suggested" if self.tab.get() == "suggested" else "Tick all in this tab")
        if not self._result_shown:
            self.status.configure(text=f"{len(self.tree.get_children())} shown, {len(self.marked)} ticked. "
                                       "Click the box to tick an app; click its name to see what it is.",
                                  foreground=MUTED)

    def _tab_changed(self) -> None:
        self._result_shown = False
        self.fill()

    # ----------------------------------------------------------------- actions
    def confirm_removal(self, rows: List[AppRow]) -> bool:
        risky = [a.label for a in rows if a.risky]
        yours = [a for a in rows if not a.system]
        text = f"Remove {len(rows)} app(s)?\n\nPreinstalled ones can be brought back from the Removed tab."
        if risky:
            text += ("\n\nThese are marked Caution, Keep or Unknown:\n  " + "\n  ".join(risky[:12])
                     + ("\n  ..." if len(risky) > 12 else ""))
        if yours:
            text += f"\n\n{len(yours)} of them you installed yourself: they are uninstalled and must be " \
                    "reinstalled from the store."
        return messagebox.askyesno("Remove apps", text, default="no" if risky else "yes",
                                   icon="warning" if risky else "question", parent=self.win)

    def apply(self) -> None:
        rows = self.chosen()
        if not rows:
            return
        restore = self._restoring()
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
            self._result_shown = True
            self.set_apps(fresh)
            self.status.configure(
                text=f"{verb} {len(ok)} app(s)." + (f" {len(failed)} failed: {', '.join(failed[:6])}" if failed else "")
                     + ("" if restore else " Find them in the Removed tab to bring them back."),
                foreground=RED if failed else GREEN)

        self.app.run(work, done, ("Restoring" if restore else "Removing") + " apps...")
