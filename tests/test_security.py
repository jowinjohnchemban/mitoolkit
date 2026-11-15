"""Regression tests for the places where a secret could leak, and for the unlock gate.

Everything uses dummy values. Nothing here touches the network, a real session
file, a real device, or fastboot.
"""
import json
import logging
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from mitoolkit import api, log, mcp, xiaomi
from mitoolkit.auth import browser, requester, store
from mitoolkit.auth.redact import mask_id, redact_response
from mitoolkit.hints import explain

SECRET = "SUPER-SECRET-TOKEN-123"


class RedactionTests(unittest.TestCase):
    def test_values_are_hidden_but_status_is_kept(self):
        out = redact_response({
            "code": 70016,
            "desc": "wrong password",
            "passToken": SECRET,
            "location": "https://example.invalid/?ticket=" + SECRET,
        })
        self.assertNotIn(SECRET, out)
        self.assertIn("70016", out)
        self.assertIn("passToken", out)  # the field name is shown, never its value

    def test_non_dict_response_is_not_echoed(self):
        self.assertNotIn(SECRET, redact_response(SECRET))
        self.assertNotIn(SECRET, redact_response([SECRET]))

    def test_account_id_is_masked(self):
        self.assertEqual(mask_id("1234567890"), "123***890")
        self.assertNotIn("4567", mask_id("1234567890"))
        self.assertNotIn("12", mask_id("12345"))  # short values are fully masked


class RequesterTests(unittest.TestCase):
    def test_failed_request_does_not_leak_the_url(self):
        err = requests.exceptions.ConnectionError(f"Max retries exceeded with url: /x?token={SECRET}")
        with mock.patch.object(requester.session, "request", side_effect=err):
            with self.assertRaises(ConnectionError) as ctx:
                requester.get("https://account.xiaomi.com/x?token=" + SECRET)
        self.assertNotIn(SECRET, str(ctx.exception))
        # The original exception, which contains the URL, must not be chained either,
        # or an unhandled error would print it in a traceback.
        self.assertTrue(ctx.exception.__suppress_context__)
        self.assertIsNone(ctx.exception.__cause__)


class SessionStoreTests(unittest.TestCase):
    """The saved session must never sit on disk readable, and must survive a round trip."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patch in (mock.patch.object(store, "ROOT", Path(self.tmp.name)),
                      mock.patch.object(store, "_keyring", return_value=None)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_round_trip(self):
        where = store.save("t", {"passToken": SECRET})
        self.assertIn(where, (store.DPAPI, store.FILE, store.FILE_OPEN))
        self.assertEqual(store.load("t"), {"passToken": SECRET})

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows only")
    def test_windows_file_is_encrypted(self):
        self.assertEqual(store.save("t", {"passToken": SECRET}), store.DPAPI)
        blob = (Path(self.tmp.name) / "t" / "session.dpapi").read_bytes()
        self.assertNotIn(SECRET.encode(), blob)
        self.assertFalse((Path(self.tmp.name) / "t" / "session.json").exists())

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_posix_file_is_private(self):
        store.save("t", {"passToken": SECRET})
        path = Path(self.tmp.name) / "t" / "session.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_delete_removes_everything(self):
        store.save("t", {"passToken": SECRET})
        store.delete("t")
        self.assertIsNone(store.load("t"))

    def test_keyring_is_preferred_and_no_file_is_left(self):
        fake = mock.MagicMock()
        fake.set_password.side_effect = lambda svc, sid, value: setattr(fake.get_password, "return_value", value)
        with mock.patch.object(store, "_keyring", return_value=fake):
            self.assertEqual(store.save("t", {"passToken": SECRET}), store.KEYRING)
            self.assertEqual(store.load("t"), {"passToken": SECRET})
        self.assertFalse((Path(self.tmp.name) / "t" / "session.json").exists())

    def test_session_without_timestamp_is_expired_and_removed(self):
        old = Path(self.tmp.name) / "t" / "session.json"
        old.parent.mkdir()
        old.write_text(json.dumps({"passToken": SECRET}), encoding="utf-8")
        self.assertIsNone(store.load("t"))
        self.assertFalse(old.exists())

    def test_session_expires_after_the_ttl(self):
        store.save("t", {"passToken": SECRET})
        later = time.time() + 25 * 3600  # default TTL is 24 hours
        with mock.patch.object(store.time, "time", return_value=later):
            self.assertIsNone(store.load("t"))
        self.assertIsNone(store.load("t"))  # and it was deleted, not just ignored

    def test_ttl_can_be_shortened_and_zero_disables_reuse(self):
        store.save("t", {"passToken": SECRET})
        with mock.patch.dict(os.environ, {"MITOOLKIT_SESSION_TTL_HOURS": "0"}):
            self.assertIsNone(store.load("t"))

    def test_stamp_is_not_returned_to_callers(self):
        store.save("t", {"passToken": SECRET})
        self.assertNotIn(store.STAMP, store.load("t"))


class LogTests(unittest.TestCase):
    def test_scrubber_hides_secrets_but_keeps_status(self):
        rec = logging.LogRecord("x", logging.INFO, "", 0,
                                f"passToken={SECRET} userId: 1234567890 code=20036 blob {'A' * 40}", None, None)
        log.Scrubber().filter(rec)
        self.assertNotIn(SECRET, rec.msg)
        self.assertNotIn("1234567890", rec.msg)
        self.assertNotIn("A" * 40, rec.msg)
        self.assertIn("20036", rec.msg)

    def test_log_goes_next_to_the_executable_and_is_scrubbed(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = logging.getLogger("mitoolkit")
            old = (list(logger.handlers), log._path)
            logger.handlers, log._path = [], None
            try:
                with mock.patch.object(log.sys, "frozen", True, create=True),                         mock.patch.object(log.sys, "executable", str(Path(tmp) / "mitoolkit.exe")):
                    path = log.setup()
                    log.get("t").info("ssecurity=%s", SECRET)
                    for h in logger.handlers:
                        h.flush()
                    self.assertEqual(path, (Path(tmp) / "mitoolkit.log").resolve())
                    text = path.read_text(encoding="utf-8")
                    self.assertIn("started", text)
                    self.assertNotIn(SECRET, text)
                    for h in logger.handlers:
                        h.close()
            finally:
                logger.handlers, log._path = old

    def test_unwritable_folder_does_not_break_the_program(self):
        with mock.patch.object(log, "RotatingFileHandler", side_effect=OSError),                 mock.patch.object(log, "_path", None):
            self.assertIsNone(log.setup())


class AgentInterfaceTests(unittest.TestCase):
    def call(self, name, args=None):
        return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}})

    def test_unlock_is_not_available_to_agents(self):
        tools = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertFalse([t for t in tools if "unlock" in t["name"]])
        self.assertIn("error", self.call("unlock", {"confirm_wipe": True}))

    def test_check_never_returns_the_session(self):
        fake = {"eligible": True, "product": "x", "zone": "India", "_service": {"ssecurity": SECRET}}
        with mock.patch.object(mcp.api, "list_devices", return_value={"android": [], "fastboot": ["s"]}),                 mock.patch.object(mcp.api, "login", return_value={}),                 mock.patch.object(mcp.api, "check_unlock_eligibility", return_value=fake):
            text = json.dumps(self.call("check_eligibility"))
        self.assertNotIn(SECRET, text)
        self.assertIn("India", text)

    def test_check_does_not_hang_without_a_phone(self):
        with mock.patch.object(mcp.api, "list_devices", return_value={"android": [], "fastboot": []}):
            self.assertIn("No phone", json.dumps(self.call("check_eligibility")))

    def test_notifications_get_no_reply_and_unknown_methods_error(self):
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "nope"})["error"]["code"], -32601)


class OpenUrlTests(unittest.TestCase):
    def test_only_https_or_local_http_is_opened(self):
        for url in ("http://evil.example/", "file:///etc/passwd", "javascript:alert(1)", "ftp://x/"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    browser.open_url(url)

    def test_url_is_never_passed_through_a_shell(self):
        nasty = "https://example.invalid/'; touch /tmp/pwned; '"
        with mock.patch.object(browser.platform, "system", return_value="Linux"), \
                mock.patch.object(browser.subprocess, "run") as run:
            browser.open_url(nasty)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["xdg-open", nasty])  # one argument, not a command string
        self.assertFalse(kwargs.get("shell", False))

    def test_local_captcha_page_is_allowed(self):
        with mock.patch.object(browser.platform, "system", return_value="Windows"), \
                mock.patch.object(browser.webbrowser, "open") as opened:
            browser.open_url("http://127.0.0.1:5000")
        opened.assert_called_once()


class UnlockGateTests(unittest.TestCase):
    """perform_unlock must refuse, and touch neither fastboot nor the network."""

    def setUp(self):
        for name in ("get_token", "stage_and_unlock", "get_product"):
            guard = mock.patch.object(api.fastboot, name, side_effect=AssertionError("fastboot was reached"))
            guard.start()
            self.addCleanup(guard.stop)
        send = mock.patch.object(xiaomi, "_send", side_effect=AssertionError("network was reached"))
        send.start()
        self.addCleanup(send.stop)

    def test_refuses_without_confirmation(self):
        with self.assertRaises(api.UnlockError):
            api.perform_unlock({}, {"eligible": True, "_service": {}}, confirm_wipe=False)

    def test_confirmation_cannot_be_omitted(self):
        with self.assertRaises(TypeError):
            api.perform_unlock({}, {"eligible": True, "_service": {}})  # type: ignore[call-arg]

    def test_refuses_when_not_eligible_even_if_confirmed(self):
        with self.assertRaises(api.UnlockError):
            api.perform_unlock({}, {"eligible": False}, confirm_wipe=True)

    def test_refuses_a_hand_built_eligibility(self):
        with self.assertRaises(api.UnlockError):
            api.perform_unlock({}, {"eligible": True}, confirm_wipe=True)


class HintTests(unittest.TestCase):
    def test_waiting_period_reports_the_hours(self):
        hint = explain(20036, "Please unlock 168 hours later.")
        self.assertEqual(hint.kind, "wait")
        self.assertIn("168", hint.advice)

    def test_account_not_added(self):
        self.assertIn("added", explain(20031).title.lower())

    def test_unknown_code_falls_back_to_xiaomis_text(self):
        hint = explain(99999, "Some new message")
        self.assertIn("Some new message", hint.advice)


if __name__ == "__main__":
    unittest.main()
