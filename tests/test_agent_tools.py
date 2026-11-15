"""The new read-only commands and tools: details and connections, and what agents are not shown."""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from mitoolkit import cli, diagnostics, mcp  # noqa: E402
from test_diagnostics import ReportTests  # noqa: E402

SECTIONS = [("Identity", [("IMEI 1", "356831091234565"), ("Android ID", "abcdef")]),
            ("Hardware", [("Board", "gram")])]


class McpToolTests(unittest.TestCase):
    def test_no_tool_can_unlock_or_erase(self):
        for name in mcp.TOOLS:
            self.assertNotIn("unlock_bootloader", name)
            self.assertNotIn("erase", name)
        self.assertIn("device_details", mcp.TOOLS)
        self.assertIn("connections", mcp.TOOLS)

    def test_device_details_leaves_out_what_identifies_the_phone(self):
        with mock.patch("mitoolkit.adb.more_details", return_value=SECTIONS):
            result = mcp._t_details({})
        titles = [s["title"] for s in result["sections"]]
        self.assertEqual(titles, ["Hardware"])
        self.assertNotIn("356831091234565", json.dumps(result))

    def test_addresses_are_left_out_in_every_section_not_only_identity(self):
        """The real phone's "Connectivity and state" section had a "Wi-Fi IP address" row that reached agents."""
        sections = [("Connectivity and state", [("Wi-Fi IP address", "192.168.1.5"), ("Wi-Fi switch", "On"),
                                                ("Default route", "via 192.168.1.1 dev wlan0"),
                                                ("Bluetooth address", "AA:BB:CC:DD:EE:FF"),
                                                ("Hardware serial", "6a81a217"), ("Link speed", "866 Mbps")]),
                    ("Hardware", [("Board", "gram"), ("Device ID", "abc123")])]
        with mock.patch("mitoolkit.adb.more_details", return_value=sections):
            result = mcp._t_details({})
        text = json.dumps(result)
        for private in ("192.168.1.5", "192.168.1.1", "AA:BB:CC:DD:EE:FF", "6a81a217", "abc123"):
            self.assertNotIn(private, text)
        rows = {r["label"]: r["value"] for s in result["sections"] for r in s["rows"]}
        self.assertEqual(rows, {"Wi-Fi switch": "On", "Default route": "via (hidden) dev wlan0",
                                "Link speed": "866 Mbps", "Board": "gram"})

    def test_connections_hides_network_and_device_names(self):
        report = diagnostics.build(ReportTests().raw(**{
            "dumpsys bluetooth_manager | head -n 160": "  enabled: true\n  name: My Phone\n"
                                                       "  AA:BB:CC:DD:EE:FF [ DEVICE_TYPE_CLASSIC ] Alice's Headphones\n"}))
        text_before = json.dumps(report)
        self.assertIn("Home Net", text_before)
        self.assertIn("Alice's Headphones", text_before)
        with mock.patch("mitoolkit.diagnostics.run", return_value=report), mock.patch("mitoolkit.adb.Phone"):
            hidden = json.dumps(mcp._t_connections({}))
        for private in ("Home Net", "a4:50:46:11:22:33", "192.168.1.23", "192.168.1.1", "Alice's Headphones",
                        "Neighbour", "Cafe", "My Phone"):
            self.assertNotIn(private, hidden, private)
        self.assertIn("-61 dBm", hidden)                                 # the state and signal stay
        self.assertIn("Jio 4G", hidden)

    def test_redact_does_not_change_the_original(self):
        report = diagnostics.build(ReportTests().raw())
        before = json.dumps(report)
        diagnostics.redact(report)
        self.assertEqual(json.dumps(report), before)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["mitoolkit", "--cli", *argv]), redirect_stdout(out):
            try:
                cli.main()
            except SystemExit:
                # the command line exits through SystemExit; its output is what the test reads
                pass
        return out.getvalue()

    def test_details_prints_every_section_as_json(self):
        with mock.patch("mitoolkit.adb.more_details", return_value=SECTIONS):
            data = json.loads(self.run_cli("details"))
        self.assertEqual([s["title"] for s in data["sections"]], ["Identity", "Hardware"])
        self.assertEqual(data["sections"][1]["rows"], [{"label": "Board", "value": "gram"}])

    def test_connections_prints_findings_and_runs_the_test_only_when_asked(self):
        report = diagnostics.build(ReportTests().raw())
        with mock.patch("mitoolkit.diagnostics.run", return_value=report), mock.patch("mitoolkit.adb.Phone"), \
                mock.patch("mitoolkit.diagnostics.network_test", return_value=[("Internet (8.8.8.8)", "ok", "ok")]) as test:
            plain = json.loads(self.run_cli("connections"))
            self.assertFalse(test.called)                                # no traffic unless asked
            self.assertNotIn("network_test", plain)
            asked = json.loads(self.run_cli("connections", "--network-test"))
            self.assertTrue(test.called)
            self.assertEqual(asked["network_test"][0]["label"], "Internet (8.8.8.8)")
        self.assertTrue(plain["findings"])


if __name__ == "__main__":
    unittest.main()
