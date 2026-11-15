"""Resource hygiene: background pool, bounded image cache, housekeeping, and nothing left behind."""
import os
import sys
import threading
import time
import tkinter as tk
import unittest
import weakref

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from miunlock import memory, workers  # noqa: E402
from tkhelper import make_root  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


def freed(ref, tries: int = 20) -> bool:
    """Collect until the object behind a weak reference is gone. gc.collect() returns at once if a
    collection is already running on another thread, so one call is not always enough."""
    for _ in range(tries):
        memory.collect()
        if ref() is None:
            return True
        time.sleep(0.01)
    return False


class BackgroundPoolTests(unittest.TestCase):
    def test_runs_jobs_off_the_calling_thread_and_delivers_on_drain(self):
        pool = workers.BackgroundPool(workers=2, name="test")
        got = []
        caller = threading.get_ident()
        where = []
        pool.submit(lambda: where.append(threading.get_ident()) or 41 + 1, lambda r, e: got.append((r, e)))
        for _ in range(100):
            if pool.drain():
                break
            time.sleep(0.01)
        self.assertEqual(got, [(42, None)])
        self.assertNotEqual(where[0], caller)                  # the work was not done on this thread

    def test_errors_come_back_through_the_callback(self):
        pool = workers.BackgroundPool(workers=1, name="test")
        got = []

        def boom():
            raise ValueError("bad")

        pool.submit(boom, lambda r, e: got.append(e))
        for _ in range(100):
            if pool.drain():
                break
            time.sleep(0.01)
        self.assertIsInstance(got[0], ValueError)

    def test_sheds_load_instead_of_growing_without_limit(self):
        pool = workers.BackgroundPool(workers=1, name="test", max_waiting=2)
        gate = threading.Event()
        try:
            accepted = [pool.submit(gate.wait, lambda r, e: None) for _ in range(6)]
            self.assertIn(False, accepted)                     # once full, new jobs are refused
        finally:
            gate.set()

    def test_workers_are_daemon_threads(self):
        pool = workers.BackgroundPool(workers=2, name="daemontest")
        self.assertTrue(all(t.daemon for t in pool._threads))   # a stuck job can't keep the program from closing


class ImageCacheTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_DISPLAY, "needs a display")
    def test_cache_is_bounded_and_keeps_recent_images(self):
        from miunlock.ui.components import render
        if not render.HAVE:
            self.skipTest("Pillow is not installed")
        root = make_root()
        try:
            render.release_images()
            first = render.ring_photo(40, 10, "#2f9e6b", "#e8ebf2")
            for pct in range(11, 11 + render.MAX_PHOTOS + 20):   # more than the cache holds
                render.ring_photo(40, pct, "#2f9e6b", "#e8ebf2")
            self.assertLessEqual(len(render._photos), render.MAX_PHOTOS)
            self.assertIsNotNone(first)
            again = render.ring_photo(40, 11 + render.MAX_PHOTOS + 19, "#2f9e6b", "#e8ebf2")   # recent: still cached
            self.assertIn((id(tk._default_root), "ring", 40, 11 + render.MAX_PHOTOS + 19, "#2f9e6b", "#e8ebf2", 11),
                          render._photos)
            self.assertIsNotNone(again)
            render.release_images()
            self.assertEqual(len(render._photos), 0)
        finally:
            root.destroy()


class HousekeepingTests(unittest.TestCase):
    def test_rss_is_a_plausible_number(self):
        used = memory.rss_mb()
        self.assertIsNotNone(used)
        self.assertGreater(used, 5)

    def test_collect_frees_reference_cycles(self):
        class Node:
            pass

        a, b = Node(), Node()
        a.other, b.other = b, a                                # a cycle only the collector can free
        ref = weakref.ref(a)
        del a, b
        self.assertTrue(freed(ref))

    def test_high_memory_releases_caches_once(self):
        released = []

        class FakeRoot:
            def after(self, ms, fn):
                return "job"

            def after_cancel(self, job):
                pass

        keeper = memory.Housekeeper(FakeRoot(), release=[lambda: released.append(1)], limit_mb=1)  # always "high"
        keeper.check_memory()
        keeper.check_memory()
        self.assertEqual(len(released), 2)                      # released each time it is high
        self.assertTrue(keeper._over)                           # but reported in the log only once per episode
        keeper.limit_mb = 10 ** 6
        keeper.check_memory()
        self.assertFalse(keeper._over)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class ClosingFreesThingsTests(unittest.TestCase):
    def test_a_closed_live_window_is_garbage_collected(self):
        from miunlock import gui
        from miunlock.ui.live_dialog import LiveStatusDialog
        root = make_root()
        try:
            app = gui.App(root)
            app.busy = True
            dlg = LiveStatusDialog(app, "X", "Phone", start=False)
            charts = [weakref.ref(c) for c in dlg.charts]
            for chart in dlg.charts:
                chart.push(10.0, redraw=False) if len(chart.series) == 1 else chart.push(10.0, 20.0, redraw=False)
            root.update()
            dlg.close()
            del dlg, chart                               # (the loop variable would keep the last chart alive)
            for _ in range(200):                         # let drawing jobs that were in flight finish and deliver
                root.update()
                if not workers.render_pool.waiting:
                    break
                time.sleep(0.01)
            root.update()
            self.assertTrue(all(freed(ref, tries=150) for ref in charts))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
