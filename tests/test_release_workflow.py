"""The release workflow keeps its two promises: nothing is released unless every other check on the commit passed, and
the programs carry the version in their file names (the in-app updater looks for those names)."""
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")

    def test_every_other_workflow_that_runs_on_main_is_waited_for(self):
        names = re.search(r"expected='(\[.*?\])'", self.text)
        self.assertIsNotNone(names, "the release must wait for the other workflows")
        waited = set(re.findall(r'"([^"]+)"', names.group(1)))
        on_main = set()
        for path in WORKFLOWS.glob("*.yml"):
            workflow = path.read_text(encoding="utf-8")
            title = re.search(r"^name:\s*(.+)$", workflow, re.M).group(1).strip().strip('"')
            if title != "Release" and re.search(r"^on:\s*\n(?:.*\n)*?\s+push:\s*\n\s+branches:\s*\[main\]", workflow, re.M):
                on_main.add(title)
        self.assertEqual(waited, on_main, "a workflow that runs on main must be waited for, or it is not a gate")

    def test_the_gate_stops_the_release_on_a_failure_and_on_a_timeout(self):
        gate = self.text.split("Release only when every check on this commit is green")[1].split("Work out the version")[0]
        self.assertIn('.state == "failed"', gate)
        self.assertGreaterEqual(gate.count("exit 1"), 2)                           # a failed check, and a timeout
        self.assertIn("actions: read", self.text)

    def test_the_release_comes_after_the_gate_and_the_programs_carry_the_version(self):
        self.assertLess(self.text.index("Release only when every check"), self.text.index("Work out the version"))
        self.assertIn("-${RELEASE_TAG}${{ matrix.ext }}", self.text)
        self.assertIn("needs: [check, executables]", self.text)

    def test_no_python_packages_are_built(self):
        self.assertNotIn("python -m build", self.text)


if __name__ == "__main__":
    unittest.main()
