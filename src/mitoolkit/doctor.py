"""The doctor: looks for what stops MiToolkit working, says what is wrong in plain words, and fixes what is safe.

Every check is a small function that returns a Check. A Check may carry a fix. Fixes come in two kinds:

* safe: cannot lose anything or interrupt anything else (tightening permissions on the program's own
  private files, removing a damaged settings file or a leftover from an update). These run by themselves at
  start-up and with ``mitoolkit doctor --fix``.
* needs a decision: stopping another program, making a new adb key (the phone then asks to allow once).
  These run only when a person chooses them (the Fix button, or ``--fix --all``).

Nothing here touches the phone's data, the Mi Account session's contents or Xiaomi's servers, and nothing
here makes a network request.
"""
from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

OK, INFO, WARN, FAIL = "ok", "info", "warn", "fail"
MARKS = {OK: "✔", INFO: "ℹ", WARN: "!", FAIL: "✖"}


@dataclass
class Check:
    id: str
    title: str
    status: str
    detail: str = ""
    fix: Optional[Callable[[], str]] = field(default=None, repr=False)   # returns a sentence saying what it did
    fix_label: str = ""
    safe: bool = False                                                   # may run without asking

    def to_dict(self) -> Dict[str, object]:
        return {"id": self.id, "title": self.title, "status": self.status, "detail": self.detail,
                "fixable": self.fix is not None, "fix": self.fix_label, "safe": self.safe}


# ------------------------------------------------------------------------------------------ the program
def check_python() -> Check:
    ok = sys.version_info >= (3, 9)
    return Check("python", f"Python {sys.version.split()[0]}", OK if ok else FAIL,
                 "" if ok else "MiToolkit needs Python 3.9 or newer.")


def check_tk() -> Check:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return Check("tk", "The window toolkit (Tk) is missing", WARN,
                     "The command line works, but the window does not. Install Tk: on Linux, for example, "
                     "sudo apt install python3-tk.")
    return Check("tk", "Window toolkit (Tk)", OK)


def check_pillow() -> Check:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return Check("pillow", "Pillow is not installed", INFO,
                     "Charts and gauges are drawn plainly instead of smoothly. pip install Pillow adds the smooth ones.")
    return Check("pillow", "Smooth charts (Pillow)", OK)


def check_libusb() -> Check:
    from mitoolkit import usbio
    if usbio.available():
        return Check("libusb", "USB access (libusb)", OK)
    return Check("libusb", "USB access (libusb) is not available", FAIL,
                 "MiToolkit cannot talk to a phone over USB. Run: pip install libusb-package (Linux: sudo apt "
                 "install libusb-1.0-0, macOS: brew install libusb).")


def _too_open(path: Path) -> bool:
    """True if other users can read this file or folder (POSIX; Windows ACLs are left to restrict_to_current_user)."""
    try:
        return os.name == "posix" and bool(path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))
    except OSError:
        return False


def check_adb_key() -> Check:
    from mitoolkit import adbkey
    path = adbkey.key_dir() / "adbkey"
    if not path.exists():
        return Check("adb-key", "No adb key yet", INFO, "It is made the first time a phone is connected.")
    try:
        adbkey.from_pem(path.read_text(encoding="ascii"))
    except Exception:
        def renew() -> str:
            path.replace(path.with_name("adbkey.damaged"))
            adbkey.load_or_create.cache_clear()
            adbkey.load_or_create()
            return "Made a new adb key (the old file is kept as adbkey.damaged). Each phone asks to allow it once."
        return Check("adb-key", "The adb key file is damaged", WARN,
                     "Phones cannot be authorised with it.", renew, "Make a new key", safe=False)
    if _too_open(path):
        def tighten() -> str:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            return f"Made {path} readable by you only."
        return Check("adb-key", "The adb key can be read by other users", WARN,
                     f"{path} should be private: it lets a computer act as yours towards your phone.",
                     tighten, "Make it private", safe=True)
    return Check("adb-key", "adb key", OK)


def check_session() -> Check:
    from mitoolkit.auth import store
    root = store.ROOT
    if not root.exists():
        return Check("session", "Saved Mi Account session", OK, "None saved.")
    loose = [p for p in [root, *root.rglob("*")] if _too_open(p)]
    if loose:
        def tighten() -> str:
            done = sum(1 for p in loose if store.restrict_to_current_user(p))
            return f"Made {done} of {len(loose)} session file(s) private to you."
        return Check("session", "The saved session can be read by other users", WARN,
                     f"{len(loose)} file(s) under {root} are open to others.", tighten, "Make them private", safe=True)
    if os.name != "posix":
        return Check("session", "Saved Mi Account session", OK, "Windows access rights are set when it is saved.")
    return Check("session", "Saved Mi Account session is private", OK)


def check_settings() -> Check:
    from mitoolkit import settings
    path = settings.PATH
    if not path.exists():
        return Check("settings", "Settings", OK, "Defaults in use.")
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return Check("settings", "Settings", OK)
    except (OSError, ValueError):
        pass

    def reset() -> str:
        path.replace(path.with_name(path.name + ".damaged"))
        return "Set the settings back to their defaults (the old file is kept as settings.json.damaged)."
    return Check("settings", "The settings file is damaged", WARN, "The defaults are used until it is reset.",
                 reset, "Reset the settings", safe=True)


def check_update_leftovers() -> Check:
    from mitoolkit import updater
    exe = updater.running_program()
    if exe is None:
        return Check("update-files", "Update files", OK)
    stale = [p for p in (updater.old_copy(exe), exe.with_name(exe.name + ".new")) if p.exists()]
    if not stale:
        return Check("update-files", "Update files", OK)

    def remove() -> str:
        for p in stale:
            p.unlink(missing_ok=True)
        return "Removed " + ", ".join(p.name for p in stale) + "."
    return Check("update-files", "Files left by an update", WARN, ", ".join(p.name for p in stale) + " next to the program.",
                 remove, "Remove them", safe=True)


def check_log() -> Check:
    from mitoolkit import log
    if log.log_path() is None:
        return Check("log", "No log file", WARN, "The program's folder is not writable, so nothing is logged for bug "
                     "reports. Run it from a folder you can write to.")
    return Check("log", "Log file", OK, str(log.log_path()))


def check_google_adb() -> Check:
    from mitoolkit import adb_server, platform_tools
    exe = platform_tools.find("adb")
    if exe is None:
        return Check("google-adb", "Google's adb (platform-tools) is not installed", INFO,
                     "Needed only for Wi-Fi (wireless adb, pairing). USB works without it.")
    state = "running" if adb_server.running() else "installed"
    return Check("google-adb", f"Google's adb is {state}", OK, exe)


# ---------------------------------------------------------------------------------------------- the phone
def check_phone() -> List[Check]:
    """What the connected phone needs. Reads the USB bus; never reads the phone's data."""
    from mitoolkit import adb, usbio
    try:
        found = adb.devices()
    except Exception as err:
        return [Check("phone", "Looking for a phone failed", WARN, str(err))]
    if not found:
        return [Check("phone", "No phone connected over adb", INFO,
                      "Connect it with a data cable and turn USB debugging on, or pair it over Wi-Fi.")]
    out: List[Check] = []
    for d in found:
        serial, state = d.get("serial", "?"), d.get("state")
        name = f"Phone {serial}"
        if state == "device":
            out.append(Check(f"phone-{serial}", f"{name} is ready", OK))
        elif state == "unauthorized":
            out.append(Check(f"phone-{serial}", f"{name} is waiting for you to allow it", WARN,
                             "Unlock the phone, tap Allow and tick \"Always allow from this computer\"."))
        elif state == "offline":
            def reset(s=serial) -> str:
                from mitoolkit import adb_usb
                adb_usb.forget(s)
                return f"Dropped the connection to {s}; the next look reconnects."
            out.append(Check(f"phone-{serial}", f"{name} is not answering", WARN,
                             "Unplug it and plug it back in, or turn USB debugging off and on.",
                             reset, "Reset the connection", safe=True))
        elif state == "no-access":
            reason = d.get("reason") or usbio.BUSY
            fix = None
            if reason == usbio.BUSY and "adb" in usbio.blocking_programs():
                def stop() -> str:
                    return ("Stopped Google's adb; it starts again the next time you use adb."
                            if usbio.stop_google_adb() else "Google's adb was not running.")
                fix = stop
            out.append(Check(f"phone-{serial}", f"{name} cannot be opened", WARN, usbio.no_access_advice(reason),
                             fix, "Stop Google's adb" if fix else "", safe=False))
        else:
            out.append(Check(f"phone-{serial}", f"{name}: {state}", INFO))
    return out


# ------------------------------------------------------------------------------------------------ running
PROGRAM_CHECKS: Tuple[Callable[[], Check], ...] = (
    check_python, check_tk, check_pillow, check_libusb, check_adb_key, check_session, check_settings,
    check_update_leftovers, check_log, check_google_adb,
)


def run(phone: bool = True) -> List[Check]:
    """Every check. A check that itself fails is reported, never raised: the doctor must not need a healthy system."""
    results: List[Check] = []
    for fn in PROGRAM_CHECKS:
        try:
            results.append(fn())
        except Exception as err:
            results.append(Check(fn.__name__.replace("check_", ""), f"Could not check {fn.__name__[6:]}", WARN, str(err)))
    if phone:
        try:
            results.extend(check_phone())
        except Exception as err:
            results.append(Check("phone", "Could not check the phone", WARN, str(err)))
    return results


def apply(checks: List[Check], include_decisions: bool = False) -> List[Tuple[Check, str]]:
    """Run the fixes: the safe ones, and with ``include_decisions`` the ones that need a decision too.
    Returns (check, what happened) for each fix that ran."""
    done: List[Tuple[Check, str]] = []
    for check in checks:
        if check.fix is None or check.status in (OK, INFO) or not (check.safe or include_decisions):
            continue
        try:
            done.append((check, check.fix()))
        except Exception as err:
            done.append((check, f"Could not fix it: {err}"))
    return done


def auto_fix() -> List[str]:
    """At start-up: the safe fixes that do not need the phone. Returns what was done, for the Activity log."""
    return [message for _check, message in apply(run(phone=False))]


def problems(checks: List[Check]) -> List[Check]:
    return [c for c in checks if c.status in (WARN, FAIL)]
