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
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

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


# What "Back up files" can copy. Each choice is a list of folders in the phone's shared
# storage. Copying only reads from the phone; nothing on it is changed or deleted.
BACKUP_SETS = {
    "photos": ("Photos and videos", ["/sdcard/DCIM", "/sdcard/Pictures", "/sdcard/Movies"]),
    "documents": ("Documents and downloads", ["/sdcard/Documents", "/sdcard/Download"]),
    "chats": ("Chat app media (WhatsApp, Telegram, ...)",
              ["/sdcard/WhatsApp", "/sdcard/Android/media", "/sdcard/Telegram"]),
    "audio": ("Music and recordings", ["/sdcard/Music", "/sdcard/Recordings", "/sdcard/MIUI/sound_recorder"]),
    "everything": ("Everything in shared storage (can be very large)", ["/sdcard"]),
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


def list_user_apps(serial: str, adb: Optional[str] = None) -> List[str]:
    """Package names of the apps you installed (not the system ones)."""
    adb = adb or get_adb()
    out = _run(adb, "-s", serial, "shell", "pm", "list", "packages", "-3")
    return sorted(line.split(":", 1)[1].strip() for line in out.splitlines() if line.startswith("package:"))


def backup_files(
    serial: str,
    dest: str,
    sets: List[str],
    adb: Optional[str] = None,
    log: Callable[[str], None] = lambda _t: None,
    cancel: Optional[threading.Event] = None,
) -> Dict[str, object]:
    """Copy the chosen folders from the phone to ``dest`` with ``adb pull``, plus a list of
    installed apps. Read-only for the phone. Returns {"copied": [...], "skipped": [...],
    "dest": path, "cancelled": bool}. Raises AdbError if there is nothing to copy."""
    adb = adb or get_adb()
    unknown = [k for k in sets if k not in BACKUP_SETS]
    if unknown:
        raise AdbError(f"Unknown backup choice: {', '.join(unknown)}")
    target = Path(dest).expanduser()
    target.mkdir(parents=True, exist_ok=True)

    # "everything" already contains the other folders; do not copy them twice.
    wanted = ["/sdcard"] if "everything" in sets else [p for k in sets for p in BACKUP_SETS[k][1]]
    copied: List[str] = []
    skipped: List[str] = []
    cancelled = False
    for remote in wanted:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        try:
            _run(adb, "-s", serial, "shell", "ls", "-d", remote)
        except AdbError:
            skipped.append(remote)  # folder does not exist on this phone
            continue
        log(f"Copying {remote} ...")
        proc = subprocess.Popen(
            [adb, "-s", serial, "pull", "-a", remote, str(target)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace", creationflags=NO_WINDOW,
        )
        last = ""
        for line in proc.stdout:  # type: ignore[union-attr]
            last = line.strip()
            if last.startswith("[") and last.count("%") and "]" in last:
                if int(last[1:last.index("%")].strip() or 0) % 10 == 0:
                    log(last[:140])
            if cancel is not None and cancel.is_set():
                proc.terminate()
                cancelled = True
                break
        proc.wait()
        if cancelled:
            break
        if proc.returncode == 0:
            copied.append(remote)
            log(last[:140] or f"Copied {remote}")
        else:
            skipped.append(remote)
            log(f"Could not copy {remote}: {last[:140]}")

    try:
        apps = list_user_apps(serial, adb)
        (target / "installed-apps.txt").write_text("\n".join(apps) + "\n", encoding="utf-8")
        log(f"Saved the list of {len(apps)} installed apps.")
    except (AdbError, OSError):
        pass
    if not copied and not cancelled:
        raise AdbError("Nothing was copied. Is the phone unlocked and USB file access allowed?")
    return {"copied": copied, "skipped": skipped, "dest": str(target), "cancelled": cancelled}
