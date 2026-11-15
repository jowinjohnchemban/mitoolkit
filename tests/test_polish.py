"""Small UI pieces: example text in entries, tooltips, quiet icon buttons, the selector's colour fade, and a dialog that
greys its actions while it works."""
import os
import sys
import tkinter as tk
import unittest
import unittest.mock as mock
from tkinter import ttk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from isolate import isolate_settings  # noqa: E402
from tkhelper import make_root  # noqa: E402

from mitoolkit.ui.components import buttons, mode_switch as ms  # noqa: E402
from mitoolkit.ui.components.placeholder import placeholder  # noqa: E402
from mitoolkit.ui.components.shapes import mix  # noqa: E402
from mitoolkit.ui.components.tooltip import Tooltip  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class PlaceholderTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self.root, textvariable=self.var)
        self.entry.pack()
        self.label = placeholder(self.entry, self.var, "192.168.1.xx")
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_the_example_shows_while_empty_and_never_becomes_the_value(self):
        self.assertTrue(self.label.winfo_ismapped())
        self.assertEqual(self.label.cget("text"), "192.168.1.xx")
        self.assertEqual(self.var.get(), "")

    def test_it_goes_when_something_is_typed_and_returns_when_cleared(self):
        self.var.set("1")
        self.root.update()
        self.assertFalse(self.label.winfo_ismapped())
        self.var.set("")
        self.root.update()
        self.assertTrue(self.label.winfo_ismapped())

    def test_clicking_the_example_focuses_the_entry(self):
        self.entry.focus_force()
        self.root.focus_force()
        self.label.event_generate("<Button-1>")
        self.root.update()
        self.assertEqual(self.root.focus_get(), self.entry)

    def test_the_example_is_readable(self):
        from mitoolkit.ui.components.placeholder import HINT
        from mitoolkit.ui.components.shapes import contrast_ratio
        self.assertGreaterEqual(contrast_ratio(HINT, "#ffffff"), 4.5)

    def test_destroying_the_entry_takes_its_callback_off_the_variable(self):
        self.entry.destroy()
        self.root.update()
        self.assertEqual(self.var.trace_info(), [])


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class TooltipTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.button = ttk.Button(self.root, text="x")
        self.button.pack(padx=40, pady=40)
        self.tip = Tooltip(self.button, lambda: "Copy details", delay=1)
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_it_names_the_control_after_a_moment_and_goes_when_the_pointer_leaves(self):
        self.button.event_generate("<Enter>")
        for _ in range(20):
            self.root.update()
            if self.tip._tip is not None:
                break
            self.root.after(5)
        self.assertIsNotNone(self.tip._tip)
        self.assertEqual(self.tip._tip.winfo_children()[0].cget("text"), "Copy details")
        self.button.event_generate("<Leave>")
        self.root.update()
        self.assertIsNone(self.tip._tip)

    def test_the_keyboard_gets_it_at_once_and_a_key_press_hides_it(self):
        self.tip.show()
        self.assertIsNotNone(self.tip._tip)
        self.tip.hide()
        self.assertIsNone(self.tip._tip)

    def test_destroying_the_control_leaves_no_tip_or_timer(self):
        self.tip.show()
        self.button.destroy()
        self.root.update()
        self.assertIsNone(self.tip._tip)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class QuietButtonTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root()

    def tearDown(self):
        self.root.destroy()

    def make(self, **kw):
        b = buttons.ModernButton(self.root, "Rescan", icon="refresh", kind="quiet", **kw)
        b.pack()
        self.root.update()
        return b

    def test_a_quiet_button_has_nothing_around_it_until_the_pointer_is_on_it(self):
        b = self.make()
        face, border, text = b._colours()
        self.assertEqual((face, border), (b._bg, b._bg))
        self.assertEqual(text, buttons.QUIET_TEXT)
        b._hover = True
        self.assertEqual(b._colours()[0], buttons.HOVER)
        b._down = True
        self.assertEqual(b._colours()[0], buttons.PRESSED)

    def test_a_compact_button_with_an_icon_is_a_square_named_by_a_tooltip(self):
        b = self.make(compact=True)
        if buttons.icon_family(b):                         # without an icon font the words stay
            self.assertEqual(int(b.cget("width")), int(b.cget("height")))
        self.assertEqual(b.cget("text"), "Rescan")          # its accessible name, and the tooltip's text

    def test_the_glyph_colour_is_readable_on_the_window(self):
        from mitoolkit.ui.components.shapes import contrast_ratio
        self.assertGreaterEqual(contrast_ratio(buttons.QUIET_TEXT, "#f0f0f0"), 4.5)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class SelectorFadeTests(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.var = tk.StringVar(value="usb")
        self.switch = ms.ModeSwitch(self.root, self.var, ("usb", "USB"), ("wifi", "Wi-Fi"))
        self.switch.pack()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def fills(self):
        s = self.switch
        return [s.itemcget(i, "fill") for i in s.find_all() if s.type(i) == "text"]

    def test_the_labels_fade_with_the_thumb(self):
        self.assertEqual(self.fills(), [ms.TEXT, ms.MUTED_TEXT])                    # at rest: dark and grey
        self.switch._pos = 0.5                                                      # half way across
        self.switch.draw()
        halfway = self.fills()
        self.assertEqual(halfway[0], halfway[1])                                    # both the same in-between colour
        self.assertEqual(halfway[0], mix(ms.MUTED_TEXT, ms.TEXT, 0.5))
        self.switch._pos = 1.0
        self.switch.draw()
        self.assertEqual(self.fills(), [ms.MUTED_TEXT, ms.TEXT])                    # arrived: swapped

    def test_a_click_ends_with_the_other_segment_chosen_after_the_fade(self):
        self.var.set("wifi")
        for _ in range(60):
            self.root.update()
            if self.switch._pos == 1.0:
                break
            self.root.after(10)
        self.assertEqual(self.fills(), [ms.MUTED_TEXT, ms.TEXT])


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class DialogBusyTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit import gui
        from mitoolkit.ui.wireless_dialog import WirelessDialog
        isolate_settings(self)
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app._polling = True
        self.root.update()
        self.dlg = WirelessDialog(self.app)

    def tearDown(self):
        self.dlg.close()
        self.root.destroy()

    def test_while_it_works_the_actions_are_greyed_instead_of_silently_ignored(self):
        d = self.dlg
        for button in (d.find_btn, d.pair_btn, d.connect_btn, d.qr_show):
            self.assertEqual(button.cget("state"), "normal")
        d._busy = True
        d._refresh()
        for button in (d.find_btn, d.pair_btn, d.connect_btn, d.qr_show):
            self.assertEqual(button.cget("state"), "disabled")
        d._busy = False
        d._refresh()
        self.assertEqual(d.find_btn.cget("state"), "normal")

    def test_the_address_boxes_show_examples_in_the_shape_of_a_local_address(self):
        examples = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Label) and "192.168" in str(child.cget("text")):
                    examples.append(child.cget("text"))
                walk(child)
        walk(self.dlg.win)
        self.assertEqual(sorted(examples), ["192.168.1.xx", "192.168.1.xx:41234"])


if __name__ == "__main__":
    unittest.main()
