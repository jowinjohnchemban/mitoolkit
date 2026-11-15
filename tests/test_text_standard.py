"""The text standard (see AGENTS.md): what the person reads is written one way everywhere.

* No "..." or "…" in text (a status says what is happening; a button names what it does).
* No decorative symbols as separators or bullets in text.
* Labels (buttons, menu items, window titles) are in Title Case.

The scan reads every string in the program's source (not docstrings or comments), so a new string that breaks the standard
fails here instead of reaching a window.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "mitoolkit"
sys.path.insert(0, str(ROOT.parent))

SKIP_DIRS = {"auth", "__pycache__", "assets"}        # auth is the code the program started from: not its own text
DECORATIVE = "·●◌❚▶◀•…"                            # separators, bullets and the like (status marks like a tick are fine)
SMALL = {"a", "an", "the", "and", "or", "but", "for", "nor", "of", "to", "in", "on", "at", "by", "from", "with", "as",
         "into", "over", "via", "vs"}
LABEL_CALLS = {"Button", "ModernButton", "add_command", "add_cascade", "add_checkbutton", "_add"}


def sources():
    for path in sorted(ROOT.rglob("*.py")):
        if not (set(path.relative_to(ROOT).parts) & SKIP_DIRS):
            yield path, ast.parse(path.read_text(encoding="utf-8"))


def docstring_nodes(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                found.add(id(body[0].value))
    return found


def strings(tree):
    skip = docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node


def is_title_case(label: str) -> bool:
    """Every word starts with a capital, except the small words in the middle. Words with no letters, acronyms,
    "Wi-Fi", "Step-by-Step" and the like pass; the mnemonic marker (&) is ignored."""
    words = label.replace("&", "").split()
    for i, word in enumerate(words):
        core = re.sub(r"^[^A-Za-z]+", "", word)
        if not core or not core[0].isalpha():
            continue
        if core.lower() in SMALL and 0 < i < len(words) - 1:
            continue
        if not core[0].isupper():
            return False
    return True


def label_texts(tree):
    """(line, text) of every button, menu item and window title given as a plain string."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func).split(".")[-1]
            if name in LABEL_CALLS:
                for kw in node.keywords:
                    if kw.arg in ("text", "label") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        yield node.lineno, kw.value.value
                if name == "_add" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) \
                        and isinstance(node.args[1].value, str):
                    yield node.lineno, node.args[1].value
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "title" for t in node.targets) \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            yield node.lineno, node.value.value


class TextStandardTests(unittest.TestCase):
    def test_no_ellipses_in_text(self):
        found = [f"{path.relative_to(ROOT)}:{n.lineno}: {n.value[:50]!r}" for path, tree in sources()
                 for n in strings(tree) if "..." in n.value or "…" in n.value]
        self.assertEqual(found, [], "Write what is happening, or name what the button does, without dots.")

    def test_no_decorative_symbols_in_text(self):
        found = [f"{path.relative_to(ROOT)}:{n.lineno}: {n.value[:50]!r}" for path, tree in sources()
                 for n in strings(tree) if n.value.strip() and any(ch in DECORATIVE for ch in n.value)
                 and not n.value.strip() in {"●"}]              # the status dot of the phone section is a drawn mark
        self.assertEqual(found, [])

    def test_labels_are_in_title_case(self):
        found = [f"{path.relative_to(ROOT)}:{line}: {text!r}" for path, tree in sources()
                 for line, text in label_texts(tree) if text.strip() and not is_title_case(text)]
        self.assertEqual(found, [], "Buttons, menu items and window titles are in Title Case.")

    def test_the_title_case_rule_itself(self):
        for good in ("Back Up Files", "Pair or Connect", "Reboot to Fastboot", "Step-by-Step Guide", "Wi-Fi Connection",
                     "&Sign In to Mi Account", "Close", "Re&start or Power Off", "Look It Up on the Web", "USB Driver Help"):
            self.assertTrue(is_title_case(good), good)
        for bad in ("Back up files", "Pair or connect", "Sign in", "check Again", "Show more"):
            self.assertFalse(is_title_case(bad), bad)

    def test_names_keep_their_own_spelling(self):
        """Names and acronyms are written the same everywhere a label or message uses them."""
        wrong = ("Wi-fi", "Wifi ", "Minitoolkit", "Mitoolkit", "Usb ", "Gpu ", "Ram ")
        found = [f"{path.relative_to(ROOT)}:{n.lineno}: {bad!r}" for path, tree in sources() for n in strings(tree)
                 for bad in wrong if bad in n.value and not n.value.startswith(("http", "/"))]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
