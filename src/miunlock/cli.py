import argparse
import functools
import json
import sys

from miunlock import __version__, adb, api, bloat, drivers, log
from miunlock.errors import MiunlockError
from miunlock.unlock import InteractiveUnlock


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
    """Decorator for subcommands: print the returned value as JSON. A MiunlockError prints
    {**on_error, "error": message} and exits 1; raising _Failed(result) prints result and exits 1."""
    def wrap(fn):
        @functools.wraps(fn)
        def run(args):
            try:
                result = fn(args)
            except _Failed as failed:
                _print_json(failed.result)
                sys.exit(1)
            except MiunlockError as e:
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


@json_command(installed=False)
def _cmd_install_driver(args):
    return {"installed": True, "message": drivers.install_usb_driver(_progress)}


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
        from miunlock import gui
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
        pass


def main():
    argv = sys.argv[1:]
    if "--gui" not in argv and (argv or "--cli" in argv):
        _attach_console()  # command-line use needs a console; the GUI must not have one
    log.setup()
    # One program, two modes: the GUI by default, the command line with --cli
    # (a subcommand such as `check` also means command line).
    args = sys.argv[1:]
    cli_flag = "--cli" in args
    gui_flag = "--gui" in args
    if "--mcp" in args:  # an AI agent controls the program directly
        from miunlock import mcp
        return mcp.serve()
    args = [a for a in args if a not in ("--cli", "--gui")]
    sys.argv = [sys.argv[0]] + args
    if gui_flag or (not args and not cli_flag):
        if _start_gui():
            return
        return interactive_main()
    if not args:
        return interactive_main()

    parser = argparse.ArgumentParser(
        prog="miunlock",
        description="Xiaomi bootloader unlock tool. Run with no arguments "
                     "for the interactive flow, or use a subcommand below "
                     "for scripting/automation (all output is JSON).",
    )
    parser.add_argument("--cli", action="store_true", help="Command-line mode (the default when a command is given). With no command: the interactive prompt.")
    parser.add_argument("--gui", action="store_true", help="Open the graphical app (the default when run with no arguments).")
    parser.add_argument("--mcp", action="store_true", help="Let an AI agent control the program over MCP (stdin/stdout). Cannot unlock.")
    parser.add_argument("--version", action="version", version=f"miunlock {__version__}")
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
    p_apps.add_argument("--known", action="store_true", help="With list: only apps in miunlock's known-bloat list.")
    p_apps.add_argument("--serial", help="Device serial, if more than one phone is connected.")
    p_apps.set_defaults(func=_cmd_apps)

    p_drv = sub.add_parser("install-driver", help="Windows only: download and install Google's official USB driver (asks for administrator permission).")
    p_drv.set_defaults(func=_cmd_install_driver)

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
