"""Tests for the phone security check (mitoolkit.security) with a fake phone and fake OSV data.
Nothing touches the network or a real phone."""
import datetime
import unittest
import unittest.mock as mock

from mitoolkit import security

TODAY = datetime.date(2026, 11, 15)


class FakePhone:
    def __init__(self, answers):
        self.answers = answers

    def shell(self, command):
        for start, out in self.answers.items():
            if command.startswith(start):
                return out
        return ""


class PatchLevelTests(unittest.TestCase):
    def osv(self, entries):
        return mock.patch.object(security, "osv_android", return_value=entries)

    def titles(self, report):
        return [(f.level, f.title) for f in report.findings]

    def test_missing_fixes_and_end_of_support(self):
        entries = {"A": {"spl": "2023-07-01", "severity": "Critical", "project": "p"},
                   "B": {"spl": "2024-01-01", "severity": "High", "project": "p"},
                   "C": {"spl": "2023-01-01", "severity": "High", "project": "p"},
                   "D": {"spl": "2025-03-01", "severity": "Moderate", "project": "p"}}
        report = security.Report()
        with self.osv(entries):
            security.check_patch_level(report, "12", "2023-06-01", TODAY)
        got = self.titles(report)
        self.assertIn((security.HIGH, "Android 12 no longer gets security fixes"), got)
        self.assertIn((security.HIGH, "3 known Android security fixes missing (1 critical, 1 high)"), got)

    def test_up_to_date_phone(self):
        entries = {"A": {"spl": "2026-10-01", "severity": "High", "project": "p"}}
        report = security.Report()
        with self.osv(entries):
            security.check_patch_level(report, "16", "2026-11-01", TODAY)
        self.assertEqual(report.findings[0].level, security.OK)
        self.assertEqual(report.verdict, "Nothing found")

    def test_offline_still_reports_age(self):
        report = security.Report()
        with mock.patch.object(security, "osv_android", side_effect=OSError("offline")):
            security.check_patch_level(report, "12", "2023-06-01", TODAY)
        self.assertEqual(report.findings[0].level, security.INFO)
        self.assertIn("41 months", report.findings[0].title)


class PlayAndAppsTests(unittest.TestCase):
    def test_play_protect_off_is_high(self):
        report = security.Report()
        security.check_play(report, FakePhone({"settings get global package_verifier_enable": "0\n"}), TODAY)
        self.assertEqual(report.findings[0].level, security.HIGH)

    def test_sideloaded_app_with_accessibility_is_high(self):
        phone = FakePhone({
            "pm list packages -i -3": "package:com.store.app  installer=com.android.vending\n"
                                      "package:com.side.loaded  installer=null\n",
            "settings get secure enabled_accessibility_services": "com.side.loaded/.Svc\n",
            "settings get secure enabled_notification_listeners": "com.store.app/.Listener\n",
            "dumpsys device_policy": "",
            "cmd appops query-op": "com.store.app\n",
        })
        report = security.Report()
        with mock.patch.object(security, "check_stalkerware"):
            security.check_apps(report, phone, lambda _t: None)
        by_pkg = {(f.package, f.level) for f in report.findings}
        self.assertIn(("com.side.loaded", security.HIGH), by_pkg)
        self.assertIn(("com.store.app", security.MEDIUM), by_pkg)

    def test_system_apps_with_access_are_not_flagged(self):
        phone = FakePhone({"pm list packages -i -3": "",
                           "settings get secure enabled_accessibility_services": "com.android.talkback/.T\n"})
        report = security.Report()
        with mock.patch.object(security, "check_stalkerware"):
            security.check_apps(report, phone, lambda _t: None)
        self.assertEqual([f for f in report.findings if f.package], [])


class StalkerwareListTests(unittest.TestCase):
    def test_parse_ioc(self):
        text = """- name: TheTruthSpy
  names:
  - Copy9
  type: stalkerware
  packages:
  - com.apspy.app
  - com.fone
  certificates:
  - 31a6ececd97cf39bc4126b8745cd94a7c30bf81c
  websites:
  - example.com
- name: Other
  packages:
    - org.other.spy
"""
        ioc = security.parse_ioc(text)
        self.assertEqual(ioc["com.fone"]["name"], "TheTruthSpy")
        self.assertEqual(ioc["com.apspy.app"]["certs"], {"31A6ECECD97CF39BC4126B8745CD94A7C30BF81C"})
        self.assertIn("org.other.spy", ioc)
        self.assertNotIn("example.com", ioc)

    def test_setting_lists_become_packages(self):
        self.assertEqual(security._packages_in_setting("a.b/.S:c.d/c.d.X"), {"a.b", "c.d"})
        self.assertEqual(security._packages_in_setting("null"), set())


if __name__ == "__main__":
    unittest.main()
