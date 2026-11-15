"""File backup: resumable (unchanged files are skipped), verified, retried, and honest about failures."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from miunlock import adb  # noqa: E402
from miunlock.adb import AdbError  # noqa: E402

FILES = {"/sdcard/DCIM/a.jpg": (b"aaaa", 1_700_000_000), "/sdcard/DCIM/b.jpg": (b"bbbbbb", 1_700_000_100)}


class FakeSync:
    def __init__(self, files=FILES, flaky=None, short=None, dead=False):
        self.files, self.flaky, self.short, self.dead = files, dict(flaky or {}), short, dead
        self.received = []

    def stat(self, path):
        return (0o40000, 0, 0) if path.startswith("/sdcard/DCIM") else (0, 0, 0)   # only DCIM exists

    def walk(self, root):
        for path, (data, mtime) in self.files.items():
            if path.startswith(root.rstrip("/") + "/"):
                yield path, 0o100644, len(data), mtime

    def recv(self, path, local, cancel=None):
        self.received.append(path)
        if self.dead:
            raise AdbError("closed")
        if self.flaky.get(path, 0) > 0:
            self.flaky[path] -= 1
            raise AdbError("transfer dropped")
        data = self.files[path][0]
        if self.short == path:
            data = data[:-1]
        Path(local).write_bytes(data)
        return len(data)

    def close(self):
        pass


def run(sync, dest):
    phone = adb.Phone.__new__(adb.Phone)
    phone.serial = "X"
    phone.sync = lambda: sync
    phone.user_apps = lambda: ["com.example"]
    with mock.patch("time.sleep"):
        return adb._Backup(phone, Path(dest), ["photos"], lambda _t: None, None).run()


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_first_run_copies_and_second_run_skips_what_is_there(self):
        first = run(FakeSync(), self.tmp.name)
        self.assertEqual((first["files"], first["unchanged"], first["failed_files"]), (2, 0, 0))
        again = FakeSync()
        second = run(again, self.tmp.name)
        self.assertEqual((second["files"], second["unchanged"]), (0, 2))
        self.assertEqual(again.received, [])                       # nothing was transferred again

    def test_a_dropped_transfer_is_retried(self):
        result = run(FakeSync(flaky={"/sdcard/DCIM/a.jpg": 2}), self.tmp.name)
        self.assertEqual((result["files"], result["failed_files"]), (2, 0))

    def test_a_short_file_is_rejected_and_listed(self):
        result = run(FakeSync(short="/sdcard/DCIM/b.jpg"), self.tmp.name)
        self.assertEqual((result["files"], result["failed_files"]), (1, 1))
        report = (Path(self.tmp.name) / "backup-problems.txt").read_text()
        self.assertIn("b.jpg", report)
        self.assertFalse(list(Path(self.tmp.name).rglob("b.jpg")))   # no half file left behind
        run(FakeSync(), self.tmp.name)                               # a later good run clears the report
        self.assertFalse((Path(self.tmp.name) / "backup-problems.txt").exists())

    def test_a_dead_connection_stops_the_backup(self):
        many = {f"/sdcard/DCIM/{i}.jpg": (b"x", 1_700_000_000 + i) for i in range(20)}
        sync = FakeSync(files=many, dead=True)
        with self.assertRaisesRegex(AdbError, "stopped"):
            run(sync, self.tmp.name)
        self.assertLess(len(sync.received), 20 * 3)                  # it did not try every file three times


if __name__ == "__main__":
    unittest.main()
