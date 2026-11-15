"""Wireless mode: the USB / Wireless switch, finding phones on the network, pairing by QR code, and clear errors."""
import logging
import os
import sys
import threading
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from isolate import isolate_settings  # noqa: E402
from tkhelper import make_root  # noqa: E402

from mitoolkit import adb_server  # noqa: E402
from mitoolkit.adb_usb import AdbError  # noqa: E402

try:
    import tkinter as tk
    tk.Tk().destroy()
    HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


class FakeConn:
    """Stands in for a socket to Google's adb server: serves the bytes it is given, 4 or n at a time."""

    def __init__(self, data: bytes):
        self.data = data

    def read(self, n, timeout_ms=0):
        out, self.data = self.data[:n], self.data[n:]
        return out


class ReplyTests(unittest.TestCase):
    def test_a_length_prefixed_text_is_read(self):
        self.assertEqual(adb_server._read_text(FakeConn(b"0005hello")), "hello")

    def test_a_fail_after_okay_is_shown_as_the_error_it_is(self):
        with self.assertRaisesRegex(AdbError, "Could not connect to 192.168.1.5:39865."):
            adb_server._read_text(FakeConn(b"FAIL0026failed to connect to 192.168.1.5:39865"))

    def test_common_failures_are_put_in_plain_words(self):
        self.assertIn("different number (port)", adb_server._readable("cannot connect: actively refused it. (10061)"))
        self.assertIn("same Wi-Fi", adb_server._readable("connection timed out (10060)"))
        self.assertIn("Pair it first", adb_server._readable("failed to authenticate to 192.168.1.5:5555"))
        self.assertEqual(adb_server._readable("something else"), "something else")

    def test_garbage_is_an_explained_error_not_a_crash(self):
        with self.assertRaisesRegex(AdbError, "Unexpected answer"):
            adb_server._read_text(FakeConn(b"zzzzrest"))

    def test_a_refused_connection_explains_pairing(self):
        with mock.patch.object(adb_server, "start", return_value=True), mock.patch.object(
                adb_server, "_host_command", side_effect=AdbError("failed to connect to 192.168.1.5:39865")):
            with self.assertRaises(AdbError) as caught:
                adb_server.connect("192.168.1.5:39865")
        self.assertIn("Could not connect to 192.168.1.5:39865", str(caught.exception))
        self.assertIn("pair it first", str(caught.exception))


class QrPairingTests(unittest.TestCase):
    def setUp(self):
        isolate_settings(self)

    def test_the_qr_text_carries_a_random_name_and_a_six_digit_password(self):
        a, b = adb_server.pairing_qr(), adb_server.pairing_qr()
        self.assertRegex(a["payload"], r"^WIFI:T:ADB;S:mitoolkit-[a-z0-9]{6};P:\d{6};;$")
        self.assertIn(a["name"], a["payload"])
        self.assertIn(a["password"], a["payload"])
        self.assertNotEqual(a["name"], b["name"])

    def test_it_waits_for_the_phone_that_scanned_it_then_pairs(self):
        seen = [[], [{"name": "other", "kind": "pairing", "address": "192.168.1.9:1111"}],
                [{"name": "mitoolkit-abc123", "kind": "pairing", "address": "192.168.1.5:41234"}]]
        with mock.patch.object(adb_server, "mdns_services", side_effect=lambda: seen.pop(0)), \
                mock.patch.object(adb_server, "pair", return_value="192.168.1.5:41234") as pair:
            address = adb_server.wait_for_qr_pairing("mitoolkit-abc123", "123456", threading.Event(), poll=0.001)
        self.assertEqual(address, "192.168.1.5:41234")
        pair.assert_called_once_with("192.168.1.5:41234", "123456")          # another phone's service was ignored

    def test_cancel_and_timeout_stop_the_wait(self):
        stop = threading.Event()
        stop.set()
        with mock.patch.object(adb_server, "mdns_services", return_value=[]):
            with self.assertRaisesRegex(AdbError, "Cancelled"):
                adb_server.wait_for_qr_pairing("n", "123456", stop, poll=0.001)
            with self.assertRaisesRegex(AdbError, "did not scan"):
                adb_server.wait_for_qr_pairing("n", "123456", threading.Event(), timeout=0.05, poll=0.01)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        isolate_settings(self)
        adb_server._tried.clear()
        adb_server._scanned.clear()
        self.addCleanup(adb_server._tried.clear)
        self.addCleanup(adb_server._scanned.clear)
        patcher = mock.patch.object(adb_server, "start", return_value=True)       # no real adb server in these tests
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_connected_paired_and_unpaired_phones(self):
        services = [{"name": "a", "kind": "connect", "address": "192.168.1.5:1"},
                    {"name": "b", "kind": "connect", "address": "192.168.1.6:2"},
                    {"name": "c", "kind": "connect", "address": "192.168.1.7:3"},
                    {"name": "d", "kind": "pairing", "address": "192.168.1.8:4"}]

        def connect(address):
            if address.endswith(":3"):
                raise AdbError("failed to connect")
            return address
        with mock.patch.object(adb_server, "mdns_services", return_value=services), \
                mock.patch.object(adb_server, "devices", return_value=[{"serial": "192.168.1.5:1", "state": "device"}]), \
                mock.patch.object(adb_server, "connect", side_effect=connect) as connect_mock:
            found = adb_server.discover_and_connect()
        self.assertEqual([(f["address"], f["state"]) for f in found],
                         [("192.168.1.5:1", "connected"), ("192.168.1.6:2", "connected"), ("192.168.1.7:3", "needs-pairing")])
        self.assertEqual(connect_mock.call_count, 2)                      # the one already connected is left alone

    def test_a_refused_phone_is_not_hammered(self):
        services = [{"name": "c", "kind": "connect", "address": "192.168.1.7:3"}]
        with mock.patch.object(adb_server, "mdns_services", return_value=services), \
                mock.patch.object(adb_server, "devices", return_value=[]), \
                mock.patch.object(adb_server, "connect", side_effect=AdbError("no")) as connect:
            adb_server.discover_and_connect()
            again = adb_server.discover_and_connect()
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(again[0]["state"], "needs-pairing")


class HandlerTests(unittest.TestCase):
    def test_warnings_reach_the_activity_log_scrubbed_and_info_does_not(self):
        from mitoolkit import gui
        lines = []
        handler = gui.ActivityHandler(lines.append)
        logger = logging.getLogger("activity-test")
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        logger.info("just information")
        logger.warning("could not read %s with token=%s", "the phone", "abcdefghijabcdefghijabcdefghij12")
        logger.error("something broke")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("Warning: could not read the phone"))
        self.assertNotIn("abcdefghij", lines[0])                         # tokens never show
        self.assertEqual(lines[1], "Error: something broke")


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class WindowTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit import gui
        isolate_settings(self)
        adb_server._scanned.clear()
        self.addCleanup(adb_server._scanned.clear)
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app._polling = True
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_usb_is_the_default_and_the_switch_changes_the_mode(self):
        self.assertEqual((self.app.link_var.get(), self.app._link_mode), ("usb", "usb"))
        with mock.patch.object(self.app, "_scan"), mock.patch.object(adb_server, "stop_started"):
            self.app.link_var.set("wifi")
            self.app._link_changed()
            self.assertEqual(self.app._link_mode, "wifi")

    def test_leaving_wireless_stops_the_adb_server_we_started(self):
        with mock.patch.object(self.app, "_scan"), mock.patch.object(adb_server, "stop_started") as stop, \
                mock.patch("threading.Thread") as thread:
            self.app.link_var.set("usb")
            self.app._link_changed()
        self.assertEqual(thread.call_args.kwargs["target"], stop)

    def test_each_mode_lists_only_its_own_phones(self):
        both = [{"serial": "6a81a217", "state": "device"}, {"serial": "192.168.1.5:5555", "state": "device"}]
        with mock.patch("mitoolkit.adb.devices", return_value=both), mock.patch.object(adb_server, "running", return_value=True):
            self.assertEqual([d["serial"] for d in self.app._adb_devices(False)], ["6a81a217"])
            self.assertEqual([d["serial"] for d in self.app._adb_devices(True)], ["192.168.1.5:5555"])
        with mock.patch.object(adb_server, "running", return_value=False), mock.patch("mitoolkit.adb.devices") as devices:
            self.assertEqual(self.app._adb_devices(True), [])             # no USB claimed while Wi-Fi is still starting
        devices.assert_not_called()

    def test_wireless_mode_says_what_to_do(self):
        with mock.patch("mitoolkit.platform_tools.find", return_value=None):
            self.assertEqual(self.app._wifi_candidate()["state"], "wifi-no-adb")
        self.app._wifi_probing = True                                    # a search is already running
        with mock.patch("mitoolkit.platform_tools.find", return_value="/sdk/adb"):
            self.assertEqual(self.app._wifi_candidate()["state"], "wifi-search")
            self.app._wifi_found = {"address": "192.168.1.5:39865", "name": "adb-6a81a217"}
            found = self.app._wifi_candidate()
        self.assertEqual((found["state"], found["serial"]), ("wifi-pair", "192.168.1.5:39865"))
        dot, headline, detail, action = self.app._status_for("wifi-pair")
        self.assertIs(action, self.app.wifi_btn)
        self.assertIn("QR code", detail)

    def test_the_search_connects_what_it_can_and_remembers_what_needs_pairing(self):
        found = [{"address": "a:1", "name": "x", "state": "needs-pairing"}, {"address": "b:2", "name": "y", "state": "connected"}]
        with mock.patch.object(adb_server, "discover_and_connect", return_value=found):
            self.app._wifi_probing = True
            self.app._probe_wifi()
        self.assertEqual(self.app._wifi_found["address"], "a:1")
        self.assertFalse(self.app._wifi_probing)
        self.assertEqual(self.app._wifi_probe_at, 0.0)                   # a phone connected: look again at once

    def test_no_show_log_file_item(self):
        bar = self.root.nametowidget(self.root.cget("menu"))
        labels = []
        for i in range(bar.index("end") + 1):
            if bar.type(i) == "cascade":
                menu = self.root.nametowidget(bar.entrycget(i, "menu"))
                labels += [menu.entrycget(j, "label") for j in range(menu.index("end") + 1) if menu.type(j) == "command"]
        self.assertNotIn("Show log file", labels)
        self.assertIn("Activity log", labels)

    def test_the_wireless_window_offers_both_ways_to_pair(self):
        from mitoolkit.ui.wireless_dialog import WirelessDialog
        d = WirelessDialog(self.app)
        self.root.update()
        self.assertEqual(d.method.get(), "qr")
        self.assertTrue(d.qr_panel.winfo_ismapped())
        self.assertFalse(d.code_panel.winfo_ismapped())
        d.method.set("code")
        d._show_method()
        self.root.update()
        self.assertTrue(d.code_panel.winfo_ismapped())
        self.assertFalse(d.qr_panel.winfo_ismapped())
        d.close()

    def test_qr_pairing_draws_a_code_and_connects_after_the_phone_scans(self):
        from mitoolkit.ui.wireless_dialog import WirelessDialog
        d = WirelessDialog(self.app)
        request = {"payload": "WIFI:T:ADB;S:mitoolkit-abc123;P:123456;;", "name": "mitoolkit-abc123", "password": "123456"}
        services = [{"name": "adb-1", "kind": "connect", "address": "192.168.1.5:37445"}]
        scanned = threading.Event()                                       # the phone scans the code when this is set

        def wait_for_scan(name, password, stop, **kw):
            scanned.wait(10)
            return "192.168.1.5:41234"
        with mock.patch.object(adb_server, "pairing_qr", return_value=request), \
                mock.patch.object(adb_server, "wait_for_qr_pairing", side_effect=wait_for_scan), \
                mock.patch.object(adb_server, "mdns_services", return_value=services), \
                mock.patch.object(adb_server, "connect", return_value="192.168.1.5:37445"), mock.patch.object(self.app, "_rescan"):
            d._pair_qr()
            self.root.update()
            self.assertGreater(len(d.qr_canvas.find_all()), 50)            # modules are drawn while it waits
            self.assertIn("Waiting for the phone", d.qr_note.cget("text"))
            scanned.set()                                                 # the phone scans it
            for _ in range(80):
                self.root.update()
                if not d._busy:
                    break
                import time
                time.sleep(0.03)
        self.assertIn("Paired and connected", d.result.cget("text"))
        self.assertLess(len(d.qr_canvas.find_all()), 10)                  # the spent code is gone: the placeholder is back
        self.assertEqual(self.app.link_var.get(), "wifi")                 # and the phone is listed under Wireless
        d.close()

    def test_pairing_keeps_looking_for_the_connect_address_the_phone_announces_late(self):
        """The phone announces its connect address a few seconds after pairing: one look is not enough."""
        from mitoolkit.ui.wireless_dialog import WirelessDialog
        looks = [[], [], [{"name": "adb-1", "kind": "connect", "address": "192.168.1.5:37445"}]]
        silent = adb_server.NothingListening("nothing there")
        with mock.patch.object(adb_server, "mdns_services", side_effect=lambda: looks.pop(0)), \
                mock.patch.object(adb_server, "find_on_host", side_effect=silent), \
                mock.patch.object(adb_server, "connect", return_value="192.168.1.5:37445") as connect:
            result = WirelessDialog._connect_announced("192.168.1.5:41234", wait=5, poll=0.001)
        self.assertEqual(result, ("192.168.1.5:37445", True))
        connect.assert_called_once_with("192.168.1.5:37445")
        with mock.patch.object(adb_server, "mdns_services", return_value=[]), \
                mock.patch.object(adb_server, "find_on_host", side_effect=silent):
            self.assertEqual(WirelessDialog._connect_announced("192.168.1.5:41234", wait=0.05, poll=0.01),
                             ("192.168.1.5:41234", False))                # gives up politely, after the time is up

    def test_when_the_network_never_announces_the_port_is_found_on_the_phones_address(self):
        """A PC on a cable and a phone on Wi-Fi often cannot hear each other's mDNS: the port is looked for directly."""
        from mitoolkit.ui.wireless_dialog import WirelessDialog
        with mock.patch.object(adb_server, "mdns_services", side_effect=AdbError("mDNS unavailable")), \
                mock.patch.object(adb_server, "find_on_host", return_value="192.168.1.5:39865") as scan:
            result = WirelessDialog._connect_announced("192.168.1.5:41234", wait=5, poll=0.001)
        self.assertEqual(result, ("192.168.1.5:39865", True))
        scan.assert_called_once_with("192.168.1.5")

    def test_a_phone_listed_by_its_network_name_is_wireless_and_counts_as_connected(self):
        from mitoolkit.adb_core import is_wireless
        for serial in ("192.168.1.5:39865", "adb-6a81a217-AbCdEf._adb-tls-connect._tcp", "adb-6a81a217-AbCdEf"):
            self.assertTrue(is_wireless(serial), serial)
        self.assertFalse(is_wireless("6a81a217"))
        services = [{"name": "adb-6a81a217-AbCdEf", "kind": "connect", "address": "192.168.1.5:39865"}]
        with mock.patch.object(adb_server, "mdns_services", return_value=services), \
                mock.patch.object(adb_server, "devices", return_value=[
                    {"serial": "adb-6a81a217-AbCdEf._adb-tls-connect._tcp", "state": "device"}]), \
                mock.patch.object(adb_server, "connect") as connect:
            found = adb_server.discover_and_connect()
        self.assertEqual(found[0]["state"], "connected")
        connect.assert_not_called()                                       # it is connected already: nothing to do

    def test_the_serial_row_is_the_phones_own_serial_and_the_wifi_address_has_its_own_row(self):
        base = {"state": "device", "model": "POCO M2 Pro", "battery": 63}
        self.app.android = dict(base, serial="192.168.1.5:39865", serialno="6a81a217")
        pairs = dict(self.app._device_pairs())
        self.assertEqual((pairs["Serial"], pairs["Wi-Fi address"]), ("6a81a217", "192.168.1.5:39865"))
        self.app.android = dict(base, serial="192.168.1.5:39865", serialno=None)      # unknown: never the address
        pairs = dict(self.app._device_pairs())
        self.assertEqual((pairs["Serial"], pairs["Wi-Fi address"]), (None, "192.168.1.5:39865"))
        self.app.android = dict(base, serial="6a81a217")                               # a cable phone
        pairs = dict(self.app._device_pairs())
        self.assertEqual((pairs["Serial"], pairs["Wi-Fi address"]), ("6a81a217", None))

    def test_a_cable_plugged_in_while_on_wifi_switches_to_usb_instead_of_saying_nothing_answers(self):
        """With the selector on Wi-Fi only a stale offline entry was left, and the window said the phone was not
        answering although it was plugged in."""
        app = self.app
        app.link_var.set("wifi")
        app._link_mode = "wifi"
        with mock.patch.object(adb_server, "stop_started") as stop:
            app._cable_plugged_in()
        self.assertEqual((app.link_var.get(), app._link_mode), ("usb", "usb"))
        stop.assert_not_called()                      # the cable is used through whatever adb is already running
        queued = []
        while not app.q.empty():
            queued.append(app.q.get_nowait())
        self.assertTrue(any(kind == "log" and "plugged in with a USB cable" in str(rest[0])
                            for kind, *rest in queued), queued)            # and the Activity log says why
        app._cable_plugged_in()                       # already on USB: nothing changes
        self.assertEqual(app.link_var.get(), "usb")

    def test_a_phone_on_wifi_is_told_up_front_that_fastboot_needs_a_cable(self):
        self.app.android = {"serial": "192.168.1.5:39865", "state": "device", "model": "POCO M2 Pro"}
        _colour, _headline, detail, _button = self.app._status_for("device")
        self.assertIn("USB cable", detail)
        self.app.android = {"serial": "6a81a217", "state": "device", "model": "POCO M2 Pro"}
        _colour, _headline, detail, _button = self.app._status_for("device")
        self.assertNotIn("Wi-Fi", detail)                                        # a cable phone gets the plain text

    def test_the_wifi_search_does_not_hide_a_cable_phone_that_is_ready(self):
        from mitoolkit import adb
        cable = {"serial": "6a81a217", "state": "device", "link": "USB port 2-8"}
        stale = {"serial": "192.168.1.5:39865", "state": "offline", "link": "Wi-Fi 192.168.1.5:39865"}
        with mock.patch.object(adb, "devices", return_value=[cable, stale]):
            self.assertEqual(self.app._adb_devices(True), [stale])           # Wi-Fi mode lists only Wi-Fi entries ...
            ready = [d for d in adb.devices() if d["state"] == "device"]
        self.assertEqual(ready, [cable])                                      # ... and the cable one is what it falls back to

    def test_a_refresh_with_new_readings_updates_the_text_in_place(self):
        """Every refresh used to tear the details down and build them again: a visible flicker."""
        app = self.app
        app.android = {"serial": "192.168.1.5:39865", "state": "device", "serialno": "6a81a217",
                       "model": "POCO M2 Pro", "battery": 63}
        app._render_status()
        self.root.update()
        cells, layout = list(app._info_cells), app._shown_layout
        packed = [str(w) for w in (app.buttons, app.details, app.copy_btn, app.export_btn) if w.winfo_manager()]
        with mock.patch.object(app.buttons, "pack_forget") as forget:
            app.android = dict(app.android, battery=62)
            app._render_status()
        self.root.update()
        forget.assert_not_called()                                         # the sections were not unpacked
        self.assertEqual(app._shown_layout, layout)
        self.assertTrue(all(a is b for a, b in zip(cells, app._info_cells)))      # the same widgets, new text
        self.assertTrue(any("62%" in c.cget("text") for c in app._info_cells))
        self.assertEqual(packed, [str(w) for w in (app.buttons, app.details, app.copy_btn, app.export_btn)
                                  if w.winfo_manager()])

    def test_pairing_resets_the_search_so_the_phone_is_tried_again_at_once(self):
        adb_server._tried["192.168.1.5:39865"] = 1e12
        self.app._wifi_found, self.app._wifi_probe_at = {"address": "x"}, 99.0
        self.app.expect_wifi_phone()
        self.assertEqual((self.app._wifi_found, self.app._wifi_probe_at, adb_server._tried), (None, 0.0, {}))

    def test_cancelling_the_qr_wait_stops_it(self):
        from mitoolkit.ui.wireless_dialog import WirelessDialog
        d = WirelessDialog(self.app)
        stop = threading.Event()
        d._qr_stop_event = stop
        d._qr_stop()
        self.assertTrue(stop.is_set())
        d.close()


if __name__ == "__main__":
    unittest.main()
