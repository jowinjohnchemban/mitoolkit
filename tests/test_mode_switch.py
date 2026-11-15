"""The USB / Wireless selector (a segmented pill): state, direct clicks, keyboard, focus ring, clean-up, colours, DPI."""
import os
import sys
import time
import tkinter as tk
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from mitoolkit.ui.components import mode_switch as ms  # noqa: E402
from mitoolkit.ui.components import render  # noqa: E402
from mitoolkit.ui.components.shapes import contrast_ratio  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


class ColourTests(unittest.TestCase):
    def test_everything_is_readable(self):
        page = "#f0f0f0"
        self.assertGreaterEqual(contrast_ratio(ms.TEXT, ms.THUMB), 4.5)               # the chosen name on the thumb
        self.assertGreaterEqual(contrast_ratio(ms.MUTED_TEXT, ms.TRACK), 4.5)         # the other name on the track
        self.assertGreaterEqual(contrast_ratio(ms.BORDER, page), 3.0)                 # the pill against the page
        self.assertGreaterEqual(contrast_ratio(ms.ACTIVE, ms.THUMB), 3.0)             # the blue glyph on the thumb
        self.assertGreaterEqual(contrast_ratio(ms.INACTIVE, ms.TRACK), 3.0)           # the grey glyph on the track
        self.assertGreaterEqual(contrast_ratio(ms.RING, page), 3.0)                   # the focus ring


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.var = tk.StringVar(value="usb")
        self.calls = []
        self.switch = ms.ModeSwitch(self.root, self.var, ("usb", "USB"), ("wifi", "Wireless"),
                                    command=lambda: self.calls.append(self.var.get()))
        self.switch.pack()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def click_segment(self, index):
        s = self.switch
        x = s._margin + s._pad + s._seg_w * index + s._seg_w // 2
        event = SimpleNamespace(x=x, y=s._margin + s._pill_h // 2)
        s._press()
        s._release(event)

    def settle(self, target):
        for _ in range(100):                                 # the thumb slides over about a fifth of a second
            self.root.update()
            if self.switch._pos == target:
                return
            time.sleep(0.01)

    def texts(self):
        return [self.switch.itemcget(i, "text") for i in self.switch.find_all() if self.switch.type(i) == "text"]

    def test_both_choices_are_always_visible_and_usb_is_the_default(self):
        self.assertEqual(self.texts(), ["USB", "Wireless"])
        self.assertEqual((self.var.get(), self.switch._pos), ("usb", 0.0))

    def test_each_segment_is_clicked_directly(self):
        self.click_segment(1)
        self.assertEqual(self.var.get(), "wifi")
        self.click_segment(1)                                # clicking the chosen one changes nothing
        self.assertEqual(self.var.get(), "wifi")
        self.click_segment(0)
        self.assertEqual(self.var.get(), "usb")
        self.assertEqual(self.calls, ["wifi", "usb"])        # the command ran once per real change

    def test_the_thumb_follows_the_variable_even_when_set_from_outside(self):
        self.var.set("wifi")
        self.settle(1.0)
        self.assertEqual(self.switch._pos, 1.0)
        self.var.set("usb")
        self.settle(0.0)
        self.assertEqual(self.switch._pos, 0.0)
        self.assertEqual(self.calls, [])                     # no command for a change the program made itself

    def test_arrow_keys_choose_and_space_flips(self):
        self.switch._step(1)
        self.assertEqual(self.var.get(), "wifi")
        self.switch._step(1)                                 # already at the end
        self.assertEqual(self.var.get(), "wifi")
        self.switch._step(-1)
        self.assertEqual(self.var.get(), "usb")
        self.switch._flip()
        self.assertEqual(self.var.get(), "wifi")

    def test_a_focus_ring_for_the_keyboard_only(self):
        self.switch._focused(True)
        self.switch._step(1)
        self.switch.draw()
        self.assertTrue(self.switch.find_withtag("ring"))
        self.switch._press()                                 # a mouse press hides it even though focus stays
        self.switch.draw()
        self.assertFalse(self.switch.find_withtag("ring"))

    def test_a_release_outside_does_not_choose(self):
        self.switch._press()
        self.switch._release(SimpleNamespace(x=-50, y=-50))
        self.assertEqual(self.var.get(), "usb")

    def test_hover_hints_only_at_the_segment_that_is_not_chosen(self):
        s = self.switch
        s._motion(SimpleNamespace(x=s._margin + s._pad + s._seg_w + 5, y=10))      # over Wireless, USB is chosen
        self.assertEqual(s._hover, 1)
        s._motion(SimpleNamespace(x=s._margin + s._pad + 5, y=10))                 # over the chosen one
        self.assertEqual(s._hover, -1)

    def test_destroying_it_takes_its_callback_off_the_variable(self):
        self.switch.destroy()
        self.root.update()
        self.assertEqual(self.var.trace_info(), [])

    def test_it_is_drawn_smoothly_and_scales_with_the_screen_dpi(self):
        base = self.switch._seg_w
        self.assertEqual(self.switch._pill_h, round(ms.HEIGHT * self.switch._k))
        self.root.tk.call("tk", "scaling", 2.0)              # 144 dpi: a 150 % screen
        big = ms.ModeSwitch(self.root, tk.StringVar(value="usb"), ("usb", "USB"), ("wifi", "Wireless"))
        big.pack()
        self.root.update()
        self.assertAlmostEqual(big._k, 1.5, places=1)
        self.assertGreater(big._seg_w, base)
        if render.HAVE:                                      # a picture with soft edges, not canvas shapes
            self.assertTrue(any(big.type(i) == "image" for i in big.find_all()))
            image = render.segmented_image(big._pill_w, big._pill_h, big._seg_w, big._pad, 1.0, -1, ms.TRACK, ms.BORDER,
                                           ms.THUMB, [("usb", 20, ms.INACTIVE), ("wifi", 90, ms.ACTIVE)], "", big._margin,
                                           big._k)
            self.assertEqual(image.size, (big._pill_w + 2 * big._margin, big._pill_h + 2 * big._margin))
            shades = {image.getpixel((x, image.height // 2)) for x in range(image.width)}
            self.assertGreater(len(shades), 6)


if __name__ == "__main__":
    unittest.main()
