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
        args = SimpleNamespace(fix=kw.get("fix", False), all=kw.get("all", False), no_phone=True,
                               run_fix=kw.get("run_fix"), result_file=kw.get("result_file"))
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


class AdministratorTests(unittest.TestCase):
    """Fixes that may need administrator rights: tried as the user first, then the system is asked."""

    def test_only_named_fixes_can_run(self):
        with self.assertRaises(ValueError):
            doctor.run_privileged("rm -rf /")
        self.assertEqual(sorted(doctor.PRIVILEGED), ["stop-adb", "udev-rules"])

    def test_no_prompt_when_the_fix_works_as_the_user(self):
        from mitoolkit import elevate
        with mock.patch.dict(doctor.PRIVILEGED, {"stop-adb": lambda: "stopped"}), \
                mock.patch.object(elevate, "run_self") as ask:
            self.assertEqual(doctor.with_admin("stop-adb"), "stopped")
        ask.assert_not_called()

    def test_asks_for_administrator_only_after_permission_was_refused(self):
        from mitoolkit import elevate

        def refused():
            raise PermissionError("access denied")
        with mock.patch.dict(doctor.PRIVILEGED, {"stop-adb": refused}), mock.patch.object(elevate, "is_admin", return_value=False), \
                mock.patch.object(elevate, "run_self", return_value=(True, "Stopped as administrator.")) as ask:
            self.assertEqual(doctor.with_admin("stop-adb"), "Stopped as administrator.")
        ask.assert_called_once_with(["doctor", "--run-fix", "stop-adb"])

    def test_declining_the_prompt_changes_nothing_and_says_so(self):
        from mitoolkit import elevate

        def refused():
            raise PermissionError("access denied")
        with mock.patch.dict(doctor.PRIVILEGED, {"stop-adb": refused}), mock.patch.object(elevate, "is_admin", return_value=False), \
                mock.patch.object(elevate, "run_self", return_value=(False, "Administrator permission was not given, so nothing was changed.")):
            with self.assertRaisesRegex(PermissionError, "not given"):
                doctor.with_admin("stop-adb")

    def test_an_administrator_is_not_asked_again(self):
        from mitoolkit import elevate

        def refused():
            raise PermissionError("still denied")
        with mock.patch.dict(doctor.PRIVILEGED, {"stop-adb": refused}), mock.patch.object(elevate, "is_admin", return_value=True), \
                mock.patch.object(elevate, "run_self") as ask:
            with self.assertRaises(PermissionError):
                doctor.with_admin("stop-adb")
        ask.assert_not_called()

    def test_apply_reports_a_refusal_instead_of_raising(self):
        def refused():
            raise PermissionError("Administrator permission was not given, so nothing was changed.")
        check = Check("x", "Held by adb", WARN, fix=refused, fix_label="Stop it", needs_admin=True)
        done = doctor.apply([check], include_decisions=True)
        self.assertIn("not given", done[0][1])
        self.assertTrue(check.to_dict()["admin"])

    def test_linux_permission_problem_offers_the_udev_rule_as_an_administrator_fix(self):
        with mock.patch("mitoolkit.adb.devices", return_value=[{"serial": "X", "state": "no-access", "reason": usbio.NO_PERMISSION}]), \
                mock.patch.object(doctor.sys, "platform", "linux"):
            check = doctor.check_phone()[0]
        self.assertEqual((check.fix_label, check.needs_admin, check.safe), ("Allow USB access", True, False))

    def test_udev_rules_are_written_and_reloaded(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(doctor.sys, "platform", "linux"), \
                mock.patch.object(doctor, "UDEV_FILE", str(Path(tmp) / "51.rules")), mock.patch("subprocess.run") as run:
            message = doctor.install_udev_rules()
            text = (Path(tmp) / "51.rules").read_text()
        self.assertIn('idVendor}=="2717"', text)
        self.assertIn("uaccess", text)
        self.assertEqual(run.call_count, 2)
        self.assertIn("Unplug", message)
        with mock.patch.object(doctor.sys, "platform", "win32"):
            with self.assertRaises(OSError):
                doctor.install_udev_rules()

    def test_the_elevated_copy_runs_one_named_fix_and_reports_through_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "r.json"
            kw = dict(run_fix="stop-adb", result_file=str(result))
            out = io.StringIO()
            with mock.patch.dict(doctor.PRIVILEGED, {"stop-adb": lambda: "done"}), redirect_stdout(out):
                cli._cmd_doctor(SimpleNamespace(fix=False, all=False, no_phone=True, **kw))
            self.assertEqual(json.loads(result.read_text()), {"ok": True, "message": "done"})

            def broken():
                raise PermissionError("denied")
            code = 0
            with mock.patch.dict(doctor.PRIVILEGED, {"stop-adb": broken}), redirect_stdout(io.StringIO()):
                try:
                    cli._cmd_doctor(SimpleNamespace(fix=False, all=False, no_phone=True, **kw))
                except SystemExit as exit_:
                    code = exit_.code
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(result.read_text())["ok"])


class ElevateTests(unittest.TestCase):
    def test_program_command(self):
        from mitoolkit import elevate
        self.assertEqual(elevate.program_command()[-2:], ["-m", "mitoolkit"])
        with mock.patch.object(elevate.sys, "frozen", True, create=True), mock.patch.object(elevate.sys, "executable", "C:/x/mitoolkit.exe"):
            self.assertEqual(elevate.program_command(), ["C:/x/mitoolkit.exe"])

    def run_with(self, code, write=None):
        from mitoolkit import elevate
        seen = {}

        def fake(command, timeout):
            seen["command"] = command
            if write is not None:
                Path(command[-1]).write_text(json.dumps(write))
            return code
        with mock.patch.object(elevate, "_windows", fake), mock.patch.object(elevate, "_posix", fake), \
                mock.patch.object(elevate, "_macos", fake):
            return elevate.run_self(["doctor", "--run-fix", "stop-adb"]), seen

    def test_the_result_file_carries_the_answer_and_the_command_is_fixed(self):
        (worked, message), seen = self.run_with(0, {"ok": True, "message": "Stopped."})
        self.assertEqual((worked, message), (True, "Stopped."))
        self.assertEqual(seen["command"][-4:-1], ["--run-fix", "stop-adb", "--result-file"])
        self.assertIn("--run-fix", seen["command"])
        self.assertTrue(seen["command"][-1].endswith(".json"))

    def test_declined_prompt(self):
        (worked, message), _seen = self.run_with(None)
        self.assertFalse(worked)
        self.assertIn("not given", message)

    def test_a_crash_without_a_result_file_is_reported(self):
        (worked, message), _seen = self.run_with(1)
        self.assertFalse(worked)
        self.assertIn("did not finish", message)

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_windows_launch_and_wait_returns_the_exit_code(self):
        """The same ShellExecuteEx plumbing as the UAC path, with the plain "open" verb so no prompt appears."""
        from mitoolkit import elevate
        code = elevate._windows([sys.executable, "-c", "import sys; sys.exit(7)"], 30, verb="open")
        self.assertEqual(code, 7)

    def test_linux_uses_polkit_with_a_desktop_and_sudo_without(self):
        from mitoolkit import elevate
        calls = []
        with mock.patch("subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0)), \
                mock.patch.object(elevate.shutil, "which", side_effect=lambda n: f"/usr/bin/{n}"):
            with mock.patch.dict(os.environ, {"DISPLAY": ":0"}):
                self.assertEqual(elevate._posix(["prog", "doctor"], 5), 0)
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(elevate._posix(["prog", "doctor"], 5), 0)
        self.assertEqual([c[0] for c in calls], ["pkexec", "sudo"])
        with mock.patch.object(elevate.shutil, "which", return_value=None):
            self.assertIsNone(elevate._posix(["prog"], 5))

    def test_macos_prompt_is_quoted_and_cancel_is_a_no(self):
        from mitoolkit import elevate
        with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stderr="")) as run:
            elevate._macos(['/Apps/My "App"/mitoolkit', "doctor"], 5)
        script = run.call_args[0][0][2]
        self.assertIn("with administrator privileges", script)
        self.assertIn('\\"App\\"', script)                    # quotes cannot break out of the AppleScript string
        with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stderr="User canceled. (-128)")):
            self.assertIsNone(elevate._macos(["x"], 5))


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
