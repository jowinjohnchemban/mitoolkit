"""Closing MiToolkit: phones are let go of, a fastboot it started is stopped, the adb server it started is stopped."""
import os
import subprocess
import sys
import threading
import time
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mitoolkit import adb_server, adb_usb, fastboot, settings, shutdown  # noqa: E402


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        shutdown._done.clear()
        self.addCleanup(shutdown._done.clear)

    def test_runs_every_step_once_and_reports_what_it_did(self):
        steps = [lambda: "one", lambda: "", lambda: "three"]
        with mock.patch.object(shutdown, "STEPS", steps):
            self.assertEqual(shutdown.run(), ["one", "three"])
            self.assertEqual(shutdown.run(), [])                  # atexit and the window both ask: it runs once

    def test_a_failing_step_does_not_stop_the_others_or_raise(self):
        def broken():
            raise RuntimeError("boom")
        with mock.patch.object(shutdown, "STEPS", [broken, lambda: "still done"]):
            self.assertEqual(shutdown.run(), ["still done"])

    def test_the_real_steps_call_the_right_things(self):
        with mock.patch.object(adb_usb, "close_all", return_value=2) as usb, \
                mock.patch.object(fastboot, "terminate_children", return_value=1) as fb, \
                mock.patch.object(adb_server, "stop_started", return_value="Stopped Google's adb server.") as adb, \
                mock.patch.object(settings, "get", side_effect=lambda key, default=None: default):
            messages = shutdown.run()
        usb.assert_called_once()
        fb.assert_called_once()
        adb.assert_called_once_with(also_others=False)
        self.assertEqual(len(messages), 3)

    def test_settings_can_turn_the_adb_stop_off_or_widen_it(self):
        with mock.patch.object(adb_server, "stop_started", return_value="x") as adb, \
                mock.patch.object(settings, "get", side_effect=lambda key, default=None: {"stop_adb_on_exit": False}.get(key, default)):
            self.assertEqual(shutdown._stop_adb(), "")
        adb.assert_not_called()
        with mock.patch.object(adb_server, "stop_started", return_value="x") as adb, \
                mock.patch.object(settings, "get", side_effect=lambda key, default=None: {"stop_any_adb_on_exit": True}.get(key, default)):
            shutdown._stop_adb()
        adb.assert_called_once_with(also_others=True)


class FilesTests(unittest.TestCase):
    def setUp(self):
        shutdown._done.clear()
        self.addCleanup(shutdown._done.clear)

    def test_the_crash_log_is_closed_with_faulthandler_switched_off_first(self):
        import io
        import mitoolkit.watchdog as watchdog
        crash = io.StringIO()
        order = []
        crash.close = lambda: order.append("close")
        with mock.patch.object(watchdog, "_crash_files", [crash]), \
                mock.patch.object(watchdog.faulthandler, "disable", side_effect=lambda: order.append("disable")):
            self.assertTrue(watchdog.close_crash_log())
            self.assertFalse(watchdog.close_crash_log())              # nothing left to close
        self.assertEqual(order, ["disable", "close"])

    def test_the_log_file_is_flushed_and_closed_last(self):
        import logging
        import tempfile
        from logging.handlers import RotatingFileHandler
        with tempfile.TemporaryDirectory() as tmp:
            handler = RotatingFileHandler(os.path.join(tmp, "x.log"), encoding="utf-8")
            logger = logging.getLogger("closing-test")
            logger.addHandler(handler)
            logger.warning("written before closing")
            order = []
            real_shutdown = logging.shutdown
            with mock.patch.object(shutdown, "STEPS", [lambda: order.append("steps") or "did"]), \
                    mock.patch("logging.shutdown", side_effect=lambda: order.append("files") or real_shutdown()):
                self.assertEqual(shutdown.run(), ["did"])
            self.assertEqual(order, ["steps", "files"])               # files after everything that logs
            self.assertIsNone(handler.stream)                         # the file handle is released
            self.assertIn("written before closing", open(os.path.join(tmp, "x.log"), encoding="utf-8").read())
            logger.removeHandler(handler)

    def test_a_failing_file_close_never_raises(self):
        with mock.patch.object(shutdown, "STEPS", []), mock.patch.object(shutdown, "_close_files", side_effect=OSError("disk")):
            self.assertEqual(shutdown.run(), [])


class AdbServerStopTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(adb_server._started)
        self.addCleanup(adb_server._started.update, self.saved)

    def test_only_a_server_we_started_is_stopped(self):
        adb_server._started["by_us"] = False
        with mock.patch.object(adb_server, "running", return_value=True), mock.patch("subprocess.run") as run:
            self.assertEqual(adb_server.stop_started(), "")          # someone else's (Android Studio, a terminal)
        run.assert_not_called()

    def test_our_own_server_is_stopped_with_kill_server(self):
        adb_server._started["by_us"] = True
        with mock.patch.object(adb_server, "running", return_value=True), \
                mock.patch("mitoolkit.platform_tools.find", return_value="/sdk/adb"), mock.patch("subprocess.run") as run:
            self.assertIn("Stopped", adb_server.stop_started())
        self.assertEqual(run.call_args[0][0], ["/sdk/adb", "kill-server"])
        self.assertFalse(adb_server._started["by_us"])

    def test_also_others_when_asked(self):
        adb_server._started["by_us"] = False
        with mock.patch.object(adb_server, "running", return_value=True), \
                mock.patch("mitoolkit.platform_tools.find", return_value="/sdk/adb"), mock.patch("subprocess.run") as run:
            self.assertIn("Stopped", adb_server.stop_started(also_others=True))
        run.assert_called_once()

    def test_start_remembers_that_we_started_it(self):
        adb_server._started["by_us"] = False
        states = iter([False, True])                                # not running, then running after start-server
        with mock.patch.object(adb_server, "running", side_effect=lambda *a, **k: next(states)), \
                mock.patch("mitoolkit.platform_tools.find", return_value="/sdk/adb"), mock.patch("subprocess.run"):
            self.assertTrue(adb_server.start())
        self.assertTrue(adb_server._started["by_us"])
        adb_server._started["by_us"] = False
        with mock.patch.object(adb_server, "running", return_value=True):
            adb_server.start()                                       # already running: not ours
        self.assertFalse(adb_server._started["by_us"])


class ChildProcessTests(unittest.TestCase):
    def test_a_running_fastboot_is_stopped_when_the_program_closes(self):
        result = {}

        def slow():
            try:
                fastboot._run_tracked([sys.executable, "-c", "import time; time.sleep(60)"], 90)
            except Exception as err:       # killed: communicate returns, the return code is not zero
                result["error"] = err
            result["done"] = True
        thread = threading.Thread(target=slow, daemon=True)
        thread.start()
        for _ in range(100):               # wait for the child to be registered
            if fastboot._children:
                break
            time.sleep(0.05)
        started = time.monotonic()
        self.assertEqual(fastboot.terminate_children(), 1)
        thread.join(20)
        self.assertTrue(result.get("done"))
        self.assertLess(time.monotonic() - started, 15)             # it did not wait out the 60 seconds
        self.assertFalse(fastboot._children)

    def test_a_finished_program_is_forgotten_and_its_output_returned(self):
        done = fastboot._run_tracked([sys.executable, "-c", "print('hi')"], 30)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "hi"))
        self.assertFalse(fastboot._children)

    def test_close_all_lets_go_of_phones_even_if_one_fails_to_close(self):
        good, bad = mock.Mock(), mock.Mock()
        bad.close.side_effect = OSError("gone")
        with mock.patch.dict(adb_usb._devices, {"a": good, "b": bad}, clear=True):
            self.assertEqual(adb_usb.close_all(), 1)
            self.assertEqual(adb_usb._devices, {})
        good.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
