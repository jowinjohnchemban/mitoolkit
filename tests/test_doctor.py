"""The doctor: checks say what is wrong, safe fixes run by themselves, decisions only when asked."""
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from mitoolkit import adbkey, cli, doctor, mcp, settings, usbio  # noqa: E402
from mitoolkit.doctor import Check, FAIL, INFO, OK, WARN  # noqa: E402

try:
    import tkinter as tk
    tk.Tk().destroy()
    HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


class ProgramCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_a_private_key_that_others_can_read_is_fixed_safely(self):
        env = mock.patch.dict(os.environ, {"ANDROID_USER_HOME": str(self.dir)})
        env.start()
        self.addCleanup(env.stop)
        (self.dir / "adbkey").write_text("x")
        # a real key is slow to make, so a stand-in is parsed; what matters here is the permission check and fix
        with mock.patch.object(adbkey, "from_pem", return_value=object()), \
                mock.patch.object(doctor, "_too_open", return_value=True), mock.patch.object(doctor.os, "chmod") as chmod:
            check = doctor.check_adb_key()
            self.assertEqual((check.status, check.safe), (WARN, True))
            self.assertIn("readable by you only", check.fix())
        chmod.assert_called_once()

    def test_a_damaged_key_is_replaced_only_when_asked(self):
        env = mock.patch.dict(os.environ, {"ANDROID_USER_HOME": str(self.dir)})
        env.start()
        self.addCleanup(env.stop)
        (self.dir / "adbkey").write_text("not a key")
        with mock.patch.object(adbkey, "load_or_create") as make:
            check = doctor.check_adb_key()
            self.assertEqual((check.status, check.safe), (WARN, False))        # a decision: phones must allow it again
            self.assertEqual(doctor.apply([check]), [])                         # not run by the safe pass
            done = doctor.apply([check], include_decisions=True)
        self.assertTrue((self.dir / "adbkey.damaged").exists())
        make.assert_called()
        self.assertIn("new adb key", done[0][1])

    def test_a_damaged_settings_file_is_reset_safely(self):
        path = self.dir / "settings.json"
        path.write_text("{not json")
        with mock.patch.object(settings, "PATH", path):
            check = doctor.check_settings()
            self.assertEqual((check.status, check.safe), (WARN, True))
            doctor.apply([check])
        self.assertFalse(path.exists())
        self.assertTrue((self.dir / "settings.json.damaged").exists())
        with mock.patch.object(settings, "PATH", path):
            self.assertEqual(doctor.check_settings().status, OK)

    def test_files_left_by_an_update_are_removed(self):
        exe = self.dir / "mitoolkit.exe"
        exe.write_text("x")
        (self.dir / "mitoolkit.exe.old").write_text("old")
        with mock.patch("mitoolkit.updater.running_program", return_value=exe):
            check = doctor.check_update_leftovers()
            self.assertEqual((check.status, check.safe), (WARN, True))
            doctor.apply([check])
            self.assertFalse((self.dir / "mitoolkit.exe.old").exists())
            self.assertEqual(doctor.check_update_leftovers().status, OK)

    def test_missing_libusb_is_a_failure_with_the_command_to_run(self):
        with mock.patch.object(usbio, "available", return_value=False):
            check = doctor.check_libusb()
        self.assertEqual(check.status, FAIL)
        self.assertIn("pip install libusb-package", check.detail)

    def test_the_blocker_list_names_xiaomis_tool_and_not_this_program(self):
        self.assertIn("miunlock", usbio._BLOCKERS)            # Xiaomi's Mi Unlock tool
        self.assertNotIn("mitoolkit", usbio._BLOCKERS)        # this program must never block itself


class RunAndApplyTests(unittest.TestCase):
    def test_a_check_that_crashes_is_reported_not_raised(self):
        def broken():
            raise RuntimeError("boom")
        with mock.patch.object(doctor, "PROGRAM_CHECKS", (broken,)):
            checks = doctor.run(phone=False)
        self.assertEqual([c.status for c in checks], [WARN])
        self.assertIn("boom", checks[0].detail)

    def test_apply_runs_safe_fixes_only_unless_asked_and_survives_a_failing_fix(self):
        calls = []
        safe = Check("a", "safe", WARN, fix=lambda: calls.append("a") or "did a", safe=True)
        asks = Check("b", "asks", WARN, fix=lambda: calls.append("b") or "did b")
        broken = Check("c", "broken", WARN, fix=lambda: 1 / 0, safe=True)
        fine = Check("d", "fine", OK, fix=lambda: calls.append("d") or "no", safe=True)
        done = doctor.apply([safe, asks, broken, fine])
        self.assertEqual(calls, ["a"])
        self.assertEqual([c.id for c, _m in done], ["a", "c"])
        self.assertIn("Could not fix", done[1][1])
        doctor.apply([asks], include_decisions=True)
        self.assertEqual(calls, ["a", "b"])

    def test_auto_fix_never_looks_at_the_phone(self):
        with mock.patch.object(doctor, "check_phone") as phone, mock.patch.object(doctor, "PROGRAM_CHECKS", ()):
            self.assertEqual(doctor.auto_fix(), [])
        phone.assert_not_called()


class PhoneCheckTests(unittest.TestCase):
    def phone(self, *devices):
        with mock.patch("mitoolkit.adb.devices", return_value=list(devices)):
            return doctor.check_phone()

    def test_states_get_plain_advice(self):
        self.assertEqual(self.phone()[0].status, INFO)
        self.assertEqual(self.phone({"serial": "X", "state": "device"})[0].status, OK)
        waiting = self.phone({"serial": "X", "state": "unauthorized"})[0]
        self.assertEqual(waiting.status, WARN)
        self.assertIn("Always allow", waiting.detail)

    def test_an_offline_phone_can_have_its_connection_reset_safely(self):
        check = self.phone({"serial": "X", "state": "offline"})[0]
        self.assertTrue(check.safe)
        with mock.patch("mitoolkit.adb_usb.forget") as forget:
            self.assertIn("Dropped", check.fix())
        forget.assert_called_once_with("X")

    def test_a_phone_held_by_googles_adb_offers_to_stop_it_but_only_when_asked(self):
        with mock.patch.object(usbio, "blocking_programs", return_value=["adb"]):
            check = self.phone({"serial": "X", "state": "no-access", "reason": usbio.BUSY})[0]
        self.assertEqual((check.status, check.safe, check.fix_label), (WARN, False, "Stop Google's adb"))

    def test_a_missing_driver_has_advice_but_no_automatic_fix(self):
        check = self.phone({"serial": "X", "state": "no-access", "reason": usbio.NO_DRIVER})[0]
        self.assertIsNone(check.fix)
        self.assertIn("driver", check.detail.lower())


class CommandTests(unittest.TestCase):
    def run_cli(self, **kw):
        args = SimpleNamespace(fix=kw.get("fix", False), all=kw.get("all", False), no_phone=True)
        out = io.StringIO()
        code = 0
        with redirect_stdout(out):
            try:
                cli._cmd_doctor(args)
            except SystemExit as exit_:
                code = exit_.code
        return code, json.loads(out.getvalue())

    def test_report_and_exit_code(self):
        with mock.patch.object(doctor, "run", return_value=[Check("p", "Fine", OK)]):
            code, data = self.run_cli()
        self.assertEqual((code, data["ok"], data["problems"]), (0, True, 0))
        with mock.patch.object(doctor, "run", return_value=[Check("u", "No USB", FAIL, "x")]):
            code, data = self.run_cli()
        self.assertEqual((code, data["ok"], data["problems"]), (1, False, 1))

    def test_fix_runs_safe_fixes_and_looks_again(self):
        state = {"broken": True}

        def fix():
            state["broken"] = False
            return "repaired"

        def run(phone=True):
            return [Check("s", "Settings", WARN if state["broken"] else OK, fix=fix if state["broken"] else None, safe=True)]
        with mock.patch.object(doctor, "run", side_effect=run):
            code, data = self.run_cli(fix=True)
        self.assertEqual((code, data["ok"]), (0, True))
        self.assertEqual(data["fixed"], [{"id": "s", "result": "repaired"}])

    def test_agents_get_the_diagnosis_without_fixes(self):
        with mock.patch.object(doctor, "run", return_value=[Check("s", "Settings", WARN, fix=lambda: "x", safe=True)]):
            data = mcp.TOOLS["doctor"][2]({})
        self.assertEqual(data["problems"], 1)
        self.assertTrue(data["checks"][0]["fixable"])
        json.dumps(data)                                   # plain data: no callables leak into the answer


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class DialogTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit import gui
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app._polling = True
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def settle(self, dialog):
        import time
        for _ in range(80):
            self.root.update()
            if not dialog._busy:
                break
            time.sleep(0.03)

    def test_shows_problems_and_fixes_the_safe_ones(self):
        from mitoolkit.ui.doctor_dialog import DoctorDialog
        fixed = []
        checks = [Check("a", "Settings file is damaged", WARN, "d", fix=lambda: fixed.append(1) or "reset", fix_label="Reset", safe=True),
                  Check("b", "Python 3.13", OK)]
        with mock.patch.object(doctor, "run", return_value=checks):
            d = DoctorDialog(self.app)
            self.settle(d)
            self.assertIn("1 thing", d.summary.cget("text"))
            self.assertEqual(str(d.fix_all.cget("state")), "normal")
            d._fix_safe()
            self.settle(d)
        self.assertEqual(fixed, [1])
        d.close()

    def test_a_clean_report_says_so_and_offers_nothing_to_fix(self):
        from mitoolkit.ui.doctor_dialog import DoctorDialog
        with mock.patch.object(doctor, "run", return_value=[Check("b", "Python 3.13", OK)]):
            d = DoctorDialog(self.app)
            self.settle(d)
        self.assertEqual(d.summary.cget("text"), "No problems found.")
        self.assertEqual(str(d.fix_all.cget("state")), "disabled")
        d.close()


if __name__ == "__main__":
    unittest.main()
