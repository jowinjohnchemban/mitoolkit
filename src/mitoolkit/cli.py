import argparse
import functools
import json
import sys
from pathlib import Path

from mitoolkit import adb, api, bloat, build, drivers, log
from mitoolkit.errors import MitoolkitError
from mitoolkit.unlock import InteractiveUnlock


def interactive_main():
    """The interactive command-line flow (prompts between the steps)."""
    InteractiveUnlock().run()


# ---------------------------------------------------------------------------
# Non-interactive subcommands, for scripts / CI / AI agents. See api.py's
# module docstring for the safety design these are built on: everything
# here is safe to call freely EXCEPT `unlock`, which refuses to run
# without --confirm-wipe passed explicitly on the command line, every time.
# ---------------------------------------------------------------------------

class _Failed(Exception):
    """Print this result as JSON and exit with status 1."""

    def __init__(self, result):
        super().__init__()
        self.result = result


def _print_json(obj):
    print(json.dumps(obj, indent=2, default=str))


def json_command(**on_error):
    """Decorator for subcommands: print the returned value as JSON. A MitoolkitError prints
    {**on_error, "error": message} and exits 1; raising _Failed(result) prints result and exits 1."""
    def wrap(fn):
        @functools.wraps(fn)
        def run(args):
            try:
                result = fn(args)
            except _Failed as failed:
                _print_json(failed.result)
                sys.exit(1)
            except MitoolkitError as e:
                _print_json({**on_error, "error": str(e)})
                sys.exit(1)
            _print_json(result)
        return run
    return wrap


def _progress(text: str) -> None:
    print(text, file=sys.stderr)


@json_command(logged_in=False)
def _cmd_login(args):
    token = api.login(login_method=args.method, silent_if_cached=not args.force)
    return {"logged_in": True, "userId": token["userId"]}


@json_command()
def _cmd_devices(args):
    return api.list_devices()


@json_command(success=False)
def _cmd_reboot_fastboot(args):
    return api.reboot_to_fastboot(args.serial)


@json_command(copied=[])
def _cmd_backup(args):
    sets = [s.strip() for s in args.only.split(",") if s.strip()]
    return adb.backup_files(args.serial, args.dest, sets, log=_progress)


@json_command()
def _cmd_apps(args):
    if args.action == "list":
        out = []
        for app in adb.list_packages(args.serial):
            if args.known and app["package"] not in bloat.KNOWN:
                continue
            name, rating, note = bloat.describe(app["package"], app["system"])
            out.append({**app, "name": name, "rating": rating, "note": note})
        return out
    if not args.packages:
        raise adb.AdbError("Name at least one package.")
    action = adb.uninstall_for_user if args.action == "remove" else adb.restore_for_user
    results = {}
    for pkg in args.packages:
        try:
            action(pkg, args.serial)
            results[pkg] = "ok"
        except adb.AdbError as e:
            results[pkg] = str(e)
    if any(v != "ok" for v in results.values()):
        raise _Failed(results)
    return results


@json_command()
def _cmd_security_check(args):
    from mitoolkit import security
    return security.run(args.serial, _progress).to_dict()


@json_command()
def _cmd_details(args):
    """Everything the phone reports over USB (what Show more shows), as JSON."""
    return {"sections": [{"title": title, "rows": [{"label": k, "value": v} for k, v in rows]}
                         for title, rows in adb.more_details(args.serial)]}


@json_command()
def _cmd_connections(args):
    """Wi-Fi, mobile network, SIM, Bluetooth and USB readings with findings (the Connections window)."""
    from mitoolkit import diagnostics
    report = diagnostics.run(adb.Phone(args.serial))
    if args.network_test:
        gateway = next((v for _t, rows in report["sections"] for k, v, _l in rows if k == "Gateway (router)"), None)
        report["network_test"] = [{"label": k, "value": v, "level": lvl}
                                  for k, v, lvl in diagnostics.network_test(adb.Phone(args.serial), gateway)]
    return report


def _run_named_fix(args):
    """`doctor --run-fix NAME --result-file FILE`: what the administrator copy of the program runs. Only the fixes
    named in doctor.PRIVILEGED exist; the result goes to a file because an elevated process's output is not readable."""
    from mitoolkit import doctor
    try:
        result = {"ok": True, "message": doctor.run_privileged(args.run_fix)}
    except Exception as err:
        result = {"ok": False, "message": str(err)}
    if args.result_file:
        try:
            Path(args.result_file).write_text(json.dumps(result), encoding="utf-8")
        except OSError:
            pass                                          # the exit code still says whether it worked
    if not result["ok"]:
        raise _Failed(result)
    return result


@json_command()
def _cmd_doctor(args):
    """Check the setup, and with --fix repair what is safe to repair (--all: what needs a decision too)."""
    from mitoolkit import doctor
    if args.run_fix:                                       # the elevated copy: one named fix, then report back
        return _run_named_fix(args)
    checks = doctor.run(phone=not args.no_phone)
    fixed = []
    if args.fix:
        fixed = [{"id": c.id, "result": message} for c, message in doctor.apply(checks, include_decisions=args.all)]
        if fixed:
            checks = doctor.run(phone=not args.no_phone)           # look again: what is left
    left = doctor.problems(checks)
    result = {"ok": not left, "problems": len(left), "fixed": fixed, "checks": [c.to_dict() for c in checks]}
    if any(c.status == doctor.FAIL for c in left):
        raise _Failed(result)
    return result


@json_command(installed=False)
def _cmd_driver_help(args):
    """Plain text, not JSON: it is for people."""
    print(drivers.instructions())
    if args.open and drivers.supported():
        drivers.open_download_page()


@json_command(logged_in=False)
def _cmd_status(args):
    token = api.login(silent_if_cached=True)
    result = {"logged_in": True, "userId": token["userId"], "zone": api.get_account_zone(token)}
    try:
        result["device_codename"] = api.get_device_codename()
    except api.UnlockError as e:
        result["device_codename"] = None
        result["device_error"] = str(e) + " (is the phone in fastboot mode?)"
    return result


def _public(eligibility: dict) -> dict:
    """The eligibility dict without the internal session (not JSON, not anyone's business)."""
    return {k: v for k, v in eligibility.items() if not k.startswith("_")}


@json_command(eligible=False)
def _cmd_check(args):
    return _public(api.check_unlock_eligibility(api.login(silent_if_cached=True)))


@json_command(success=False)
def _cmd_unlock(args):
    if not args.confirm_wipe:
        raise _Failed({
            "success": False,
            "error": "Refusing to unlock: --confirm-wipe was not passed. "
                     "This wipes all data on the device with no undo. "
                     "Re-run with --confirm-wipe only after you mean it.",
        })
    token = api.login(silent_if_cached=True)
    eligibility = api.check_unlock_eligibility(token)
    if not eligibility.get("eligible"):
        raise _Failed({"success": False, "eligibility": _public(eligibility)})
    return api.perform_unlock(token, eligibility, confirm_wipe=True)


def _start_gui() -> bool:
    """Open the GUI. False (after saying why) if it cannot, so the caller can fall back."""
    try:
        from mitoolkit import gui
    except ImportError:
        print("The graphical app needs Tkinter, which is not installed. Using the command line instead.\n"
              "(Linux: sudo apt install python3-tk)", file=sys.stderr)
        return False
    gui.main()
    return True


def _attach_console():
    """The Windows program is built without a console, so double-clicking it opens only
    the GUI (no black window). For command-line use, borrow the console of the terminal
    that started us, or the redirected pipes, and point the standard streams at it."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        import msvcrt
        import os
        k32 = ctypes.windll.kernel32
        k32.GetStdHandle.restype = ctypes.c_void_p
        k32.AttachConsole(-1)  # ATTACH_PARENT_PROCESS; harmless if it fails or is already attached

        def stream(std_handle, fallback, mode, fd_flags):
            handle = k32.GetStdHandle(std_handle)
            if handle in (None, 0, ctypes.c_void_p(-1).value):
                return open(fallback, mode, encoding="utf-8", errors="replace", buffering=1 if "w" in mode else -1)
            fd = msvcrt.open_osfhandle(handle, fd_flags)
            return os.fdopen(fd, mode, encoding="utf-8", errors="replace", buffering=1 if "w" in mode else -1)

        if sys.stdout is None:
            sys.stdout = stream(-11, "CONOUT$", "w", 0)
        if sys.stderr is None:
            sys.stderr = stream(-12, "CONOUT$", "w", 0)
        if sys.stdin is None:
            sys.stdin = stream(-10, "CONIN$", "r", os.O_RDONLY)
    except Exception:
        # no console to attach to (started from a shortcut, say): carry on without one
        pass


def main():
    debug = "--debug" in sys.argv[1:]
    sys.argv = [a for a in sys.argv if a != "--debug"]       # a flag for every mode, not for the parser
    argv = sys.argv[1:]
    if "--gui" not in argv and (argv or "--cli" in argv):
        _attach_console()  # command-line use needs a console; the GUI must not have one
    log.setup(True if debug else None)
    # One program, two modes: the GUI by default, the command line with --cli
    # (a subcommand such as `check` also means command line).
    args = sys.argv[1:]
    cli_flag = "--cli" in args
    gui_flag = "--gui" in args
    if "--mcp" in args:  # an AI agent controls the program directly
        from mitoolkit import mcp
        mcp.serve()
        return
    args = [a for a in args if a not in ("--cli", "--gui")]
    sys.argv = [sys.argv[0]] + args
    if gui_flag or (not args and not cli_flag):
        if not _start_gui():          # no display or no Tk: the interactive prompt instead
            interactive_main()
        return
    if not args:
        interactive_main()
        return

    parser = argparse.ArgumentParser(
        prog="mitoolkit",
        description="Xiaomi bootloader unlock tool. Run with no arguments "
                     "for the interactive flow, or use a subcommand below "
                     "for scripting/automation (all output is JSON).",
    )
    parser.add_argument("--cli", action="store_true", help="Command-line mode (the default when a command is given). With no command: the interactive prompt.")
    parser.add_argument("--gui", action="store_true", help="Open the graphical app (the default when run with no arguments).")
    parser.add_argument("--mcp", action="store_true", help="Let an AI agent control the program over MCP (stdin/stdout). Cannot unlock.")
    parser.add_argument("--version", action="version", version=f"mitoolkit {build.full_version()}")
    parser.add_argument("--debug", action="store_true", help="Write step-by-step debug details to mitoolkit.log "
                        "(also: set MITOOLKIT_DEBUG=1, or Help > Debug logging in the app). Secrets stay hidden.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Log in (or reuse a saved session) and print account info as JSON.")
    p_login.add_argument("--method", choices=["1", "3"], default="1", help="1=browser (default), 3=QR code")
    p_login.add_argument("--force", action="store_true", help="Ignore any saved session and log in again.")
    p_login.set_defaults(func=_cmd_login)

    p_dev = sub.add_parser("devices", help="List phones seen by adb and fastboot. Read-only.")
    p_dev.set_defaults(func=_cmd_devices)

    p_rb = sub.add_parser("reboot-fastboot", help="Use adb to reboot a phone running Android into fastboot mode. Erases nothing.")
    p_rb.add_argument("--serial", help="Device serial, if more than one phone is connected.")
    p_rb.set_defaults(func=_cmd_reboot_fastboot)

    p_bk = sub.add_parser("backup", help="Copy files from a phone running Android to this computer over adb. Read-only for the phone.")
    p_bk.add_argument("--dest", required=True, help="Folder to save into.")
    p_bk.add_argument("--only", default="photos,documents",
                      help="Comma-separated: photos, documents, chats, audio, everything (default: photos,documents).")
    p_bk.add_argument("--serial", help="Device serial, if more than one phone is connected.")
    p_bk.set_defaults(func=_cmd_backup)

    p_apps = sub.add_parser("apps", help="List, remove (for your user) or restore apps on a phone running Android.")
    p_apps.add_argument("action", choices=["list", "remove", "restore"])
    p_apps.add_argument("packages", nargs="*", help="Package names for remove/restore.")
    p_apps.add_argument("--known", action="store_true", help="With list: only apps in mitoolkit's known-bloat list.")
    p_apps.add_argument("--serial", help="Device serial, if more than one phone is connected.")
    p_apps.set_defaults(func=_cmd_apps)

    p_sec = sub.add_parser("security-check", help="Read-only security check of a phone running Android: patch level vs. "
                                                  "Android security bulletins (OSV), Play Protect, app sources, known stalkerware.")
    p_sec.add_argument("--serial", help="Device serial, if more than one phone is connected.")
    p_sec.set_defaults(func=_cmd_security_check)

    p_det = sub.add_parser("details", help="Everything a phone running Android reports over USB (identity, hardware, modem, "
                                           "SIM, boot, servicing, partitions, sensors) as JSON. Read-only.")
    p_det.add_argument("--serial", help="Device serial, if more than one phone is connected.")
    p_det.set_defaults(func=_cmd_details)

    p_con = sub.add_parser("connections", help="Wi-Fi, mobile network (modem), SIM, Bluetooth and USB readings with plain-language "
                                               "findings, as JSON. Read-only, unless --network-test (a few pings from the phone).")
    p_con.add_argument("--serial", help="Device serial, if more than one phone is connected.")
    p_con.add_argument("--network-test", action="store_true",
                       help="Also ping the router and 8.8.8.8 and look up a name, from the phone.")
    p_con.set_defaults(func=_cmd_connections)

    p_doc = sub.add_parser("doctor", help="Check the setup (Python, USB access, adb key, saved session, settings, the "
                                          "phone) and say what is wrong. --fix repairs what is safe to repair.")
    p_doc.add_argument("--fix", action="store_true", help="Repair what is safe: permissions on private files, a damaged "
                       "settings file, files left by an update, a stuck connection.")
    p_doc.add_argument("--all", action="store_true", help="With --fix: also what needs a decision (stop Google's adb, "
                       "make a new adb key if the old one is damaged).")
    p_doc.add_argument("--no-phone", action="store_true", help="Do not look at the USB bus for a phone.")
    from mitoolkit import doctor as _doctor
    p_doc.add_argument("--run-fix", choices=sorted(_doctor.PRIVILEGED), help=argparse.SUPPRESS)      # internal
    p_doc.add_argument("--result-file", help=argparse.SUPPRESS)                                      # internal
    p_doc.set_defaults(func=_cmd_doctor)

    p_drv = sub.add_parser("driver-help", help="Windows: how to install Google's USB driver. --open opens Google's download page.")
    p_drv.add_argument("--open", action="store_true", help="Also open Google's download page in the browser.")
    p_drv.set_defaults(func=_cmd_driver_help)

    p_status = sub.add_parser("status", help="Print account + device status as JSON. Never touches fastboot oem unlock.")
    p_status.set_defaults(func=_cmd_status)

    p_check = sub.add_parser("check", help="Ask Xiaomi's server if this account/device is eligible to unlock right now. Safe, read-only.")
    p_check.set_defaults(func=_cmd_check)

    p_unlock = sub.add_parser("unlock", help="Actually unlock the bootloader. WIPES THE DEVICE. Requires --confirm-wipe.")
    p_unlock.add_argument("--confirm-wipe", action="store_true",
                           help="Required. Without this flag the command refuses to run. "
                                "Only pass this after a human has decided to proceed.")
    p_unlock.set_defaults(func=_cmd_unlock)

    args = parser.parse_args()
    args.func(args)
