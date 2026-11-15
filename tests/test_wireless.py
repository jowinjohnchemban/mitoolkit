"""Wireless adb: address checks, the Wi-Fi address, switching on, and the fastboot (USB-only) rule."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from miunlock import adb, adb_server  # noqa: E402
from miunlock.adb_usb import AdbError  # noqa: E402


class FakeDev:
    def __init__(self, serial, outputs=None):
        self.serial, self.state, self.outputs, self.tcpip_port = serial, "device", outputs or {}, None

    def shell(self, command, timeout_ms=60000):
        for key, out in self.outputs.items():
            if key in command:
                return out
        return ""

    def tcpip(self, port):
        self.tcpip_port = port

    def close(self):
        pass


def phone(serial, outputs=None):
    p = adb.Phone.__new__(adb.Phone)
    p._dev, p.serial = FakeDev(serial, outputs), serial
    return p


class AddressTests(unittest.TestCase):
    def test_valid_addresses(self):
        self.assertEqual(adb_server.valid_address(" 192.168.1.5 "), "192.168.1.5:5555")
        self.assertEqual(adb_server.valid_address("10.0.0.2:5556"), "10.0.0.2:5556")
        for bad in ("", "phone", "1.2.3", "300.1.1.1", "1.2.3.4:0", "1.2.3.4:x", "1.2.3.4:99999"):
            self.assertIsNone(adb_server.valid_address(bad), bad)

    def test_connect_rejects_a_bad_address_without_touching_the_network(self):
        with mock.patch.object(adb_server, "_host_command") as host:
            with self.assertRaises(AdbError):
                adb_server.connect("not an address")
            host.assert_not_called()


class PhoneTests(unittest.TestCase):
    def test_wifi_address_is_read_from_the_phone(self):
        p = phone("6a81a217", {"wlan0": "    inet 192.168.1.5/24 brd 192.168.1.255 scope global wlan0"})
        self.assertEqual(p.wifi_address(), "192.168.1.5")
        self.assertIsNone(phone("6a81a217").wifi_address())

    def test_enable_wireless_switches_the_phone_then_connects(self):
        p = phone("6a81a217", {"wlan0": "inet 192.168.1.5/24"})
        with mock.patch.object(adb_server, "start", return_value=True), \
                mock.patch.object(adb_server, "connect", return_value="192.168.1.5:5555") as connect, \
                mock.patch("time.sleep"):
            self.assertEqual(p.enable_wireless(), "192.168.1.5:5555")
        self.assertEqual(p._dev.tcpip_port, 5555)
        connect.assert_called_once_with("192.168.1.5:5555")

    def test_enable_wireless_needs_wifi_and_google_adb(self):
        with self.assertRaises(AdbError):
            phone("6a81a217").enable_wireless()                      # not on Wi-Fi
        with mock.patch.object(adb_server, "start", return_value=False):
            with self.assertRaises(AdbError):
                phone("6a81a217", {"wlan0": "inet 192.168.1.5/24"}).enable_wireless()

    def test_a_wifi_phone_will_not_reboot_into_fastboot(self):
        p = phone("192.168.1.5:5555")
        self.assertTrue(p.wireless)
        with self.assertRaisesRegex(AdbError, "USB cable"):
            p.reboot_to_bootloader()
        self.assertFalse(phone("6a81a217").wireless)


if __name__ == "__main__":
    unittest.main()
