import argparse
import json
import sys

from miunlock.auth import get_passtoken, get_service, get_region, get_dataCenterZone

from miunlock.unlock import unlock_device
from miunlock.fastboot import get_fastboot
from miunlock.system import console, GREEN, WHITE, ORANGE
from miunlock import api


def interactive_main():
    """The original interactive flow. Unchanged behavior: run `miunlock`
    with no arguments and this is exactly what runs, same as always."""

    fastboot_cmd = get_fastboot()

    param = {"sid": 'unlockApi'}
    param["checkSafeAddress"] = True

    passToken = get_passtoken(param)
    if passToken is None:
        raise SystemExit(1)

    service = get_service(passToken, param)
    if service is None:
        raise SystemExit(1)

    region = get_region(passToken)
    if region is None:
        userId = passToken['userId']
        Zone = get_dataCenterZone(userId)
    else:
        console.print(f"\n[{GREEN}]Account Region: {region}[/]")
        if region == "CN":
            Zone = "China"
        elif region == "IN":
            Zone = "India"
        elif region == "RU":
            Zone = "Russia"
        elif region in {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "EL", "HU", "IS", "IE", "IT", "LV", "LI", "LT", "LU", "MT", "NL", "NO", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "UK"}:
            Zone = "Europe"
        else:
            Zone = "Singapore"

    if Zone is None:
        Zone = get_dataCenterZone()
    else:
        console.print(f"\n[{GREEN}]dataCenterZone: {Zone}[/]")
        user_input = console.input(f"\n[{WHITE}](Enter to continue, [{ORANGE}]m[/] to change dataCenterZone) > [/]").strip().lower()
        if user_input == "m":
            Zone = get_dataCenterZone()

    domain = {
        "Singapore": "https://unlock.update.intl.miui.com",
        "China": "https://unlock.update.miui.com",
        "India": "https://in-unlock.update.intl.miui.com",
        "Russia": "https://ru-unlock.update.intl.miui.com",
        "Europe": "https://eu-unlock.update.intl.miui.com",
    }.get(Zone)

    unlock_device(domain, service, fastboot_cmd)


# ---------------------------------------------------------------------------
# Non-interactive subcommands, for scripts / CI / AI agents. See api.py's
# module docstring for the safety design these are built on: everything
# here is safe to call freely EXCEPT `unlock`, which refuses to run
# without --confirm-wipe passed explicitly on the command line, every time.
# ---------------------------------------------------------------------------

def _print_json(obj):
    print(json.dumps(obj, indent=2, default=str))


def _cmd_login(args):
    try:
        token = api.login(login_method=args.method, silent_if_cached=not args.force)
        _print_json({"logged_in": True, "userId": token["userId"]})
    except api.UnlockError as e:
        _print_json({"logged_in": False, "error": str(e)})
        sys.exit(1)


def _cmd_status(args):
    try:
        token = api.login(silent_if_cached=True)
        zone = api.get_account_zone(token)
        result = {"logged_in": True, "userId": token["userId"], "zone": zone}
        try:
            result["device_codename"] = api.get_device_codename()
        except api.UnlockError as e:
            result["device_codename"] = None
            result["device_error"] = str(e) + " (is the phone in fastboot mode?)"
        _print_json(result)
    except api.UnlockError as e:
        _print_json({"logged_in": False, "error": str(e)})
        sys.exit(1)


def _cmd_check(args):
    try:
        token = api.login(silent_if_cached=True)
        result = api.check_unlock_eligibility(token)
        result.pop("_service", None)  # internal, not JSON-serializable, not anyone's business
        _print_json(result)
    except api.UnlockError as e:
        _print_json({"eligible": False, "error": str(e)})
        sys.exit(1)


def _cmd_unlock(args):
    if not args.confirm_wipe:
        _print_json({
            "success": False,
            "error": "Refusing to unlock: --confirm-wipe was not passed. "
                     "This wipes all data on the device with no undo. "
                     "Re-run with --confirm-wipe only after you mean it.",
        })
        sys.exit(1)
    try:
        token = api.login(silent_if_cached=True)
        eligibility = api.check_unlock_eligibility(token)
        if not eligibility.get("eligible"):
            eligibility.pop("_service", None)
            _print_json({"success": False, "eligibility": eligibility})
            sys.exit(1)
        result = api.perform_unlock(token, eligibility, confirm_wipe=True)
        _print_json(result)
    except api.UnlockError as e:
        _print_json({"success": False, "error": str(e)})
        sys.exit(1)


def main():
    # Bare `miunlock` with no arguments: run the original interactive flow,
    # byte-for-byte the same as every previous version of this tool.
    if len(sys.argv) == 1:
        return interactive_main()

    parser = argparse.ArgumentParser(
        prog="miunlock",
        description="Xiaomi bootloader unlock tool. Run with no arguments "
                     "for the interactive flow, or use a subcommand below "
                     "for scripting/automation (all output is JSON).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Log in (or reuse a saved session) and print account info as JSON.")
    p_login.add_argument("--method", choices=["1", "3"], default="1", help="1=browser (default), 3=QR code")
    p_login.add_argument("--force", action="store_true", help="Ignore any saved session and log in again.")
    p_login.set_defaults(func=_cmd_login)

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
