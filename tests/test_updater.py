"""Version text, the updater (release lookup, checksum, swap), settings and the update window."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from miunlock import build, settings, updater  # noqa: E402

try:
    import tkinter as tk
    tk.Tk().destroy()
    HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False

NAME = "miunlock-linux-x64"
BASE = updater.DOWNLOADS + "v9.9.9/"


def release(version="v9.9.9"):
    return updater.Release(version, updater.parse_version(version), "Notes", "https://github.com/x/releases",
                           {NAME: BASE + NAME, updater.SUMS: BASE + updater.SUMS})


class FakeReply:
    def __init__(self, payload=None, body=b"", text=""):
        self._payload, self.body, self.text = payload, body, text
        self.headers = {"Content-Length": str(len(body))}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload

    def iter_content(self, _n):
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class VersionTests(unittest.TestCase):
    def test_full_version_format(self):
        with mock.patch.object(build, "info", return_value=("15112026", "8ae71a1")):
            self.assertEqual(build.full_version(), f"v{build.__version__} (build: 15112026-8ae71a1)")
        with mock.patch.object(build, "info", return_value=None):
            self.assertEqual(build.full_version(), f"v{build.__version__}")

    def test_git_checkout_gives_date_and_short_id(self):
        info = build._from_git(Path(build.__file__).resolve().parent)
        if info is not None:                                   # a checkout; an archive has no git
            self.assertRegex(info[0], r"^\d{8}$")
            self.assertRegex(info[1], r"^[0-9a-f]{7,}$")


class ReleaseTests(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(updater.parse_version("v1.8.1"), (1, 8, 1))
        self.assertIsNone(updater.parse_version("1.8"))
        self.assertIsNone(updater.parse_version("v1.8.1-beta"))
        self.assertTrue(updater.is_newer(release("v1.10.0"), "1.9.9"))      # numbers, not text
        self.assertFalse(updater.is_newer(release("v1.0.0"), "1.0.0"))

    def test_latest_keeps_only_downloads_from_this_project(self):
        data = {"tag_name": "v9.9.9", "body": "What is new", "html_url": "https://github.com/p",
                "assets": [{"name": NAME, "browser_download_url": BASE + NAME},
                           {"name": "evil", "browser_download_url": "https://example.com/evil"}]}
        with mock.patch("requests.get", return_value=FakeReply(data)):
            found = updater.latest()
        self.assertEqual(list(found.assets), [NAME])
        self.assertEqual(found.version, (9, 9, 9))

    def test_a_network_failure_is_a_clear_error(self):
        import requests
        with mock.patch("requests.get", side_effect=requests.ConnectionError("down")):
            with self.assertRaisesRegex(updater.UpdateError, "Could not reach GitHub"):
                updater.latest()

    def test_checksum_lookup(self):
        h = "a" * 64
        self.assertEqual(updater.checksum_for(f"{h}  {NAME}\n{'b' * 64}  other", NAME), h)
        self.assertIsNone(updater.checksum_for(f"{h}  other", NAME))
        self.assertIsNone(updater.checksum_for("nothex  " + NAME, NAME))


class DownloadAndInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        patch = mock.patch.object(updater, "asset_name", return_value=NAME)
        patch.start()
        self.addCleanup(patch.stop)

    def get(self, body, listed):
        sums = f"{listed}  {NAME}\n"

        def fake(url, **kw):
            return FakeReply(body=body) if url.endswith(NAME) else FakeReply(text=sums)
        return mock.patch("requests.get", side_effect=fake)

    def test_good_download_is_kept(self):
        body = b"new program"
        with self.get(body, hashlib.sha256(body).hexdigest()):
            path = updater.download(release(), self.dir / "new")
        self.assertEqual(path.read_bytes(), body)

    def test_a_wrong_checksum_is_refused_and_removed(self):
        with self.get(b"tampered", "0" * 64):
            with self.assertRaisesRegex(updater.UpdateError, "checksum"):
                updater.download(release(), self.dir / "new")
        self.assertFalse((self.dir / "new").exists())

    def test_no_checksum_file_means_no_install(self):
        r = release()
        del r.assets[updater.SUMS]
        with self.assertRaisesRegex(updater.UpdateError, "SHA256SUMS"):
            updater.download(r, self.dir / "new")

    def test_install_swaps_and_keeps_the_old_copy_until_next_start(self):
        exe, new = self.dir / "miunlock", self.dir / "miunlock.new"
        exe.write_bytes(b"old")
        new.write_bytes(b"new")
        updater.install(new, exe)
        self.assertEqual(exe.read_bytes(), b"new")
        self.assertEqual(updater.old_copy(exe).read_bytes(), b"old")
        self.assertFalse(new.exists())

    def test_a_failed_swap_puts_the_old_program_back(self):
        exe, new = self.dir / "miunlock", self.dir / "miunlock.new"
        exe.write_bytes(b"old")
        new.write_bytes(b"new")
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) == 2:                     # moving the new program into place fails
                raise OSError("locked")
            return real(src, dst)
        with mock.patch("os.replace", side_effect=flaky):
            with self.assertRaises(updater.UpdateError):
                updater.install(new, exe)
        self.assertEqual(exe.read_bytes(), b"old")


class SettingsAndScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(settings, "PATH", Path(self.tmp.name) / "settings.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_settings_round_trip_and_damaged_file(self):
        self.assertEqual(settings.get("x", 5), 5)
        settings.set("x", 7)
        self.assertEqual(settings.get("x"), 7)
        settings.PATH.write_text("not json")
        self.assertEqual(settings.get("x", 1), 1)

    def test_check_is_due_once_a_day_and_can_be_turned_off(self):
        self.assertTrue(updater.check_due(now=1_000_000))
        updater.mark_checked(now=1_000_000)
        self.assertFalse(updater.check_due(now=1_000_000 + 3600))
        self.assertTrue(updater.check_due(now=1_000_000 + updater.CHECK_EVERY_S))
        settings.set("auto_update_check", False)
        self.assertFalse(updater.check_due(now=9_000_000))


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class UpdateWindowTests(unittest.TestCase):
    def setUp(self):
        from miunlock import gui
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app._polling = True
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def dialog(self, rel):
        from miunlock.ui.update_dialog import UpdateDialog
        return UpdateDialog(self.app, rel, start=True)

    def test_newer_release_offers_the_right_button(self):
        with mock.patch.object(updater, "can_self_update", return_value=False):
            d = self.dialog(release("v99.0.0"))
            self.assertIn("v99.0.0", d.line.cget("text"))
            self.assertEqual(d.action.cget("text"), "Open the release page")
            d.close()
        with mock.patch.object(updater, "can_self_update", return_value=True):
            d = self.dialog(release("v99.0.0"))
            self.assertEqual(d.action.cget("text"), "Install and restart")
            d.close()

    def test_same_version_says_up_to_date(self):
        d = self.dialog(release(f"v{build.__version__}"))
        self.assertIn("up to date", d.line.cget("text"))
        d.close()


if __name__ == "__main__":
    unittest.main()
