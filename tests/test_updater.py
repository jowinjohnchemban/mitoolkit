"""Version text, the updater (release lookup, checksum, swap), settings and the update window."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from mitoolkit import build, settings, updater  # noqa: E402

try:
    import tkinter as tk
    tk.Tk().destroy()
    HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False

NAME = "mitoolkit-linux-x64"
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

    def versioned(self, tag="v9.9.9"):
        name = f"{NAME}-{tag}"
        return updater.Release(tag, updater.parse_version(tag), "Notes", "https://github.com/x/releases",
                               {name: BASE + name, updater.SUMS: BASE + updater.SUMS}), name

    def test_a_release_with_the_version_in_the_file_name_is_found_and_checked_by_that_name(self):
        rel, name = self.versioned()
        self.assertEqual(updater.release_asset(rel), name)
        body = b"new program"
        sums = f"{hashlib.sha256(body).hexdigest()}  {name}\n"

        def fake(url, **kw):
            return FakeReply(body=body) if url.endswith(name) else FakeReply(text=sums)
        with mock.patch("requests.get", side_effect=fake):
            path = updater.download(rel, self.dir / "new")
        self.assertEqual(path.read_bytes(), body)

    def test_older_releases_without_the_version_in_the_name_still_work(self):
        self.assertEqual(updater.release_asset(release()), NAME)
        both = updater.Release("v9.9.9", (9, 9, 9), "", "", {NAME: "x", f"{NAME}-v9.9.9": "y"})
        self.assertEqual(updater.release_asset(both), f"{NAME}-v9.9.9")                # the versioned one is preferred

    def test_another_versions_file_is_never_taken_and_no_file_is_a_clear_error(self):
        other = updater.Release("v9.9.9", (9, 9, 9), "", "", {f"{NAME}-v1.0.0": "x", updater.SUMS: "s"})
        self.assertIsNone(updater.release_asset(other))
        with self.assertRaisesRegex(updater.UpdateError, "no program for this system"):
            updater.download(other, self.dir / "new")

    def test_a_release_can_be_downloaded_to_a_folder_without_installing_it(self):
        body = b"new program"
        with self.get(body, hashlib.sha256(body).hexdigest()):
            path = updater.download_to(release("v9.9.9"), self.dir)
        self.assertEqual(path, self.dir / "mitoolkit-linux-x64-v9.9.9")           # the version is in the name
        self.assertEqual(path.read_bytes(), body)
        self.assertEqual([p.name for p in self.dir.iterdir()], [path.name])         # no .part left behind
        if sys.platform != "win32":
            self.assertTrue(os.access(path, os.X_OK))                                # a program, not a plain file

    def test_a_download_of_another_version_is_kept_and_the_same_one_is_replaced(self):
        for version, body in (("v9.9.8", b"old"), ("v9.9.9", b"new"), ("v9.9.9", b"new again")):
            with self.get(body, hashlib.sha256(body).hexdigest()):
                updater.download_to(release(version), self.dir)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["mitoolkit-linux-x64-v9.9.8", "mitoolkit-linux-x64-v9.9.9"])
        self.assertEqual((self.dir / "mitoolkit-linux-x64-v9.9.9").read_bytes(), b"new again")

    def test_a_download_with_a_wrong_checksum_leaves_nothing_in_the_folder(self):
        with self.get(b"tampered", "0" * 64):
            with self.assertRaisesRegex(updater.UpdateError, "checksum"):
                updater.download_to(release(), self.dir)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_folder_that_cannot_be_written_is_a_plain_error(self):
        with self.get(b"x", hashlib.sha256(b"x").hexdigest()):
            with self.assertRaisesRegex(updater.UpdateError, "Could not save it"):
                updater.download_to(release(), self.dir / "missing" / "folder")

    def test_the_downloads_folder_falls_back_to_home(self):
        with mock.patch.object(Path, "home", return_value=self.dir):
            self.assertEqual(updater.downloads_folder(), self.dir)                    # no Downloads folder here
            (self.dir / "Downloads").mkdir()
            self.assertEqual(updater.downloads_folder(), self.dir / "Downloads")

    def test_install_swaps_and_keeps_the_old_copy_until_next_start(self):
        exe, new = self.dir / "mitoolkit", self.dir / "mitoolkit.new"
        exe.write_bytes(b"old")
        new.write_bytes(b"new")
        updater.install(new, exe)
        self.assertEqual(exe.read_bytes(), b"new")
        self.assertEqual(updater.old_copy(exe).read_bytes(), b"old")
        self.assertFalse(new.exists())

    def test_a_failed_swap_puts_the_old_program_back(self):
        exe, new = self.dir / "mitoolkit", self.dir / "mitoolkit.new"
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
        from mitoolkit import gui
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app._polling = True
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def dialog(self, rel):
        from mitoolkit.ui.update_dialog import UpdateDialog
        return UpdateDialog(self.app, rel, start=True)

    def packed(self, d):
        return [str(w.cget("text")) for w in (d.action, d.download_btn, d.page_btn) if w.winfo_manager()]

    def test_newer_release_offers_the_right_buttons(self):
        with mock.patch.object(updater, "can_self_update", return_value=False):
            d = self.dialog(release("v99.0.0"))
            self.assertIn("v99.0.0", d.line.cget("text"))
            self.assertEqual(d.action.cget("text"), "Download")                  # a pip or source install: get the file
            self.assertEqual(self.packed(d), ["Download", "Release Page"])
            d.close()
        with mock.patch.object(updater, "can_self_update", return_value=True):
            d = self.dialog(release("v99.0.0"))
            self.assertEqual(d.action.cget("text"), "Install and Restart")
            self.assertEqual(self.packed(d), ["Install and Restart", "Download Only", "Release Page"])
            d.close()

    def test_the_buttons_all_fit_in_the_window(self):
        with mock.patch.object(updater, "can_self_update", return_value=True):
            d = self.dialog(release("v99.0.0"))
            self.root.update()
            right = max(b.winfo_rootx() + b.winfo_width() for b in (d.action, d.download_btn, d.page_btn))
            self.assertLessEqual(right, d.win.winfo_rootx() + d.win.winfo_width())
            d.close()

    def test_download_only_saves_the_checked_file_and_installs_nothing(self):
        body = b"program"
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))

        def fake(url, **kw):
            return FakeReply(body=body) if url.endswith(NAME) else FakeReply(text=f"{hashlib.sha256(body).hexdigest()}  {NAME}\n")
        with mock.patch.object(updater, "can_self_update", return_value=True), \
                mock.patch.object(updater, "asset_name", return_value=NAME), \
                mock.patch.object(updater, "downloads_folder", return_value=folder), \
                mock.patch.object(updater, "install") as install, mock.patch("requests.get", side_effect=fake):
            d = self.dialog(release("v99.0.0"))
            d._download()
            for _ in range(100):
                self.root.update()
                if d.saved is not None:
                    break
                self.root.after(20)
        install.assert_not_called()
        self.assertEqual(d.saved, folder / "mitoolkit-linux-x64-v99.0.0")
        self.assertIn("not installed", d.line.cget("text"))
        self.assertTrue(d.reveal_btn.winfo_manager())                              # Show in folder appears
        self.assertEqual(str(d.action.cget("state")), "normal")                    # and the buttons are back
        d.close()

    def test_a_failed_download_says_why_and_brings_the_buttons_back(self):
        with mock.patch.object(updater, "can_self_update", return_value=True), \
                mock.patch.object(updater, "download_to", side_effect=updater.UpdateError("The download stopped.")):
            d = self.dialog(release("v99.0.0"))
            d._download()
            for _ in range(100):
                self.root.update()
                if not d._busy:
                    break
                self.root.after(20)
        self.assertIn("The download stopped.", d.line.cget("text"))
        self.assertEqual(str(d.download_btn.cget("state")), "normal")
        d.close()

    def test_same_version_says_up_to_date(self):
        d = self.dialog(release(f"v{build.__version__}"))
        self.assertIn("up to date", d.line.cget("text"))
        d.close()


if __name__ == "__main__":
    unittest.main()
