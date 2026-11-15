"""The menu bar: every entry exists, states follow the app, shortcuts respect them."""
import os
import sys
import tkinter as tk
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

try:
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


def labels(menu):
    out = {}
    for i in range(menu.index("end") + 1):
        if menu.type(i) in ("command", "cascade"):
            out[menu.entrycget(i, "label")] = menu.entrycget(i, "state") if menu.type(i) == "command" else "cascade"
    return out


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class MenuTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit import gui
        self.root = make_root()
        self.app = gui.App(self.root)
        self.bar = self.root.nametowidget(self.root.cget("menu"))

    def tearDown(self):
        self.root.destroy()

    def menu(self, name):
        for i in range(self.bar.index("end") + 1):
            if self.bar.type(i) == "cascade" and self.bar.entrycget(i, "label") == name:
                self.bar.postcommand = None
                m = self.root.nametowidget(self.bar.entrycget(i, "menu"))
                self.app.menubar.refresh()
                return m
        raise AssertionError(f"no {name} menu")

    def test_top_level_menus(self):
        names = [self.bar.entrycget(i, "label") for i in range(self.bar.index("end") + 1)]
        names = [n for n in names if n.strip()]  # not the blank spacer before File
        self.assertEqual(names, ["File", "Unlock", "Phone", "View", "Help"])

    def test_unlock_itself_is_not_a_menu_item(self):
        for i in range(self.bar.index("end") + 1):
            if self.bar.type(i) != "cascade":
                continue
            menu = self.root.nametowidget(self.bar.entrycget(i, "menu"))
            for j in range(menu.index("end") + 1):
                if menu.type(j) == "command":
                    self.assertNotIn("erase", menu.entrycget(j, "label").lower())
                    self.assertNotEqual(menu.entrycget(j, "label"), "Unlock")

    def test_idle_with_no_phone(self):
        phone = labels(self.menu("Phone"))
        for item in ("Back up files...", "Manage apps...", "Security check...", "Restart or power off...",
                     "Export device details...", "Stop Google's adb"):
            self.assertEqual(phone[item], "disabled", item)
        self.assertEqual(labels(self.menu("Unlock"))["Check eligibility"], "disabled")
        self.assertEqual(labels(self.menu("Unlock"))["Sign in to Mi Account..."], "normal")
        self.assertEqual(labels(self.menu("File"))["Quit"], "normal")

    def test_android_phone_enables_tools(self):
        self.app.android = {"serial": "X", "state": "device", "model": "POCO M2 Pro"}
        phone = labels(self.menu("Phone"))
        for item in ("Back up files...", "Manage apps...", "Security check...", "Restart or power off..."):
            self.assertEqual(phone[item], "normal", item)

    def test_fastboot_phone_can_be_restarted_from_the_menu(self):
        self.app.device, self.app.fastboot = "FB1", "built-in USB fastboot"
        self.assertEqual(labels(self.menu("Phone"))["Restart or power off..."], "normal")

    def test_signed_in_fastboot_allows_check(self):
        self.app.token, self.app.device = {"userId": "1"}, "FB1"
        unlock = labels(self.menu("Unlock"))
        self.assertEqual(unlock["Check eligibility"], "normal")
        self.assertEqual(unlock["Sign in to Mi Account..."], "disabled")

    def test_busy_disables_everything_that_starts_work(self):
        self.app.android = {"serial": "X", "state": "device"}
        self.app.busy = True
        phone = labels(self.menu("Phone"))
        self.assertEqual(phone["Back up files..."], "disabled")
        self.assertEqual(phone["Rescan"], "disabled")

    def test_shortcut_does_nothing_while_disabled(self):
        calls = []
        self.app._check = lambda: calls.append(1)
        # the menu captured the original method, so test the guard directly
        from mitoolkit.ui.menu import MenuBar
        self.assertEqual(MenuBar._fire(lambda: calls.append(1), lambda: False), "break")
        self.assertEqual(calls, [])
        MenuBar._fire(lambda: calls.append(1), lambda: True)
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
