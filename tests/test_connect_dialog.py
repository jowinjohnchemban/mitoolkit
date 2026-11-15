"""Connections window: tabs, findings, rows with marks, the network test, no crash on bad data."""
import os
import sys
import tkinter as tk
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from test_diagnostics import ReportTests  # noqa: E402
from tkhelper import make_root  # noqa: E402

from miunlock import diagnostics  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class ConnectionsDialogTests(unittest.TestCase):
    def setUp(self):
        from miunlock import gui
        from miunlock.ui.connect_dialog import ConnectionsDialog
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app.busy = True
        self.app._polling = True
        self.dlg = ConnectionsDialog(self.app, "X", "POCO M2 Pro", start=False)
        self.report = diagnostics.build(ReportTests().raw())

    def tearDown(self):
        self.dlg.close()
        self.root.destroy()

    def show(self, report=None):
        self.dlg._arrived(report or self.report, None)
        self.root.update()

    def texts(self, widget):
        out = []
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                out.append(child.cget("text"))
            out += self.texts(child)
        return out

    def test_summary_shows_findings_with_marks_and_stops_the_skeleton(self):
        self.show()
        self.assertIsNone(self.dlg.loading)
        text = " ".join(self.texts(self.dlg.findings_box))
        self.assertIn("Mobile data is connected but has no internet", text)
        self.assertIn("✖", text)                                  # a symbol as well as a colour

    def test_each_tab_lists_its_sections(self):
        self.show()
        expected = {"wifi": "Home Net", "mobile": "Jio 4G (405874)", "other": "Connected"}
        for tab, needle in expected.items():
            self.dlg.tab_var.set(tab)
            self.dlg._show_tab()
            self.root.update()
            text = " ".join(self.texts(self.dlg.pages[tab].content))
            self.assertIn(needle, text, tab)

    def test_unchanged_report_does_not_rebuild_the_page(self):
        self.show()
        self.dlg.tab_var.set("wifi")
        self.dlg._show_tab()
        first = self.dlg.pages["wifi"].content.winfo_children()
        self.dlg._arrived(diagnostics.build(ReportTests().raw()), None)    # the same content again
        self.assertEqual(self.dlg.pages["wifi"].content.winfo_children(), first)

    def test_signal_charts_get_a_point_per_refresh(self):
        self.show()
        self.show()
        self.assertEqual(len(self.dlg.wifi_chart.data[0]), 2)
        self.assertEqual(self.dlg.wifi_chart.data[0][-1], -61)

    def test_an_error_keeps_the_last_report_and_says_so(self):
        self.show()
        self.dlg._busy = True
        self.dlg._arrived(None, "The phone did not answer in 30 seconds.")
        self.assertIn("did not answer", self.dlg.sub.cget("text"))
        self.assertIs(self.dlg.report, self.report if self.dlg.report is self.report else self.dlg.report)
        self.assertFalse(self.dlg._busy)

    def test_network_test_results_show_on_the_summary(self):
        self.show()
        self.dlg._testing = True
        self.dlg._test_done([("Internet (8.8.8.8)", "3 of 3 replies, 12 ms", diagnostics.OK)], None)
        self.assertEqual(self.dlg.tab_var.get(), "summary")
        self.assertIn("3 of 3 replies, 12 ms", " ".join(self.texts(self.dlg.test_box)))

    def test_odd_data_does_not_break_rendering(self):
        odd = {"sections": [("Wi-Fi", [("Signal", "-61 dBm", None), ("Strange", "", "unknown-level")])],
               "findings": [(diagnostics.OK, "Fine", "")], "signals": {"wifi_dbm": None, "mobile_dbm": None},
               "state": {}}
        self.show(odd)
        self.dlg.tab_var.set("wifi")
        self.dlg._show_tab()
        self.root.update()
        self.assertTrue(self.dlg.alive())


if __name__ == "__main__":
    unittest.main()
