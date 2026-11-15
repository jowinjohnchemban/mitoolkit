"""Windows open fully inside the area the system leaves free (no taskbar/Dock/panel overlap)."""
import os
import sys
import time
import tkinter as tk
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from miunlock.ui import placement  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


def settle(root, seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root()

    def tearDown(self):
        self.root.destroy()

    def test_fallback_margins_when_system_will_not_say(self):
        with mock.patch.object(placement, "_windows_work_area", side_effect=OSError), \
                mock.patch.object(placement, "_x11_work_area", side_effect=OSError):
            x, y, w, h = placement.work_area(self.root)
        self.assertGreater(y, 0)                                   # room for a top bar
        self.assertLess(y + h, self.root.winfo_screenheight())     # room for a bottom bar

    def _check_inside(self, win, area):
        ax, ay, aw, ah = area
        top = win.winfo_rooty() - win.winfo_y()
        self.assertGreaterEqual(win.winfo_x(), ax)
        self.assertGreaterEqual(win.winfo_y(), ay)
        self.assertLessEqual(win.winfo_x() + win.winfo_width(), ax + aw)
        self.assertLessEqual(win.winfo_y() + top + win.winfo_height(), ay + ah)

    def test_oversized_window_is_made_to_fit(self):
        self.root.deiconify()
        placement.fit_to_screen(self.root, 5000, 5000)
        settle(self.root)
        self._check_inside(self.root, placement.work_area(self.root))

    def test_window_with_a_menu_bar_fits(self):
        self.root.config(menu=tk.Menu(self.root))
        placement.fit_to_screen(self.root, 900, 5000)
        settle(self.root)
        self._check_inside(self.root, placement.work_area(self.root))

    def test_window_pushed_off_screen_is_pulled_back(self):
        area = placement.work_area(self.root)
        self.root.geometry(f"400x300+{area[0] + area[2] - 100}+{area[1] + area[3] - 50}")
        settle(self.root, 0.3)
        placement.keep_in_work_area(self.root)
        settle(self.root, 0.3)
        self._check_inside(self.root, area)


if __name__ == "__main__":
    unittest.main()
