"""The USB / Wireless toggle switch: state, click, keyboard, focus ring, clean-up, and readable colours."""
import os
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from mitoolkit.ui.components import toggle  # noqa: E402
from mitoolkit.ui.components.shapes import contrast_ratio  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


class ColourTests(unittest.TestCase):
    def test_names_and_switch_are_readable(self):
        page = "#f0f0f0"                                           # the window background
        self.assertGreaterEqual(contrast_ratio(toggle.TEXT, page), 4.5)
        self.assertGreaterEqual(contrast_ratio(toggle.MUTED_TEXT, page), 4.5)
        self.assertGreaterEqual(contrast_ratio(toggle.OFF_BORDER, page), 3.0)     # the off switch against the page
        self.assertGreaterEqual(contrast_ratio(toggle.ON_TRACK, page), 3.0)       # the on track against the page
        self.assertGreaterEqual(contrast_ratio(toggle.ON_HOVER, page), 3.0)
        self.assertGreaterEqual(contrast_ratio(toggle.KNOB_ON, toggle.ON_TRACK), 3.0)     # the thumb on the track
        self.assertGreaterEqual(contrast_ratio(toggle.KNOB_ON, toggle.ON_HOVER), 3.0)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.var = tk.StringVar(value="usb")
        self.calls = []
        self.switch = toggle.ToggleSwitch(self.root, self.var, ("usb", "USB"), ("wifi", "Wireless"),
                                          command=lambda: self.calls.append(self.var.get()))
        self.switch.pack()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def click(self):
        event = SimpleNamespace(x=10, y=10)
        self.switch._on_press(event)
        self.switch._on_release(event)

    def texts(self):
        return [self.switch.itemcget(i, "text") for i in self.switch.find_all() if self.switch.type(i) == "text"]

    def test_starts_on_the_first_choice_and_a_click_flips_it_and_back(self):
        self.assertEqual((self.var.get(), self.switch._pos), ("usb", 0.0))
        self.click()
        self.assertEqual(self.var.get(), "wifi")
        self.click()
        self.assertEqual(self.var.get(), "usb")
        self.assertEqual(self.calls, ["wifi", "usb"])

    def test_the_knob_follows_the_variable_even_when_set_from_outside(self):
        def settle(target):
            import time
            for _ in range(100):                               # the knob slides over about a tenth of a second
                self.root.update()
                if self.switch._pos == target:
                    return
                time.sleep(0.01)
        self.var.set("wifi")
        settle(1.0)
        self.assertEqual(self.switch._pos, 1.0)
        self.var.set("usb")
        settle(0.0)
        self.assertEqual(self.switch._pos, 0.0)
        self.assertEqual(self.calls, [])                     # no command for a change the program made itself

    def test_both_names_are_shown(self):
        self.assertEqual(self.texts(), ["USB", "Wireless"])

    def test_space_and_enter_toggle_and_a_ring_shows_for_the_keyboard_only(self):
        self.switch.focus_force()
        self.root.update()
        self.switch._focused(True)
        self.switch._key(None)
        self.assertEqual(self.var.get(), "wifi")
        self.assertTrue(self.switch._focus and not self.switch._mouse)
        self.switch.draw()
        self.assertTrue(self.switch.find_withtag("ring"))        # the keyboard gets a focus ring
        self.switch._on_press(SimpleNamespace(x=10, y=10))     # a mouse press hides the ring even though focus stays
        self.switch.draw()
        self.assertFalse(self.switch.find_withtag("ring"))

    def test_a_release_outside_does_not_toggle(self):
        self.switch._on_press(SimpleNamespace(x=10, y=10))
        self.switch._on_release(SimpleNamespace(x=-40, y=-40))
        self.assertEqual(self.var.get(), "usb")

    def test_destroying_it_takes_its_callback_off_the_variable(self):
        self.switch.destroy()
        self.root.update()
        self.assertEqual(self.var.trace_info(), [])


if __name__ == "__main__":
    unittest.main()
