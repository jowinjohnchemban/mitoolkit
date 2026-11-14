"""Regression tests for the places where a secret could leak, and for the unlock gate.

Everything uses dummy values. Nothing here touches the network, a real session
file, a real device, or fastboot.
"""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from miunlock import api
from miunlock.auth import browser, passtoken, requester
from miunlock.auth.redact import mask_id, redact_response
from miunlock.hints import explain

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


class SessionFileTests(unittest.TestCase):
    def test_session_is_saved_and_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "session.json"
            protected = passtoken._write_session(path, {"passToken": SECRET})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["passToken"], SECRET)
            if os.name != "nt":
                self.assertTrue(protected)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)


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
        guard = mock.patch.object(api, "get_fastboot", side_effect=AssertionError("fastboot was reached"))
        guard.start()
        self.addCleanup(guard.stop)
        send = mock.patch.object(api, "_send", side_effect=AssertionError("network was reached"))
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
