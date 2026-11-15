"""Buttons: a click leaves no selected look behind; the keyboard still gets a focus ring."""
import os
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class ButtonStateTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit.ui.components.buttons import ModernButton
        self.root = make_root()
        self.clicks = []
        self.button = ModernButton(self.root, "Back up files...", lambda: self.clicks.append(1))
        self.button.pack()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def click(self):
        b = self.button
        event = SimpleNamespace(x=5, y=5)
        b._on_enter(event)
        b._on_press(event)
        self.assertTrue(b._down and b._hover)
        b._on_release(event)

    def test_a_click_runs_the_command_and_leaves_no_hover_or_focus_look(self):
        self.click()
        b = self.button
        self.assertEqual(self.clicks, [1])
        self.assertFalse(b._hover)      # the pointer may never get a Leave if the click opens a window
        self.assertFalse(b._focus)
        self.assertFalse(b._down)
        self.assertFalse(b._mouse)

    def test_moving_over_the_button_again_brings_the_hover_tint_back(self):
        self.click()
        self.button._on_motion(SimpleNamespace(x=6, y=6))
        self.assertTrue(self.button._hover)

    def test_keyboard_focus_shows_a_ring_but_a_click_does_not(self):
        b = self.button
        b._set(focus=not b._mouse)       # what a FocusIn from Tab does
        self.assertTrue(b._focus)
        b._focus_lost()
        b._on_press(SimpleNamespace(x=1, y=1))
        self.assertFalse(b._focus)       # focus that comes from a press gets no ring

    def test_a_release_outside_the_button_does_not_click(self):
        b = self.button
        b._on_press(SimpleNamespace(x=1, y=1))
        b._on_release(SimpleNamespace(x=-50, y=-50))
        self.assertEqual(self.clicks, [])

    def test_state_kinds_have_colours(self):
        from mitoolkit.ui.components.buttons import KINDS
        for kind in ("danger", "warn", "good"):
            self.button.configure(kind=kind)
            face, border, text = self.button._colours()
            self.assertEqual(border, KINDS[kind][0])
            self.assertEqual(text, KINDS[kind][1])


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class NativeButtonTests(unittest.TestCase):
    """macOS uses the system's own buttons: the app still configures them with kind= and icon=."""

    def test_native_buttons_accept_the_same_options(self):
        import unittest.mock as mock
        from mitoolkit.ui.components import buttons
        root = make_root()
        try:
            with mock.patch.object(buttons.sys, "platform", "darwin"):
                button = buttons.Button(root, "Security check...")
                radio = buttons.Button(root, "1 min", variable=tk.StringVar(), value="1")
            button.configure(text="Security check... !", kind="warn", icon="shield")
            radio.configure(text="1 hr", icon="clock")
            self.assertEqual(button.cget("text"), "Security check... !")
            self.assertEqual(button.kind, "warn")
            self.assertEqual(radio.cget("text"), "1 hr")
            self.assertTrue(button.configure())            # a query still works
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
