"""Skeleton placeholders: they animate with ONE shared timer and stop when nothing is loading."""
import os
import sys
import time
import tkinter as tk
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


def run(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class SkeletonTests(unittest.TestCase):
    def setUp(self):
        from miunlock.ui.components import skeleton
        self.skeleton = skeleton
        self.root = make_root()
        self.root.geometry("500x400")

    def tearDown(self):
        self.skeleton.clock._watching.clear()
        self.skeleton.clock._job = None
        self.root.destroy()

    def pending_timers(self):
        return len(self.root.tk.splitlist(self.root.tk.call("after", "info")))

    def test_many_skeletons_share_one_timer_and_it_does_not_multiply(self):
        """A skeleton that redraws itself (like a chart) calls watch() from inside the tick. That once
        started a new timer every tick, doubling them until the window froze."""
        class Redrawing(self.skeleton.Skeleton):
            def draw(self):
                super().draw()
                self.skeleton_clock.watch(self)          # what charts and gauges do while loading

        Redrawing.skeleton_clock = self.skeleton.clock
        bars = [Redrawing(self.root, rows=3) for _ in range(8)]
        for bar in bars:
            bar.pack(fill="x")
        run(self.root, 0.6)
        self.assertLessEqual(self.pending_timers(), 3)    # the shared tick, not one per widget per tick
        self.assertEqual(len(self.skeleton.clock._watching), 8)

    def test_stops_by_itself_when_nothing_is_loading(self):
        bar = self.skeleton.Skeleton(self.root, rows=2)
        bar.pack(fill="x")
        run(self.root, 0.2)
        bar.stop()
        run(self.root, 0.3)
        self.assertEqual(len(self.skeleton.clock._watching), 0)
        self.assertIsNone(self.skeleton.clock._job)

    def test_a_frame_that_takes_long_slows_the_animation_down(self):
        clock = self.skeleton.clock

        class Slow(self.skeleton.Skeleton):
            def draw(self):
                time.sleep(0.05)

        bar = Slow(self.root, rows=1)
        bar.pack(fill="x")
        started = time.time()
        run(self.root, 0.6)
        ticks = clock._watching and 1                       # still animating, but not flat out
        self.assertTrue(ticks)
        self.assertLess(time.time() - started, 5)

    def test_colours_are_valid(self):
        for position in (0, 0.5, 1):
            colour = self.skeleton.bar_colour(position)
            self.assertRegex(colour, r"^#[0-9a-f]{6}$")


if __name__ == "__main__":
    unittest.main()
