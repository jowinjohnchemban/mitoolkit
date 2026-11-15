"""WCAG 2.2 AA checks for the GUI: colour contrast (1.4.3 text 4.5:1, 1.4.11 graphics 3:1)
and text resizing up to 200% (1.4.4)."""
import unittest

from mitoolkit.ui import theme as t

WINDOW_BG, WHITE = "#fafafa", "#ffffff"
NATIVE_BG = "#f0f0f0"  # Windows' own window colour (the native theme)


def _luminance(colour: str) -> float:
    c = colour.lstrip("#")
    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(int(c[i:i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


TEXT_PAIRS = [
    ("muted text, native", t.MUTED, NATIVE_BG), ("green, native", t.GREEN, NATIVE_BG),
    ("red, native", t.RED, NATIVE_BG), ("amber, native", t.AMBER, NATIVE_BG), ("body, native", t.TEXT, NATIVE_BG),
    ("body text", t.TEXT, WINDOW_BG), ("muted text", t.MUTED, WINDOW_BG), ("muted on white", t.MUTED, WHITE),
    ("green", t.GREEN, WINDOW_BG), ("green on white", t.GREEN, WHITE), ("red", t.RED, WINDOW_BG),
    ("amber", t.AMBER, WINDOW_BG), ("amber on white", t.AMBER, WHITE), ("warning banner", t.WARN_FG, t.WARN_BG),
    ("next-step badge", WHITE, t.ACCENT), ("done badge", WHITE, t.GREEN), ("not-yet badge", WHITE, t.LOCKED),
    ("unlock button", WHITE, t.RED), ("activity text", t.CONSOLE_FG, t.CONSOLE_BG),
    ("activity time", t.CONSOLE_DIM, t.CONSOLE_BG), ("activity red", t.RED, t.CONSOLE_BG),
    ("activity green", t.GREEN, t.CONSOLE_BG), ("activity header", t.CONSOLE_FG, t.CONSOLE_HEAD),
    ("activity header note", t.CONSOLE_DIM, t.CONSOLE_HEAD),
]
GRAPHIC_PAIRS = [("phone status dot", t.ORANGE_DOT, WINDOW_BG), ("status dot, native", t.ORANGE_DOT, NATIVE_BG), ("rating dot red", t.RED, WHITE),
                 ("rating dot amber", t.AMBER, WHITE)]


class ContrastTests(unittest.TestCase):
    def test_text_has_at_least_4_5_to_1(self):
        for name, fg, bg in TEXT_PAIRS:
            with self.subTest(name):
                self.assertGreaterEqual(contrast(fg, bg), 4.5, f"{name}: {fg} on {bg}")

    def test_graphics_have_at_least_3_to_1(self):
        for name, fg, bg in GRAPHIC_PAIRS:
            with self.subTest(name):
                self.assertGreaterEqual(contrast(fg, bg), 3.0, f"{name}: {fg} on {bg}")


class ThemeChoiceTests(unittest.TestCase):
    ALL = ("alt", "aqua", "clam", "classic", "default", "vista", "winnative")

    def pick(self, platform, names=ALL):
        import unittest.mock as mock
        with mock.patch.object(t.sys, "platform", platform):
            return t.native_theme_name(names)

    def test_each_system_gets_its_own_theme(self):
        self.assertEqual(self.pick("win32"), "vista")
        self.assertEqual(self.pick("darwin"), "aqua")
        self.assertEqual(self.pick("linux"), "clam")

    def test_falls_back_when_the_native_theme_is_missing(self):
        self.assertEqual(self.pick("win32", ("clam", "default")), "clam")
        self.assertEqual(self.pick("linux", ("default", "alt")), "alt")


class TextSizeTests(unittest.TestCase):
    def test_text_can_double_and_return(self):
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception:
            raise unittest.SkipTest("no display")
        try:
            root.withdraw()
            t.apply_theme(root)
            fonts = t.Fonts(root)
            body = t.named_font("TkDefaultFont", root)
            normal, heading = body.actual("size"), fonts.heading.actual("size")
            t.scale_fonts(root, 2.0, fonts.all())
            self.assertGreaterEqual(body.actual("size"), normal * 2 - 1)
            self.assertGreaterEqual(fonts.heading.actual("size"), heading * 2 - 1)
            t.scale_fonts(root, 1.0, fonts.all())
            self.assertEqual(body.actual("size"), normal)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()


class ComponentContrastTests(unittest.TestCase):
    """Text in every state of the new components, not just at rest (WCAG 1.4.3)."""

    def check(self, name, fg, bg, ratio=4.5):
        self.assertGreaterEqual(contrast(fg, bg), ratio, f"{name}: {fg} on {bg} is {contrast(fg, bg):.2f}")

    def test_buttons_in_every_state(self):
        from mitoolkit.ui.components import buttons as b
        for face in (b.FACE, b.HOVER, b.PRESSED):
            self.check("button text", b.TEXT, face)
        for face in (b.PRIMARY, b.PRIMARY_HOVER, b.PRIMARY_PRESSED):
            self.check("main button text", "#ffffff", face)
        for kind, (border, text, hover, pressed) in b.KINDS.items():
            for face in (b.FACE, hover, pressed):
                self.check(f"{kind} button text", text, face)
            self.check(f"{kind} button border", border, "#ffffff", 3.0)            # 1.4.11
        for face in (NATIVE_BG, b.HOVER, b.PRESSED):
            self.check("expander text", b.ACCENT, face)

    def test_selector_bar(self):
        from mitoolkit.ui.components import selector as s
        for bg in (NATIVE_BG, s.HOVER_FILL):
            self.check("selector text", s.TEXT, bg)
            self.check("selector muted text", s.MUTED_TEXT, bg)

    def test_text_in_chart_colours_is_readable_on_the_card(self):
        from mitoolkit.ui.components import charts, shapes
        for name in ("BLUE", "GREEN", "RED", "ORANGE", "PURPLE", "OK_COLOUR", "WARN_COLOUR", "CRIT_COLOUR"):
            colour = getattr(charts, name)
            self.check(f"{name} as text", shapes.text_colour(colour), shapes.CARD)
        self.check("axis text", charts.AXIS_TEXT, shapes.CARD)
        self.check("card text", charts.TEXT, shapes.CARD)

    def test_status_marks_in_the_connections_window(self):
        from mitoolkit.ui.components.shapes import CARD
        from mitoolkit.ui.connect_dialog import MARKS
        for mark, colour, word in MARKS.values():
            self.check(f"mark {word}", colour, CARD)

    def test_text_colour_only_darkens_when_it_must(self):
        from mitoolkit.ui.components.shapes import text_colour
        self.assertEqual(text_colour("#1b1b1b"), "#1b1b1b")          # already dark: unchanged
        self.assertNotEqual(text_colour("#91cc75"), "#91cc75")       # a light green is darkened
        self.check("darkened light green", text_colour("#91cc75"), WHITE)


class ChartColourTests(unittest.TestCase):
    """Graph lines and gauge arcs must stand out from the white plot (WCAG 1.4.11: 3:1)."""

    def test_chart_colours_contrast_with_white(self):
        from mitoolkit.ui.components import charts
        for name in ("BLUE", "GREEN", "RED", "ORANGE", "PURPLE", "OK_COLOUR", "WARN_COLOUR", "CRIT_COLOUR"):
            colour = getattr(charts, name)
            self.assertGreaterEqual(contrast(colour, "#ffffff"), 3.0, f"{name} {colour}")
