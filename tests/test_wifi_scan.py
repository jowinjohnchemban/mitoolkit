"""Finding a phone without mDNS: the port scan, remembered addresses, connecting by address alone, and the search that
falls back to them. The footer's description of how a phone is connected is tested here too."""
import os
import socket
import sys
import threading
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from isolate import isolate_settings  # noqa: E402

from mitoolkit import adb_server, usbio, wifi_scan  # noqa: E402
from mitoolkit.adb_core import describe_link  # noqa: E402
from mitoolkit.adb_usb import AdbError  # noqa: E402


class Listener:
    """A TCP listener on this computer that answers with ``reply`` (or says nothing) to whoever connects."""

    def __init__(self, reply: bytes = b""):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.reply, self.clients = reply, []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            self.clients.append(client)
            if self.reply:
                try:
                    client.sendall(self.reply)
                except OSError:
                    # the test already closed its end: there is nobody to answer
                    pass

    def close(self):
        self.sock.close()
        for client in self.clients:
            client.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ScanTests(unittest.TestCase):
    def test_open_ports_finds_the_listener_among_closed_ports(self):
        listener = Listener()
        self.addCleanup(listener.close)
        closed = free_port()
        self.assertEqual(wifi_scan.open_ports("127.0.0.1", [closed, listener.port], timeout=1.0), [listener.port])

    def test_a_silent_service_does_not_speak_tls(self):
        listener = Listener()
        self.addCleanup(listener.close)
        self.assertFalse(wifi_scan.speaks_tls("127.0.0.1", listener.port, timeout=0.3))

    def test_a_service_that_answers_in_something_else_does_not_speak_tls(self):
        listener = Listener(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        self.addCleanup(listener.close)
        self.assertFalse(wifi_scan.speaks_tls("127.0.0.1", listener.port, timeout=1.0))

    def test_a_closed_port_does_not_speak_tls(self):
        self.assertFalse(wifi_scan.speaks_tls("127.0.0.1", free_port(), timeout=0.3))

    def test_a_tls_server_that_refuses_us_counts(self):
        import ssl
        err = ssl.SSLError(1, "[SSL: TLSV13_ALERT_CERTIFICATE_REQUIRED] certificate required")
        err.reason = "TLSV13_ALERT_CERTIFICATE_REQUIRED"
        with mock.patch("socket.create_connection", side_effect=err):
            self.assertTrue(wifi_scan.speaks_tls("192.168.1.5", 39865))

    def test_candidates_put_tls_first_then_the_legacy_port_and_leave_the_rest(self):
        with mock.patch.object(wifi_scan, "open_ports", return_value=[5555, 38537, 39865, 40000]), \
                mock.patch.object(wifi_scan, "speaks_tls", side_effect=lambda h, p: p in (39865, 40000)):
            self.assertEqual(wifi_scan.candidates("192.168.1.5"), [39865, 40000, 5555])


class HostsTests(unittest.TestCase):
    def setUp(self):
        isolate_settings(self)

    def test_addresses_are_remembered_newest_first_without_repeats_and_capped(self):
        for host in ("192.168.1.5", "192.168.1.6", "192.168.1.5"):
            adb_server.remember_host(host)
        self.assertEqual(adb_server.known_hosts(), ["192.168.1.5", "192.168.1.6"])
        for n in range(10, 20):
            adb_server.remember_host(f"192.168.1.{n}")
        self.assertEqual(len(adb_server.known_hosts()), adb_server.MAX_HOSTS)
        self.assertEqual(adb_server.known_hosts()[0], "192.168.1.19")

    def test_nonsense_in_the_settings_is_ignored(self):
        from mitoolkit import settings
        settings.set(adb_server.HOSTS_KEY, ["192.168.1.5", "not an address", 7])
        self.assertEqual(adb_server.known_hosts(), ["192.168.1.5"])
        settings.set(adb_server.HOSTS_KEY, "192.168.1.5")
        self.assertEqual(adb_server.known_hosts(), [])

    def test_a_successful_connection_or_pairing_remembers_the_phone(self):
        with mock.patch.object(adb_server, "start", return_value=True), \
                mock.patch.object(adb_server, "_host_command", return_value="connected to 192.168.1.5:39865"):
            adb_server.connect("192.168.1.5:39865")
        self.assertEqual(adb_server.known_hosts(), ["192.168.1.5"])
        with mock.patch.object(adb_server, "start", return_value=True), \
                mock.patch.object(adb_server, "_host_command", return_value="Successfully paired to 192.168.1.9:4"):
            adb_server.pair("192.168.1.9:41234", "123456")
        self.assertEqual(adb_server.known_hosts(), ["192.168.1.9", "192.168.1.5"])


class FindOnHostTests(unittest.TestCase):
    def setUp(self):
        isolate_settings(self)
        adb_server._scanned.clear()
        self.addCleanup(adb_server._scanned.clear)
        patcher = mock.patch.object(adb_server, "start", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_address_without_a_port_is_searched_for_its_port(self):
        with mock.patch.object(wifi_scan, "candidates", return_value=[39865]) as scan, \
                mock.patch.object(adb_server, "_host_command", return_value="connected to 192.168.1.5:39865"):
            self.assertEqual(adb_server.connect("192.168.1.5"), "192.168.1.5:39865")
        scan.assert_called_once_with("192.168.1.5")

    def test_an_address_with_a_port_is_not_searched(self):
        with mock.patch.object(wifi_scan, "candidates") as scan, \
                mock.patch.object(adb_server, "_host_command", return_value="connected to 192.168.1.5:39865"):
            adb_server.connect("192.168.1.5:39865")
        scan.assert_not_called()

    def test_nothing_listening_is_said_plainly(self):
        with mock.patch.object(wifi_scan, "candidates", return_value=[]):
            with self.assertRaisesRegex(adb_server.NothingListening, "Wireless debugging on"):
                adb_server.find_on_host("192.168.1.5")

    def test_the_next_port_is_tried_when_the_first_refuses_and_only_a_few_are_tried(self):
        answers = iter([AdbError("refused"), "connected to 192.168.1.5:2"])

        def host(text, timeout=15.0):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer
        with mock.patch.object(wifi_scan, "candidates", return_value=[1, 2, 3, 4, 5]), \
                mock.patch.object(adb_server, "_host_command", side_effect=host):
            self.assertEqual(adb_server.find_on_host("192.168.1.5"), "192.168.1.5:2")
        with mock.patch.object(wifi_scan, "candidates", return_value=[1, 2, 3, 4, 5]), \
                mock.patch.object(adb_server, "_host_command", side_effect=AdbError("refused")) as host:
            with self.assertRaises(AdbError):
                adb_server.find_on_host("192.168.1.5", limit=3)
        self.assertEqual(host.call_count, 3)

    def test_the_search_falls_back_to_remembered_addresses_when_mdns_is_silent(self):
        adb_server.remember_host("192.168.1.5")
        with mock.patch.object(adb_server, "mdns_services", side_effect=AdbError("mDNS unavailable")), \
                mock.patch.object(adb_server, "devices", return_value=[]), \
                mock.patch.object(adb_server, "find_on_host", return_value="192.168.1.5:39865") as find:
            found = adb_server.discover_and_connect()
            again = adb_server.discover_and_connect()                      # soon after: not scanned again
        self.assertEqual(found, [{"address": "192.168.1.5:39865", "name": "", "state": "connected"}])
        self.assertEqual(again[0]["state"], "connected")
        find.assert_called_once_with("192.168.1.5")

    def test_a_remembered_phone_that_is_connected_is_not_scanned(self):
        adb_server.remember_host("192.168.1.5")
        with mock.patch.object(adb_server, "mdns_services", return_value=[]), \
                mock.patch.object(adb_server, "devices", return_value=[{"serial": "192.168.1.5:39865", "state": "device"}]), \
                mock.patch.object(adb_server, "find_on_host") as find:
            found = adb_server.discover_and_connect()
        self.assertEqual(found[0]["state"], "connected")
        find.assert_not_called()

    def test_a_phone_that_refuses_needs_pairing_and_one_that_is_off_is_not_listed(self):
        adb_server.remember_host("192.168.1.5")
        with mock.patch.object(adb_server, "mdns_services", return_value=[]), \
                mock.patch.object(adb_server, "devices", return_value=[]):
            with mock.patch.object(adb_server, "find_on_host", side_effect=AdbError("failed to authenticate")):
                self.assertEqual(adb_server.discover_and_connect()[0]["state"], "needs-pairing")
            adb_server._scanned.clear()
            with mock.patch.object(adb_server, "find_on_host", side_effect=adb_server.NothingListening("off")):
                self.assertEqual(adb_server.discover_and_connect(), [])


class LinkTests(unittest.TestCase):
    def test_a_cable_phone_shows_its_port_and_a_wifi_phone_its_address_and_port(self):
        self.assertEqual(describe_link("6a81a217", "1-3"), "USB port 1-3")
        self.assertEqual(describe_link("6a81a217"), "USB")
        self.assertEqual(describe_link("192.168.1.5:39865"), "Wi-Fi 192.168.1.5:39865")
        self.assertTrue(describe_link("adb-6a81a217-xyz._adb-tls-connect._tcp").startswith("Wi-Fi"))

    def test_the_port_of_the_one_cable_phone_comes_from_libusb_when_adbs_list_does_not_say(self):
        """Newer adb leaves the usb: field out of its device list; libusb still knows where the phone is plugged in."""
        from mitoolkit import adb_usb

        class Dev:
            bus, port_numbers = 2, (8,)
        adb_usb._placed.clear()
        self.addCleanup(adb_usb._placed.clear)
        with mock.patch.object(usbio, "find", return_value=[(Dev(), None)]) as find:
            self.assertEqual(adb_usb._lone_location(["6a81a217"]), {"6a81a217": "2-8"})
            self.assertEqual(adb_usb._lone_location(["6a81a217"]), {"6a81a217": "2-8"})
        self.assertEqual(find.call_count, 1)                                        # found once, not on every scan
        adb_usb._placed.clear()
        with mock.patch.object(usbio, "find", return_value=[(Dev(), None), (Dev(), None)]):
            self.assertEqual(adb_usb._lone_location(["6a81a217"]), {})              # two interfaces: not guessed
        self.assertEqual(adb_usb._lone_location(["a", "b"]), {})                    # two phones: not guessed
        with mock.patch.object(usbio, "find", side_effect=usbio.UsbError("no libusb")):
            self.assertEqual(adb_usb._lone_location(["6a81a217"]), {})              # no USB access: the footer says USB

    def test_the_usb_location_is_the_bus_and_the_chain_of_hub_ports(self):
        class Dev:
            bus, port_numbers = 1, (2, 4)
        self.assertEqual(usbio.location(Dev()), "1-2.4")
        Dev.port_numbers = None
        self.assertIsNone(usbio.location(Dev()))

    def test_usb_locations_are_read_from_the_server_listing(self):
        listing = ("List of devices attached\n6a81a217  device usb:1-3 product:gram model:POCO_M2_Pro transport_id:1\n"
                   "192.168.1.5:39865  device product:gram transport_id:2\n")

        class Conn:
            def request(self, text):
                self.text = text

            def close(self):
                pass
        with mock.patch.object(adb_server, "_Conn", return_value=Conn()), \
                mock.patch.object(adb_server, "_read_text", return_value=listing):
            self.assertEqual(adb_server.usb_locations(), {"6a81a217": "1-3"})


if __name__ == "__main__":
    unittest.main()
