"""The watchdog: stuck phone calls are given up on, a frozen window is recorded, crashes are logged."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from miunlock import watchdog  # noqa: E402


class CallWithTimeoutTests(unittest.TestCase):
    def test_returns_the_result(self):
        self.assertEqual(watchdog.call_with_timeout(lambda: 42, 2), 42)

    def test_passes_errors_through(self):
        def boom():
            raise ValueError("bad reading")

        with self.assertRaises(ValueError):
            watchdog.call_with_timeout(boom, 2)

    def test_gives_up_on_a_call_that_never_returns(self):
        release = threading.Event()
        try:
            with self.assertRaises(watchdog.Stalled) as ctx:
                watchdog.call_with_timeout(release.wait, 0.2, "the phone")
            self.assertIn("did not answer", str(ctx.exception))
            self.assertIsInstance(ctx.exception, TimeoutError)
        finally:
            release.set()                       # let the abandoned helper thread end


class FakeRoot:
    def after(self, ms, fn):
        return "job"


class UiWatchdogTests(unittest.TestCase):
    def make(self):
        self.now = 0.0
        self.noted = []
        guard = watchdog.UiWatchdog(FakeRoot(), warn_after=4, clock=lambda: self.now, on_stall=self.noted.append)
        guard._beat = 0.0
        return guard

    def test_a_busy_window_is_noticed_once_and_recovery_is_seen(self):
        guard = self.make()
        self.now = 2
        guard.check()
        self.assertEqual(guard.stalls, 0)                # a short pause is normal
        self.now = 5
        guard.check()
        guard.check()                                    # still frozen: not reported again
        self.assertEqual((guard.stalls, len(self.noted)), (1, 1))
        self.assertGreaterEqual(self.noted[0], 4)
        guard._beat = 5                                  # the window answered
        guard.check()
        self.assertIsNone(guard._stalled_since)
        self.now = 12
        guard.check()                                    # a second freeze is reported separately
        self.assertEqual(guard.stalls, 2)

    def test_stacks_name_the_threads(self):
        text = watchdog.thread_stacks()
        self.assertIn("MainThread", text)


if __name__ == "__main__":
    unittest.main()
