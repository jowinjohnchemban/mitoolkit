"""The Security check button takes the colour of the last check: green, amber or red, with a mark."""
import os
import sys
import tkinter as tk
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class SecurityButtonTests(unittest.TestCase):
    def setUp(self):
        from miunlock import gui
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app.busy = True                      # no real USB scan during the test
        self.app._polling = True                  # (a scan would replace the phone we set below)
        self.app.android = {"serial": "X", "state": "device", "model": "POCO M2 Pro"}

    def tearDown(self):
        self.root.destroy()

    def test_colour_follows_the_verdict_and_a_mark_says_it_in_words(self):
        b = self.app.security_btn
        self.app._paint_security_button()
        self.assertEqual((b.kind, b.cget("text")), ("normal", "Security check..."))      # not checked yet
        for verdict, kind, mark in (("No problems found", "good", "✔"), ("Some things to review", "warn", "!"),
                                    ("Needs attention", "danger", "⚠")):
            self.app.security_result("X", verdict)
            self.assertEqual(b.kind, kind)
            self.assertTrue(b.cget("text").endswith(mark))

    def test_another_phone_starts_neutral(self):
        self.app.security_result("X", "Needs attention")
        self.app.android = {"serial": "Y", "state": "device", "model": "Other"}
        self.app._paint_security_button()
        self.assertEqual(self.app.security_btn.kind, "normal")


if __name__ == "__main__":
    unittest.main()
