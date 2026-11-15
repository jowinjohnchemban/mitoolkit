"""Search box: ranking of suggestions, keyboard and click behaviour, clean-up. And the details view."""
import os
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from mitoolkit.ui.components.search import rank  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False

APPS = [("FM Radio", "com.miui.fm"), ("Mi Browser", "com.mi.globalbrowser"), ("Calculator", "com.miui.calculator"),
        ("Browser Helper", "com.example.help"), ("Camera", "com.android.camera"), ("fm radio", "dup")]


class RankTests(unittest.TestCase):
    def test_starts_with_first_then_word_start_then_contains(self):
        names = [t for t, _n in rank("br", APPS)]
        self.assertEqual(names, ["Browser Helper", "Mi Browser"])               # "Browser" starts with it; "Mi Browser" has a word that does
        self.assertEqual([t for t, _ in rank("miui", APPS)], ["Calculator", "FM Radio"])   # found through the package

    def test_case_is_ignored_and_duplicates_are_not_offered_twice(self):
        self.assertEqual([t for t, _ in rank("FM", APPS)], ["FM Radio"])
        self.assertEqual(rank("", APPS), [])
        self.assertEqual(rank("zzz", APPS), [])

    def test_limit(self):
        many = [(f"app{i}", "") for i in range(30)]
        self.assertEqual(len(rank("app", many)), 8)
        self.assertEqual(len(rank("app", many, limit=3)), 3)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class SearchBoxTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit.ui.components.search import SearchBox
        self.root = make_root()
        self.var = tk.StringVar()
        self.picked = []
        self.box = SearchBox(self.root, self.var, "Search apps", suggest=lambda q: rank(q, APPS),
                             on_pick=self.picked.append)
        self.box.pack()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def type(self, text):
        self.box.entry.focus_force()
        self.root.update()
        self.box._typing = True
        self.var.set(text)
        self.root.update()

    def test_placeholder_shows_only_when_empty_and_unfocused(self):
        self.assertEqual(self.box.itemcget(self.box._hint_win, "state"), "normal")
        self.type("fm")
        self.assertEqual(self.box.itemcget(self.box._hint_win, "state"), "hidden")

    def test_typing_opens_suggestions_and_enter_picks_one(self):
        self.type("br")
        self.assertIsNotNone(self.box._popup)
        self.assertEqual(self.box._list.size(), 2)
        self.box._move(1)
        self.box._enter(SimpleNamespace())
        self.assertEqual(self.var.get(), "Browser Helper")
        self.assertEqual(self.picked, ["Browser Helper"])
        self.assertIsNone(self.box._popup)                    # a pick closes the list and does not open a new one

    def test_escape_closes_the_list_then_clears_the_text(self):
        self.type("br")
        self.box._escape(None)
        self.assertIsNone(self.box._popup)
        self.assertEqual(self.var.get(), "br")
        self.box._escape(None)
        self.assertEqual(self.var.get(), "")

    def test_clear_button_and_destroy_leave_nothing_behind(self):
        self.type("fm")
        self.box._click(SimpleNamespace(x=self.box.winfo_width() - 10, y=10))
        self.assertEqual(self.var.get(), "")
        self.type("br")
        self.box.destroy()
        self.root.update()
        self.assertEqual(self.var.trace_info(), [])             # its callback is off the variable


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class DetailsViewTests(unittest.TestCase):
    def test_sections_rows_and_height(self):
        from mitoolkit.ui.components.details_view import DetailsView
        from mitoolkit.ui.theme import Fonts
        root = make_root()
        root.geometry("600x400")                                     # a window that is mapped and has a width
        try:
            view = DetailsView(root, Fonts(root), "#5f6368", "#f0f0f0")
            view.pack(fill="x")
            view.set_sections([("Identity", [("Serial number", "6a81a217"), ("IMEI 1", "356831091234565")]),
                               ("Battery", [("Charge", "66%")])])
            root.update()
            view._fit()
            text = view.plain_text()
            self.assertIn("Identity", text)
            self.assertIn("IMEI 1\t356831091234565", text)
            self.assertGreater(int(view.cget("height")), 60)         # sized from the content, no inner scrollbar
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
