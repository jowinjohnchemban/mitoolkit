"""Tests for mitoolkit's own adb and fastboot clients, against a fake USB device.

Nothing here touches a real phone or USB. The adb key test makes a real (temporary) key.
"""
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mitoolkit import adb_usb, adbkey, bloat, fastboot_usb, usbio


class FakeHandle:
    """Stands in for usbio.Handle: records writes, replays queued reads."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.writes = []
        self.max_packet = 512

    def write(self, data, timeout_ms=5000, zlp=False):
        self.writes.append(bytes(data))
        if zlp and data and len(data) % self.max_packet == 0:
            self.writes.append(b"")

    def read(self, size, timeout_ms=5000):
        if not self.replies:
            raise usbio.UsbTimeout("timeout")
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        assert len(item) <= size, f"device sent {len(item)} bytes but host asked for {size}"
        return item

    def close(self):
        pass


def msg(cmd, a0, a1, data=b""):
    """A device-to-host adb message: header then payload, as separate transfers."""
    out = [adb_usb.pack(cmd, a0, a1, data)]
    if data:
        out.append(data)
    return out


_KEY = None


def shared_key():
    global _KEY
    if _KEY is None:
        _KEY = adbkey.generate()
    return _KEY


class AdbKeyTests(unittest.TestCase):
    def test_signature_is_pkcs1_sha1_over_token(self):
        key = shared_key()
        token = os.urandom(20)
        sig = key.sign_token(token)
        self.assertEqual(len(sig), 256)
        em = pow(int.from_bytes(sig, "big"), key.e, key.n).to_bytes(256, "big")
        self.assertTrue(em.startswith(b"\x00\x01\xff"))
        self.assertTrue(em.endswith(bytes.fromhex("3021300906052b0e03021a05000414") + token))

    def test_pem_round_trip(self):
        key = shared_key()
        again = adbkey.from_pem(key.to_pem())
        self.assertEqual((again.n, again.e, again.d), (key.n, key.e, key.d))

    def test_public_key_format(self):
        key = shared_key()
        blob = key.adb_public_key()
        self.assertTrue(blob.endswith(b"\x00"))  # adbd expects a NUL-terminated string
        raw = __import__("base64").b64decode(blob.split(b" ")[0])
        words, n0inv = struct.unpack("<II", raw[:8])
        self.assertEqual(words, 64)
        self.assertEqual(int.from_bytes(raw[8:264], "little"), key.n)
        self.assertEqual((n0inv * key.n) % (1 << 32), (1 << 32) - 1)  # n0inv = -1/n mod 2^32
        self.assertEqual(int.from_bytes(raw[264:520], "little"), pow(2, 4096, key.n))
        self.assertEqual(struct.unpack("<I", raw[520:524])[0], 65537)

    def test_matches_cryptography_if_available(self):
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, utils
        except ImportError:
            self.skipTest("cryptography not installed")
        key = shared_key()
        loaded = serialization.load_pem_private_key(key.to_pem().encode(), password=None)
        token = os.urandom(20)
        loaded.public_key().verify(key.sign_token(token), token, padding.PKCS1v15(), utils.Prehashed(hashes.SHA1()))
        theirs = loaded.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()).decode()
        self.assertEqual(adbkey.from_pem(theirs).n, key.n)

    def test_key_file_is_created_private(self):
        key = shared_key()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"ANDROID_USER_HOME": tmp}), \
                mock.patch.object(adbkey, "_cached", None), mock.patch.object(adbkey, "generate", lambda: key):
            adbkey.load_or_create()
            self.assertTrue((Path(tmp) / "adbkey").exists())
            self.assertTrue((Path(tmp) / "adbkey.pub").exists())
            if os.name == "posix":
                self.assertEqual((Path(tmp) / "adbkey").stat().st_mode & 0o777, 0o600)


class AdbProtocolTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(adbkey, "load_or_create", shared_key)
        p.start()
        self.addCleanup(p.stop)

    def device(self, replies):
        fake = FakeHandle(replies)
        with mock.patch.object(usbio, "Handle", lambda dev, intf: fake):
            dev = adb_usb.AdbDevice(None, None, "SERIAL")
        return dev, fake

    def test_connect_without_auth(self):
        dev, fake = self.device(msg(adb_usb.A_CNXN, adb_usb.VERSION, 4096, b"device::"))
        self.assertEqual(dev.connect(), "device")
        cmd, a0, a1, length = struct.unpack("<4I", fake.writes[0][:16])
        self.assertEqual((cmd, a0), (adb_usb.A_CNXN, adb_usb.VERSION))
        self.assertEqual(fake.writes[1], b"host::features=")  # no NUL, as Google's host

    def test_unknown_key_sends_public_key_then_waits(self):
        token = os.urandom(20)
        dev, fake = self.device(msg(adb_usb.A_AUTH, 1, 0, token) + msg(adb_usb.A_AUTH, 1, 0, token))
        self.assertEqual(dev.connect(), "unauthorized")
        sig_header = struct.unpack("<6I", fake.writes[2])
        self.assertEqual(sig_header[:2], (adb_usb.A_AUTH, adb_usb.AUTH_SIGNATURE))
        pub_header = struct.unpack("<6I", fake.writes[-2])
        self.assertEqual(pub_header[:2], (adb_usb.A_AUTH, adb_usb.AUTH_RSAPUBLICKEY))
        self.assertTrue(fake.writes[-1].endswith(b"\x00"))
        fake.replies += msg(adb_usb.A_CNXN, adb_usb.VERSION, 4096, b"device::")
        self.assertEqual(dev.poll_authorized(), "device")

    def test_zero_length_packet_after_full_packet_payload(self):
        dev, fake = self.device([])
        dev._send(adb_usb.A_WRTE, 1, 2, b"x" * 512)
        self.assertEqual(fake.writes[-1], b"")

    def test_shell_collects_output_and_acks(self):
        dev, fake = self.device(msg(adb_usb.A_CNXN, adb_usb.VERSION, 4096, b"device::"))
        dev.connect()
        fake.replies += (msg(adb_usb.A_OKAY, 7, 1) + msg(adb_usb.A_WRTE, 7, 1, b"[ro.a]: [1]\r\n")
                         + msg(adb_usb.A_WRTE, 7, 1, b"hello") + msg(adb_usb.A_CLSE, 7, 1))
        self.assertEqual(dev.shell("getprop"), "[ro.a]: [1]\nhello")
        okays = [w for w in fake.writes if w[:4] == struct.pack("<I", adb_usb.A_OKAY)]
        self.assertEqual(len(okays), 2)

    def test_sync_list_and_recv(self):
        dev, fake = self.device(msg(adb_usb.A_CNXN, adb_usb.VERSION, 4096, b"device::"))
        dev.connect()
        sync = dev.sync()
        fake.replies += msg(adb_usb.A_OKAY, 9, 1)  # sync: opened
        dent = lambda name, mode, size: (b"DENT" + struct.pack("<IIII", mode, size, 1700000000, len(name)) + name)
        listing = dent(b".", 0o040755, 0) + dent(b"a.jpg", 0o100644, 3) + dent(b"Sub", 0o040755, 0) \
            + b"DONE" + b"\0" * 16
        fake.replies += msg(adb_usb.A_OKAY, 9, 1) + msg(adb_usb.A_WRTE, 9, 1, listing)
        entries = sync.listdir("/sdcard/DCIM/")
        self.assertEqual([e[0] for e in entries], ["a.jpg", "Sub"])
        data = b"DATA" + struct.pack("<I", 3) + b"abc" + b"DONE" + struct.pack("<I", 0)
        fake.replies += msg(adb_usb.A_OKAY, 9, 1) + msg(adb_usb.A_WRTE, 9, 1, data)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.jpg"
            self.assertEqual(sync.recv("/sdcard/DCIM/a.jpg", out), 3)
            self.assertEqual(out.read_bytes(), b"abc")

    def test_recv_failure_leaves_no_partial_file(self):
        dev, fake = self.device(msg(adb_usb.A_CNXN, adb_usb.VERSION, 4096, b"device::"))
        dev.connect()
        sync = dev.sync()
        fake.replies += msg(adb_usb.A_OKAY, 9, 1)
        fail = b"FAIL" + struct.pack("<I", 6) + b"denied"
        fake.replies += msg(adb_usb.A_OKAY, 9, 1) + msg(adb_usb.A_WRTE, 9, 1, fail)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(adb_usb.AdbError):
                sync.recv("/x", Path(tmp) / "x")
            self.assertEqual(list(Path(tmp).iterdir()), [])


class FastbootProtocolTests(unittest.TestCase):
    def device(self, replies):
        fake = FakeHandle(replies)
        with mock.patch.object(usbio, "open_first", lambda triple, serial=None: (fake, "FB1")):
            return fastboot_usb.FastbootDevice(), fake

    def test_getvar(self):
        fb, fake = self.device([b"OKAYgarnet"])
        self.assertEqual(fb.getvar("product"), "garnet")
        self.assertEqual(fake.writes, [b"getvar:product"])

    def test_getvar_missing_is_none(self):
        fb, _ = self.device([b"FAILunknown variable"])
        self.assertIsNone(fb.getvar("nope"))

    def test_token_from_info_lines(self):
        fb, _ = self.device([b"INFOtoken:AAAA", b"INFOtoken:BBBB", b"OKAY"])
        _reply, info = fb.oem("get_token")
        self.assertEqual(fastboot_usb.parse_token(info), "AAAABBBB")

    def test_download_sends_size_then_data_without_zlp(self):
        data = b"z" * 512
        fb, fake = self.device([b"DATA00000200", b"OKAY"])
        fb.download(data)
        self.assertEqual(fake.writes, [b"download:00000200", data])

    def test_download_size_mismatch_is_refused(self):
        fb, fake = self.device([b"DATA00000100"])
        with self.assertRaises(fastboot_usb.FastbootError):
            fb.download(b"z" * 512)
        self.assertEqual(len(fake.writes), 1)  # nothing sent after the bad DATA reply

    def test_fail_is_reported(self):
        fb, _ = self.device([b"FAILnot allowed"])
        with self.assertRaises(fastboot_usb.Refused) as ctx:
            fb.oem("unlock")
        self.assertIn("not allowed", str(ctx.exception))


class AppManagerTests(unittest.TestCase):
    def test_package_names_are_validated(self):
        from mitoolkit import adb
        for bad in ("com.x; reboot", "com.x && rm", "../x", "x", "com.x$(id)"):
            with self.assertRaises(adb.AdbError):
                adb._valid(bad)
        self.assertEqual(adb._valid("com.miui.msa.global"), "com.miui.msa.global")

    def test_unlock_critical_apps_are_marked_avoid(self):
        for pkg in ("com.xiaomi.account", "com.miui.cloudservice", "com.miui.securitycenter"):
            self.assertEqual(bloat.KNOWN[pkg][1], "avoid")
        for pkg, (_name, rating, _note) in bloat.KNOWN.items():
            self.assertIn(rating, bloat.RATINGS, pkg)


if __name__ == "__main__":
    unittest.main()
