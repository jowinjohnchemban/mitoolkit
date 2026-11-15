"""Tests for the shared building blocks: Xiaomi server client, fastboot backends, errors,
CLI JSON commands. Nothing touches the network or a phone."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from miunlock import adb, api, cli, drivers, fastboot, usbio, xiaomi
from miunlock.errors import MiunlockError, UnlockError

SERVICE = {"servicedata": {"ssecurity": "s", "deviceId": "dev"}, "cookies": {"userId": "1"}}


class ErrorHierarchyTests(unittest.TestCase):
    def test_every_error_type_shares_the_base(self):
        for cls in (UnlockError, xiaomi.ServerError, adb.AdbError, fastboot.FastbootError,
                    usbio.UsbError, drivers.DriverError, api.UnlockError):
            self.assertTrue(issubclass(cls, MiunlockError), cls)

    def test_one_error_type_per_layer(self):
        from miunlock import adb_usb, fastboot_usb
        self.assertIs(adb.AdbError, adb_usb.AdbError)
        self.assertIs(fastboot.FastbootError, fastboot_usb.FastbootError)


class UnlockServerTests(unittest.TestCase):
    def test_each_request_gets_a_fresh_nonce(self):
        calls = []

        def send(path, params, domain, ssecurity, cookies):
            calls.append((path, params))
            if path == "/api/v2/nonce":
                return {"code": 0, "nonce": f"n{len(calls)}"}
            if path == "/api/v2/unlock/device/clear":
                return {"code": 0, "cleanOrNot": 1}
            return {"code": 0, "encryptData": "0a0b"}

        with mock.patch.object(xiaomi, "_send", side_effect=send):
            server = xiaomi.UnlockServer(SERVICE, "India")
            self.assertEqual(server.domain, "https://in-unlock.update.intl.miui.com")
            server.device_clear("garnet")
            self.assertEqual(server.unlock_data("garnet", "TOKEN"), b"\x0a\x0b")
        nonces = [p["nonce"] for path, p in calls if path != "/api/v2/nonce"]
        self.assertEqual(len(set(nonces)), 2)
        unlock_params = calls[-1][1]["data"]
        self.assertEqual(unlock_params["deviceToken"], "TOKEN")
        self.assertEqual(unlock_params["deviceInfo"]["product"], "garnet")

    def test_refusal_carries_code_and_description(self):
        def send(path, *a):
            return {"code": 0, "nonce": "n"} if path == "/api/v2/nonce" else {"code": 20036, "descEN": "wait"}

        with mock.patch.object(xiaomi, "_send", side_effect=send):
            with self.assertRaises(xiaomi.ServerError) as ctx:
                xiaomi.UnlockServer(SERVICE, "Europe").unlock_data("p", "t")
        self.assertEqual((ctx.exception.code, ctx.exception.description), (20036, "wait"))

    def test_region_to_zone(self):
        self.assertEqual(xiaomi.zone_for_region("IN"), "India")
        self.assertEqual(xiaomi.zone_for_region("DE"), "Europe")
        self.assertEqual(xiaomi.zone_for_region("US"), "Singapore")
        self.assertEqual(xiaomi.zone_for_region(None), "Singapore")

    def test_unknown_zone_is_refused(self):
        with self.assertRaises(UnlockError):
            xiaomi.UnlockServer(SERVICE, "Mars")


class FastbootBackendTests(unittest.TestCase):
    def test_default_backend_is_usb(self):
        with mock.patch.object(fastboot, "_backend", None):
            self.assertIsInstance(fastboot.backend(), fastboot.UsbBackend)

    def test_android_is_refused_with_a_clear_message(self):
        import miunlock.system
        with mock.patch.object(usbio, "_backend", None), mock.patch.object(miunlock.system, "IS_ANDROID", True):
            with self.assertRaises(usbio.UsbUnavailable) as ctx:
                usbio.backend()
        self.assertIn("computer", str(ctx.exception))

    def test_module_functions_use_the_backend(self):
        fake = mock.Mock(spec=fastboot.Backend)
        fake.getvar.return_value = "garnet"
        fake.token.return_value = "TOK"
        with mock.patch.object(fastboot, "_backend", fake), mock.patch.object(fastboot, "wait_for_device"):
            self.assertEqual(fastboot.get_product(), "garnet")
            self.assertEqual(fastboot.get_token(), "TOK")
            fastboot.stage_and_unlock(b"x")
        fake.stage_and_unlock.assert_called_once_with(b"x")

    def test_missing_token_is_an_error(self):
        fake = mock.Mock(spec=fastboot.Backend)
        fake.token.return_value = None
        with mock.patch.object(fastboot, "_backend", fake):
            with self.assertRaises(fastboot.FastbootError):
                fastboot.get_token()


class CliTests(unittest.TestCase):
    def run_cmd(self, fn, args):
        out = io.StringIO()
        code = 0
        with redirect_stdout(out):
            try:
                fn(args)
            except SystemExit as e:
                code = e.code
        return code, json.loads(out.getvalue())

    def test_error_becomes_json_and_exit_1(self):
        with mock.patch.object(cli.api, "list_devices", side_effect=adb.AdbError("no usb")):
            code, data = self.run_cmd(cli._cmd_devices, mock.Mock())
        self.assertEqual((code, data), (1, {"error": "no usb"}))

    def test_unlock_refuses_without_confirm_wipe(self):
        with mock.patch.object(cli.api, "login", side_effect=AssertionError("must not log in")):
            code, data = self.run_cmd(cli._cmd_unlock, mock.Mock(confirm_wipe=False))
        self.assertEqual(code, 1)
        self.assertFalse(data["success"])

    def test_internal_session_never_printed(self):
        with mock.patch.object(cli.api, "login", return_value={}), \
                mock.patch.object(cli.api, "check_unlock_eligibility",
                                  return_value={"eligible": False, "_service": {"secret": 1}}):
            code, data = self.run_cmd(cli._cmd_check, mock.Mock())
        self.assertNotIn("_service", data)


if __name__ == "__main__":
    unittest.main()
