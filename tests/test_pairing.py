"""Wireless adb pairing: input checks, the adb server calls, finding phones, and the dialog."""
import os
import sys
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from mitoolkit import adb_server  # noqa: E402
from mitoolkit.adb_usb import AdbError  # noqa: E402

try:
    import tkinter as tk
    tk.Tk().destroy()
    HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False

MDNS = ("List of discovered mdns services\n"
        "adb-6a81a217-abc\t_adb-tls-connect._tcp\t192.168.1.5:37445\n"
        "adb-6a81a217-xyz\t_adb-tls-pairing._tcp\t192.168.1.5:41234\n"
        "printer\t_ipp._tcp\t192.168.1.9:631\n")


class InputTests(unittest.TestCase):
    def test_pairing_needs_a_port(self):
        self.assertIsNone(adb_server.valid_address("192.168.1.5", require_port=True))
        self.assertEqual(adb_server.valid_address("192.168.1.5:41234", require_port=True), "192.168.1.5:41234")
        self.assertEqual(adb_server.valid_address("192.168.1.5"), "192.168.1.5:5555")   # connecting keeps its default

    def test_bad_input_never_reaches_the_server(self):
        with mock.patch.object(adb_server, "_host_command") as host:
            for address, code in (("192.168.1.5", "123456"), ("192.168.1.5:41234", "12345"),
                                  ("192.168.1.5:41234", "12345a"), ("phone:1", "123456")):
                with self.assertRaises(AdbError):
                    adb_server.pair(address, code)
            host.assert_not_called()


class PairTests(unittest.TestCase):
    def test_success_sends_code_then_address(self):
        with mock.patch.object(adb_server, "start", return_value=True), mock.patch.object(
                adb_server, "_host_command",
                return_value="Successfully paired to 192.168.1.5:41234 [guid=adb-6a81a217-xyz]") as host:
            self.assertEqual(adb_server.pair(" 192.168.1.5:41234 ", " 123456 "), "192.168.1.5:41234")
        host.assert_called_once_with("host:pair:123456:192.168.1.5:41234", timeout=30.0)

    def test_a_refusal_says_how_to_retry_and_never_repeats_the_code(self):
        with mock.patch.object(adb_server, "start", return_value=True), mock.patch.object(
                adb_server, "_host_command", side_effect=AdbError("Failed: Wrong password")):
            with self.assertRaises(AdbError) as caught:
                adb_server.pair("192.168.1.5:41234", "123456")
        self.assertIn("new code", str(caught.exception))
        self.assertNotIn("123456", str(caught.exception))

    def test_needs_google_adb(self):
        with mock.patch.object(adb_server, "start", return_value=False):
            with self.assertRaisesRegex(AdbError, "Google's adb"):
                adb_server.pair("192.168.1.5:41234", "123456")


class FindTests(unittest.TestCase):
    def find(self, text):
        replies = {"host:mdns:check": "mdns daemon version [Openscreen discovery 0.0.0]", "host:mdns:services": text}
        with mock.patch.object(adb_server, "start", return_value=True), mock.patch.object(
                adb_server, "_host_command", side_effect=lambda cmd, timeout=15.0: replies[cmd]):
            return adb_server.mdns_services()

    def test_lists_pairing_and_connect_services_only(self):
        self.assertEqual(self.find(MDNS), [
            {"name": "adb-6a81a217-abc", "kind": "connect", "address": "192.168.1.5:37445"},
            {"name": "adb-6a81a217-xyz", "kind": "pairing", "address": "192.168.1.5:41234"}])

    def test_unavailable_mdns_is_explained(self):
        with mock.patch.object(adb_server, "start", return_value=True), mock.patch.object(
                adb_server, "_host_command", return_value="ERROR: mdns daemon unavailable"):
            with self.assertRaisesRegex(AdbError, "Type the address"):
                adb_server.mdns_services()


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class DialogTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit import gui
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app._polling = True
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def finish(self, dialog):
        for _ in range(60):
            self.root.update()
            if not dialog._busy:
                break
            self.root.after(50)
            import time
            time.sleep(0.05)

    def test_find_fills_the_addresses(self):
        from mitoolkit.ui.wireless_dialog import WirelessDialog
        d = WirelessDialog(self.app)
        services = [{"name": "a", "kind": "pairing", "address": "192.168.1.5:41234"},
                    {"name": "b", "kind": "connect", "address": "192.168.1.5:37445"}]
        with mock.patch.object(adb_server, "mdns_services", return_value=services), mock.patch.object(
                self.app, "_rescan"):
            d._find()
            self.finish(d)
        self.assertEqual(d.pair_address.get(), "192.168.1.5:41234")
        self.assertEqual(d.address.get(), "192.168.1.5:37445")
        self.assertIn("6-digit code", d.result.cget("text"))
        d.close()

    def test_pair_checks_input_then_pairs_connects_and_clears_the_code(self):
        from mitoolkit.ui.wireless_dialog import WirelessDialog
        d = WirelessDialog(self.app)
        d.pair_address.set("192.168.1.5")
        d.pair_code.set("123456")
        d._pair()
        self.assertIn("port", d.result.cget("text"))                  # refused before any work started
        d.pair_address.set("192.168.1.5:41234")
        services = [{"name": "b", "kind": "connect", "address": "192.168.1.5:37445"}]
        with mock.patch.object(adb_server, "pair", return_value="192.168.1.5:41234") as pair, mock.patch.object(
                adb_server, "mdns_services", return_value=services), mock.patch.object(
                adb_server, "connect", return_value="192.168.1.5:37445") as connect, mock.patch.object(
                self.app, "_rescan"):
            d._pair()
            self.finish(d)
        pair.assert_called_once_with("192.168.1.5:41234", "123456")
        connect.assert_called_once_with("192.168.1.5:37445")
        self.assertEqual(d.pair_code.get(), "")
        self.assertIn("Paired and connected", d.result.cget("text"))
        d.close()

    def test_unauthorized_phone_gets_a_plain_instruction(self):
        from mitoolkit.ui.wireless_dialog import WirelessDialog
        self.app.android = {"serial": "192.168.1.5:5555", "state": "unauthorized"}
        d = WirelessDialog(self.app)
        self.assertIn("Always allow", d.state.cget("text"))
        d.close()


if __name__ == "__main__":
    unittest.main()
