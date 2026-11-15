"""adb (Android Debug Bridge) helpers, used to manage the phone before the unlock.

adb talks to a phone that is running Android with USB debugging on, while
``fastboot`` talks to one in the bootloader. With adb the tool can see the phone
earlier, show what it is, and send it to fastboot for you instead of making you
hold buttons.

Everything here is read-only or a plain reboot. Nothing runs ``adb root``,
``adb install``, ``adb shell`` with a write, or touches your files.
"""
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from miunlock.system import SYSTEM, IS_TERMUX, NO_WINDOW, make_executable

_PROPS = {
    "model": "ro.product.model",
    "codename": "ro.product.device",
    "android": "ro.build.version.release",
    "miui": "ro.miui.ui.version.name",
    "hyperos": "ro.mi.os.version.name",
    "bootloader_locked": "ro.boot.flash.locked",
    "brand": "ro.product.brand",
    "security_patch": "ro.build.version.security_patch",
}

# Read-only fastboot variables worth showing. "unlocked" is the bootloader state.
_FASTBOOT_VARS = {
    "product": "product",
    "unlocked": "unlocked",
    "bootloader_version": "version-bootloader",
    "slot": "current-slot",
    "serial": "serialno",
}


class AdbError(Exception):
    """adb is missing or a command failed. str(e) is human-readable."""


def get_adb() -> str:
    """Find adb, or download Google's platform-tools (which include it) on first use."""
    if IS_TERMUX:
        raise AdbError("adb is not set up automatically on Termux; use `pkg install android-tools`.")
    found = shutil.which("adb")
    if found:
        return found
    exe = "adb.exe" if SYSTEM == "Windows" else "adb"
    local = Path.home() / "platform-tools" / exe
    if not local.exists():
        from miunlock.fastboot import download_platform_tools
        download_platform_tools()
    if not local.exists():
        raise AdbError("adb could not be found or installed.")
    make_executable(str(local))
    return str(local)


def _run(adb: str, *args: str, timeout: int = 15) -> str:
    try:
        done = subprocess.run(
            [adb, *args], capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW
        )
    except subprocess.TimeoutExpired:
        raise AdbError("adb did not answer in time.") from None
    except OSError as err:
        raise AdbError(f"Could not run adb ({type(err).__name__}).") from None
    if done.returncode != 0:
        raise AdbError((done.stderr or done.stdout).strip() or f"adb exited with {done.returncode}")
    return done.stdout


def devices(adb: Optional[str] = None) -> List[Dict[str, str]]:
    """Phones adb can see: [{"serial", "state"}]. State is ``device`` when ready,
    ``unauthorized`` if the phone is waiting for you to accept the USB-debugging prompt,
    or ``offline``."""
    adb = adb or get_adb()
    out = _run(adb, "devices")
    found = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            found.append({"serial": parts[0], "state": parts[1]})
    return found


def device_info(serial: str, adb: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Read a few non-sensitive properties (model, codename, Android and MIUI version,
    whether the bootloader is locked) from a phone that is in the ``device`` state."""
    adb = adb or get_adb()
    info: Dict[str, Optional[str]] = {}
    for key, prop in _PROPS.items():
        value = _run(adb, "-s", serial, "shell", "getprop", prop).strip()
        info[key] = value or None
    flag = info.pop("bootloader_locked")
    info["bootloader_locked"] = None if flag is None else flag == "1"
    info["battery"] = None
    try:  # charge level, so you can check the phone is above 50%
        for line in _run(adb, "-s", serial, "shell", "dumpsys", "battery").splitlines():
            if line.strip().startswith("level:"):
                info["battery"] = int(line.split(":", 1)[1])
                break
    except (AdbError, ValueError):
        pass
    return info


def fastboot_info(fastboot: str, serial: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Read-only facts about a phone in fastboot mode: codename, whether the bootloader is
    already unlocked, bootloader version, active slot. Uses ``fastboot getvar`` only."""
    info: Dict[str, Optional[str]] = {}
    base = [fastboot] + (["-s", serial] if serial else [])
    for key, var in _FASTBOOT_VARS.items():
        value = None
        try:
            done = subprocess.run(base + ["getvar", var], capture_output=True, text=True,
                                  timeout=8, creationflags=NO_WINDOW)
            for line in (done.stderr + done.stdout).splitlines():  # fastboot prints "var: value" on stderr
                if line.startswith(var + ":"):
                    value = line.split(":", 1)[1].strip() or None
                    break
        except (subprocess.SubprocessError, OSError):
            pass
        info[key] = value
    return info


def reboot_to_bootloader(serial: Optional[str] = None, adb: Optional[str] = None) -> None:
    """Reboot a phone running Android into fastboot mode. It does not erase anything."""
    adb = adb or get_adb()
    args = ["-s", serial] if serial else []
    _run(adb, *args, "reboot", "bootloader")
