"""Smoke test of the whole interface: every window opens, every menu builds, text can be enlarged to
200% with everything open, and nothing raises. Phone access is faked.

Tk reports an error inside a handler through report_callback_exception and carries on, so a plain
test would pass while a window was broken. These tests collect those reports and fail on any.
"""
import os
import sys
import time
import tkinter as tk
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False

SERIAL = "6a81a217"
PHONE = {"serial": SERIAL, "state": "device", "brand": "POCO", "model": "POCO M2 Pro", "android": "12", "sdk": "31",
         "miui": "V140", "build": "SKQ1.211019.001", "security_patch": "2023-06-01", "region": "IN", "chipset": "SM7125",
         "ram_gb": 5.4, "storage_used_gb": 42.1, "storage_total_gb": 45.1, "screen": "1080x2400",
         "kernel": "4.14.190-perf", "verified_boot": "green", "encryption": "encrypted", "bootloader_locked": True,
         "battery": 66, "battery_temp_c": 33.2, "codename": "gram"}


def settle(root, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class SmokeTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit import gui
        self.errors = []
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app.busy = True                                # no real USB scan
        self.app._polling = True
        self.root.report_callback_exception = lambda exc, val, tb: self.errors.append(f"{exc.__name__}: {val}")
        self.app.android = dict(PHONE)
        self.app._device_seen(None, dict(PHONE), None)
        settle(self.root)

    def tearDown(self):
        self.root.destroy()

    def assertClean(self):
        settle(self.root, 0.2)
        self.assertEqual(self.errors, [])

    def test_every_menu_builds_and_refreshes(self):
        bar = self.root.nametowidget(self.root.cget("menu"))
        self.app.menubar.refresh()
        for i in range(bar.index("end") + 1):
            if bar.type(i) == "cascade":
                menu = self.root.nametowidget(bar.entrycget(i, "menu"))
                for j in range(menu.index("end") + 1):
                    self.assertIn(menu.type(j), ("command", "separator", "cascade", "checkbutton"))
        self.assertClean()

    def test_text_size_up_to_200_percent_and_back(self):
        for _ in range(8):
            self.app._zoom(+1)
            settle(self.root, 0.05)
        self.assertEqual(self.app._zoom_factor, 2.0)
        for _ in range(8):
            self.app._zoom(-1)
        self.app._zoom(0)
        self.assertClean()

    def test_guide_activity_and_driver_windows_open(self):
        self.app._open_guide()
        self.app._toggle_details()
        self.app._driver_help()
        settle(self.root)
        self.assertTrue(self.app._guide.alive())
        self.assertClean()
        self.app._guide.close()
        self.app._activity_win.close()

    def test_live_status_and_connections_and_log_windows_open_and_close(self):
        from mitoolkit import diagnostics
        from mitoolkit.ui.connect_dialog import ConnectionsDialog
        from mitoolkit.ui.live_dialog import LiveStatusDialog
        from mitoolkit.ui.log_dialog import LogDialog
        live = LiveStatusDialog(self.app, SERIAL, "POCO M2 Pro", start=False)
        conn = ConnectionsDialog(self.app, SERIAL, "POCO M2 Pro", start=False)
        with mock.patch("mitoolkit.adb.logcat", return_value="11-15 13:20:01.123  1  2 E Tag: boom\n"):
            log = LogDialog(self.app, SERIAL, "POCO M2 Pro")
            settle(self.root, 0.6)
        from test_diagnostics import ReportTests
        conn._arrived(diagnostics.build(ReportTests().raw()), None)
        for tab in ("wifi", "mobile", "other", "summary"):
            conn.tab_var.set(tab)
            conn._show_tab()
        for tab in ("processor", "sensors", "processes", "overview"):
            live.tab_var.set(tab)
            live._show_tab()
        settle(self.root)
        self.assertIn("boom", log.text.get("1.0", "end"))
        self.assertClean()
        for dialog in (live, conn, log):
            dialog.close()
        self.assertClean()

    def test_security_backup_and_app_manager_windows_open(self):
        from mitoolkit import security
        from mitoolkit.ui.apps_dialog import AppManagerDialog
        from mitoolkit.ui.backup_dialog import BackupDialog
        from mitoolkit.ui.security_dialog import SecurityDialog
        report = security.Report()
        report.add(security.OK, "Phone software", "Security patch is recent", "")
        with mock.patch("mitoolkit.security.run", return_value=report), \
                mock.patch("mitoolkit.adb.list_packages", return_value=[]):
            security_window = SecurityDialog(self.app, SERIAL)
            backup = BackupDialog(self.app, SERIAL, "POCO M2 Pro")
            apps = AppManagerDialog(self.app, SERIAL)
            settle(self.root, 0.5)
        self.assertClean()
        for dialog in (security_window, backup, apps):
            dialog.close()

    def test_show_more_expands_and_collapses_without_rebuilding(self):
        key = ("android", SERIAL)
        self.app._more[key] = [("Identity", [("Serial", "6a81a217"), ("IMEI 1", "356831091234565")]),
                               ("Battery", [("Charge", "66%")])]
        self.app._more_open = True
        self.app._show_more()
        first = self.app.more_box.winfo_children()
        self.assertTrue(first)
        self.app._toggle_more()                                   # collapse
        self.assertFalse(self.app.more_box.winfo_ismapped())
        self.app._toggle_more()                                   # expand again: same widgets, no rebuild
        self.assertEqual(self.app.more_box.winfo_children(), first)
        self.assertEqual(self.app.more_btn.cget("text"), "Show less")
        self.assertClean()

    def test_rescan_gives_feedback_and_recovers_from_a_stuck_scan(self):
        self.app.busy = False
        self.app.fastboot = "built-in USB fastboot"
        self.app._polling = True
        self.app._scan_started = time.monotonic()                  # a scan is running now
        self.app._rescan()
        self.assertEqual(self.app.status.cget("text"), "Already looking for the phone...")
        self.app._scan_started = time.monotonic() - 60             # ...but it has been stuck for a minute
        with mock.patch.object(self.app, "_scan") as scan:
            self.app._rescan()
            scan.assert_called_once()
        self.assertFalse(self.app._polling)
        self.app.busy = True
        self.app._rescan()
        self.assertIn("Busy", self.app.status.cget("text"))

    def test_the_message_pump_survives_a_failing_update(self):
        calls = []

        def broken():
            raise RuntimeError("boom")

        self.app.q.put(("call", broken, ()))
        self.app.q.put(("call", lambda: calls.append("next"), ()))
        self.app._pump()
        self.assertEqual(calls, ["next"])                         # the item after the failure still ran
        self.assertEqual(self.errors, [])

    def test_unlock_stays_behind_its_guards(self):
        self.assertEqual(str(self.app.unlock_btn.cget("state")), "disabled")


if __name__ == "__main__":
    unittest.main()
