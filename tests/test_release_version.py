"""The release version: Conventional Commits decide the bump, the tag is the source of truth, the build is stamped."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import release_version as rv  # noqa: E402


class BumpTests(unittest.TestCase):
    def test_titles_map_to_bumps(self):
        for title, expected in [("feat: add the doctor", "minor"), ("feat(ui): wider window", "minor"),
                                ("fix: stop a crash", "patch"), ("docs: reword the guide", "patch"),
                                ("ci: update actions", "patch"), ("chore: tidy", "patch"),
                                ("feat!: drop Python 3.9", "major"), ("fix(api)!: rename login", "major"),
                                ("Add something without a type", "patch")]:
            self.assertEqual(rv.bump_for(title), expected, title)

    def test_breaking_change_in_the_body_is_major(self):
        self.assertEqual(rv.bump_for("fix: x\n\nBREAKING CHANGE: the command was renamed"), "major")

    def test_labels_override_the_title_and_skip_means_no_release(self):
        self.assertEqual(rv.bump_for("fix: small", ["major"]), "major")
        self.assertEqual(rv.bump_for("feat: big", ["patch", "docs"]), "patch")
        self.assertIsNone(rv.bump_for("docs: typo [skip release]"))

    def test_the_biggest_bump_among_merges_wins(self):
        self.assertEqual(rv.biggest(["patch", "minor", "patch"]), "minor")
        self.assertEqual(rv.biggest(["patch", None, "major", "minor"]), "major")
        self.assertIsNone(rv.biggest([None, None]))

    def test_next_version_resets_the_lower_numbers(self):
        self.assertEqual(rv.next_version((1, 4, 7), "patch"), (1, 4, 8))
        self.assertEqual(rv.next_version((1, 4, 7), "minor"), (1, 5, 0))
        self.assertEqual(rv.next_version((1, 4, 7), "major"), (2, 0, 0))

    def test_tags_are_compared_as_numbers(self):
        self.assertEqual(max(["v1.9.0", "v1.10.0", "v1.2.0"], key=rv.parse_tag), "v1.10.0")
        self.assertIsNone(rv.parse_tag("1.2.3"))
        self.assertIsNone(rv.parse_tag("v1.2"))
        self.assertIsNone(rv.parse_tag("v1.2.3-beta"))

    def test_decide(self):
        tag, bump = rv.decide("v1.0.0", [("fix: a", []), ("feat: b", [])])
        self.assertEqual((tag, bump), ("v1.1.0", "minor"))
        self.assertEqual(rv.decide(None, [("fix: a", [])]), ("v1.0.0", "patch"))        # the first release
        self.assertEqual(rv.decide("v1.0.0", [("fix: a", [])], forced="major"), ("v2.0.0", "major"))
        self.assertIsNone(rv.decide("v1.0.0", [])[0])
        self.assertIsNone(rv.decide("v1.0.0", [("docs: x [skip release]", [])])[0])


class GitTests(unittest.TestCase):
    """The whole script against a real (temporary) repository."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = os.getcwd()
        self.addCleanup(os.chdir, self.old)
        os.chdir(self.tmp.name)
        patched = mock.patch.dict(os.environ)            # no token: pull request labels are not looked up
        patched.start()
        self.addCleanup(patched.stop)
        for env in ("GH_TOKEN", "GITHUB_REPOSITORY"):
            os.environ.pop(env, None)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    def commit(self, message):
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rv.main(list(argv))
        return code, dict(line.split("=", 1) for line in out.getvalue().splitlines() if "=" in line)

    def test_next_release_from_the_merges_since_the_last_tag(self):
        self.commit("feat: first")
        self.git("tag", "v1.0.0")
        self.commit("fix: one (#1)")
        self.commit("feat: two (#2)")
        self.commit("docs: three (#3)")
        code, out = self.run_main()
        self.assertEqual((code, out), (0, {"release": "true", "tag": "v1.1.0", "version": "1.1.0", "bump": "minor"}))

    def test_a_patch_only_history_gives_a_patch(self):
        self.commit("feat: first")
        self.git("tag", "v1.4.2")
        self.commit("fix: only a fix (#4)")
        self.assertEqual(self.run_main()[1]["tag"], "v1.4.3")

    def test_nothing_new_means_no_release(self):
        self.commit("feat: first")
        self.git("tag", "v1.0.0")
        self.assertEqual(self.run_main()[1], {"release": "false"})          # the tag is on HEAD already

    def test_manual_bump_and_no_tags_yet(self):
        self.commit("chore: start")
        self.assertEqual(self.run_main()[1]["tag"], "v1.0.0")
        self.git("tag", "v1.0.0")
        self.commit("fix: x")
        self.assertEqual(self.run_main("--bump", "major")[1]["tag"], "v2.0.0")
        self.assertEqual(self.run_main("--bump", "huge")[0], 2)


class StampTests(unittest.TestCase):
    def test_the_version_is_written_into_the_build_tree_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            init = Path(tmp) / "src" / "mitoolkit" / "__init__.py"
            init.parent.mkdir(parents=True)
            init.write_text('__version__ = "1.0.0"\nother = 1\n')
            run = lambda v: subprocess.run([sys.executable, str(SCRIPTS / "stamp_version.py"), v], cwd=tmp,
                                           capture_output=True, text=True)
            self.assertEqual(run("v2.3.4").returncode, 0)
            self.assertEqual(init.read_text(), '__version__ = "2.3.4"\nother = 1\n')
            self.assertNotEqual(run("2.3").returncode, 0)                     # not major.minor.patch: refused


if __name__ == "__main__":
    unittest.main()
