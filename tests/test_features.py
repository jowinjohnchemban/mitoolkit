"""Export formats, the quick security check, restart choices, fastboot restart modes and sign out."""
import csv
import io
import os
import sys
import unittest
from datetime import date
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from mitoolkit import export, fastboot, security  # noqa: E402
from mitoolkit.fastboot import FastbootError  # noqa: E402

try:
    import tkinter as tk
    tk.Tk().destroy()
    HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False

PAIRS = [("Device", "POCO M2 Pro"), ("Serial", "6a81a217"), ("Region", None)]
SECTIONS = [("Battery", [("Charge", "66%"), ("Note", "a | b\nc")])]


class ExportTests(unittest.TestCase):
    def test_csv_has_a_row_per_item_and_skips_empty_values(self):
        rows = list(csv.reader(io.StringIO(export.render("csv", PAIRS, SECTIONS))))
        self.assertEqual(rows[0], ["Section", "Item", "Value"])
        self.assertIn(["Summary", "Serial", "6a81a217"], rows)
        self.assertIn(["Battery", "Note", "a | b c"], rows)
        self.assertNotIn("Region", [r[1] for r in rows])

    def test_markdown_escapes_the_table_bar(self):
        md = export.render("md", PAIRS, SECTIONS)
        self.assertIn("## Battery", md)
        self.assertIn("| Note | a \\| b c |", md)

    def test_text_and_unknown_format(self):
        text = export.render("txt", PAIRS, SECTIONS)
        self.assertIn("Summary\n  Device: POCO M2 Pro", text)
        with self.assertRaises(ValueError):
            export.render("pdf", PAIRS)

    def test_suggested_name_is_safe(self):
        self.assertEqual(export.suggested_name("csv", "POCO M2/Pro"), "POCO-M2-Pro-details.csv")


class QuickCheckTests(unittest.TestCase):
    TODAY = date(2026, 6, 1)

    def verdict(self, **info):
        base = {"security_patch": "2026-05-01", "verified_boot": "green", "encryption": "encrypted",
                "bootloader_locked": True}
        base.update(info)
        return security.passive(base, "1", self.TODAY).verdict

    def test_good_phone_has_nothing_to_report(self):
        self.assertEqual(self.verdict(), "Nothing found")

    def test_levels(self):
        self.assertEqual(self.verdict(security_patch="2026-01-01"), "Some things to review")
        self.assertEqual(self.verdict(security_patch="2024-12-01"), "Needs attention")
        self.assertEqual(self.verdict(bootloader_locked=False, verified_boot="orange"), "Some things to review")
        self.assertEqual(self.verdict(verified_boot="red"), "Needs attention")
        self.assertEqual(self.verdict(encryption="unencrypted"), "Needs attention")
        self.assertEqual(security.passive({"security_patch": "2026-05-01"}, "0", self.TODAY).verdict,
                         "Needs attention")                       # Play Protect off


class FastbootRestartTests(unittest.TestCase):
    def test_only_known_modes(self):
        with mock.patch.object(fastboot, "backend") as backend:
            fastboot.reboot("S", "recovery")
            backend.return_value.reboot.assert_called_once_with("S", "recovery")
            with self.assertRaises(FastbootError):
                fastboot.reboot("S", "bootloader; rm")


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class WindowTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit import gui
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app._polling = True
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_restart_dialog_in_android_and_in_fastboot(self):
        from mitoolkit.ui.restart_dialog import RestartDialog
        self.app.android = {"serial": "X", "state": "device"}
        d = RestartDialog(self.app)
        self.assertEqual(d.choice.get(), "android")
        d.choice.set("off")
        self.assertEqual(d.go.cget("text"), "Power Off")
        d.close()
        self.app.android, self.app.device = None, "FB1"
        d = RestartDialog(self.app)
        self.assertEqual(d.choice.get(), "android")                # "Cancel and start Android" comes first
        with mock.patch.object(self.app, "_reboot") as reboot:
            d.choice.set("recovery")
            d._go()
            reboot.assert_called_once_with("recovery")

    def test_wifi_phone_cannot_pick_fastboot(self):
        from mitoolkit.ui.restart_dialog import RestartDialog
        self.app.android = {"serial": "192.168.1.5:5555", "state": "device"}
        d = RestartDialog(self.app)
        radios = [w for w in d.body.winfo_children()[2].winfo_children()]
        d.close()
        self.assertTrue(radios)

    def test_about_dialog_is_short_and_copies_version_info(self):
        from mitoolkit.ui.about_dialog import AboutDialog, version_text
        d = AboutDialog(self.app)
        d._copy()
        self.assertEqual(self.root.clipboard_get(), version_text())
        self.assertNotIn("fork", "".join(w.cget("text") for w in d.body.winfo_children()
                                         if w.winfo_class() == "TLabel").lower())
        d.close()

    def test_sign_out_button_shows_only_when_signed_in(self):
        self.assertFalse(self.app.signout_btn.winfo_ismapped())
        self.app.token = {"userId": "1"}
        self.app._refresh()
        self.root.update()
        self.assertTrue(self.app.signout_btn.winfo_ismapped())

    def test_quick_audit_colours_the_security_button(self):
        self.app.android = {"serial": "X", "state": "device"}
        self.app._passive["X"] = "Needs attention"
        self.app._paint_security_button()
        self.assertEqual(self.app.security_btn.kind, "danger")
        self.app.security_result("X", "Nothing found")             # a full check takes over
        self.assertEqual(self.app.security_btn.kind, "good")


if __name__ == "__main__":
    unittest.main()
