"""adb features used before and around the unlock: see the phone, show its details, send
it to fastboot, copy files off it, and manage preinstalled apps.

Everything goes through miunlock's own adb client (adb_usb); no adb program is needed.
The only commands that change the phone are the reboot and, when you choose them in the
app manager, uninstalling or restoring apps for your user (``pm uninstall --user 0`` /
``cmd package install-existing``). Nothing runs as root, installs software or deletes
your files.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from miunlock import adb_usb, usbio
from miunlock.system import IS_TERMUX

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

_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


class AdbError(Exception):
    """str(e) is human-readable."""


def _check() -> None:
    if IS_TERMUX:
        raise AdbError("adb features are not available on Termux.")
    if not usbio.available():
        try:
            usbio.backend()
        except usbio.UsbError as err:
            raise AdbError(str(err)) from None


def _dev(serial: Optional[str]) -> adb_usb.AdbDevice:
    _check()
    try:
        return adb_usb.get(serial)
    except (adb_usb.AdbError, usbio.UsbError) as err:
        raise AdbError(str(err)) from None


def _shell(serial: Optional[str], command: str, timeout_ms: int = 60000) -> str:
    dev = _dev(serial)
    try:
        return dev.shell(command, timeout_ms)
    except (adb_usb.AdbError, usbio.UsbError) as err:
        if dev.state == "offline":
            adb_usb.forget(dev.serial)
        raise AdbError(str(err)) from None


def devices() -> List[Dict[str, str]]:
    """Phones with adb: [{"serial", "state"}]. State is "device" when ready,
    "unauthorized" while the phone waits for you to allow USB debugging, "no-access" when
    there is no driver or permission for it, or "offline"."""
    _check()
    try:
        return adb_usb.scan()
    except usbio.UsbError as err:
        raise AdbError(str(err)) from None


def device_info(serial: Optional[str] = None) -> Dict[str, object]:
    """Non-sensitive details: model, codename, Android and MIUI/HyperOS version, security
    patch, whether the bootloader is locked, battery level."""
    props: Dict[str, str] = {}
    for line in _shell(serial, "getprop").splitlines():
        m = re.match(r"\[(.+?)\]: \[(.*)\]", line.strip())
        if m:
            props[m.group(1)] = m.group(2)
    info: Dict[str, object] = {key: (props.get(prop) or None) for key, prop in _PROPS.items()}
    flag = info.pop("bootloader_locked")
    info["bootloader_locked"] = None if flag is None else flag == "1"
    info["battery"] = None
    try:
        for line in _shell(serial, "dumpsys battery").splitlines():
            if line.strip().startswith("level:"):
                info["battery"] = int(line.split(":", 1)[1])
                break
    except (AdbError, ValueError):
        pass
    return info


def reboot_to_bootloader(serial: Optional[str] = None) -> None:
    """Reboot a phone running Android into fastboot mode. It does not erase anything."""
    dev = _dev(serial)
    try:
        dev.reboot("bootloader")
    except (adb_usb.AdbError, usbio.UsbError) as err:
        raise AdbError(str(err)) from None
    finally:
        adb_usb.forget(dev.serial)


# --------------------------------------------------------------------- apps
def _packages(serial: Optional[str], flags: str) -> set:
    out = _shell(serial, f"pm list packages {flags}".strip())
    return {line.split(":", 1)[1].strip() for line in out.splitlines() if line.startswith("package:")}


def list_user_apps(serial: Optional[str] = None) -> List[str]:
    """Package names of the apps you installed (not the preinstalled ones)."""
    return sorted(_packages(serial, "-3"))


def list_packages(serial: Optional[str] = None) -> List[Dict[str, object]]:
    """Every app on the phone, including preinstalled ones removed for your user:
    [{"package", "system", "installed", "disabled"}]."""
    every = _packages(serial, "-u")
    installed = _packages(serial, "")
    system = _packages(serial, "-s -u")
    disabled = _packages(serial, "-d")
    return [{"package": p, "system": p in system, "installed": p in installed, "disabled": p in disabled}
            for p in sorted(every)]


def _valid(package: str) -> str:
    if not _PACKAGE.match(package):
        raise AdbError(f"Not a valid package name: {package!r}")
    return package


def uninstall_for_user(package: str, serial: Optional[str] = None) -> str:
    """Remove an app for your user only (``pm uninstall -k --user 0``). A preinstalled app
    stays on the system partition and can be restored; an app you installed yourself is
    removed and has to be installed again from the store."""
    out = _shell(serial, f"pm uninstall -k --user 0 {_valid(package)}").strip()
    if "Success" not in out:
        raise AdbError(out or "The phone did not confirm the removal.")
    return out


def restore_for_user(package: str, serial: Optional[str] = None) -> str:
    """Bring back a preinstalled app removed with uninstall_for_user."""
    pkg = _valid(package)
    out = _shell(serial, f"cmd package install-existing {pkg}").strip()
    if "installed" not in out.lower():
        out = _shell(serial, f"pm install-existing {pkg}").strip()
    if "installed" not in out.lower():
        raise AdbError(out or "The phone did not confirm the restore.")
    return out


# -------------------------------------------------------------------- backup
def backup_files(
    serial: Optional[str],
    dest: str,
    sets: List[str],
    log: Callable[[str], None] = lambda _t: None,
    cancel: Optional[threading.Event] = None,
) -> Dict[str, object]:
    """Copy the chosen folders from the phone to ``dest``, plus a list of installed apps.
    Read-only for the phone. Returns {"copied", "skipped", "files", "bytes", "dest",
    "cancelled"}. Raises AdbError if nothing could be copied."""
    unknown = [k for k in sets if k not in BACKUP_SETS]
    if unknown:
        raise AdbError(f"Unknown backup choice: {', '.join(unknown)}")
    dev = _dev(serial)
    target = Path(dest).expanduser()
    target.mkdir(parents=True, exist_ok=True)

    # "everything" already contains the other folders; do not copy them twice.
    wanted = ["/sdcard"] if "everything" in sets else [p for k in sets for p in BACKUP_SETS[k][1]]
    copied: List[str] = []
    skipped: List[str] = []
    failed_files = 0
    files = total = 0
    cancelled = False
    try:
        sync = dev.sync()
        for remote in wanted:
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            try:
                mode, _size, _mtime = sync.stat(remote.rstrip("/") + "/")
            except adb_usb.AdbError:
                mode = 0
            if mode == 0:
                skipped.append(remote)  # not on this phone
                continue
            log(f"Copying {remote} ...")
            base = target / remote.rstrip("/").rsplit("/", 1)[-1]
            for path, _mode, size, mtime in sync.walk(remote):
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                rel = path[len(remote.rstrip("/")) + 1:]
                local = base.joinpath(*[part for part in rel.split("/") if part not in ("", ".", "..")])
                local.parent.mkdir(parents=True, exist_ok=True)
                try:
                    total += sync.recv(path, local, cancel)
                    os.utime(local, (mtime, mtime))
                    files += 1
                    if files % 50 == 0:
                        log(f"{files} files, {total / 1e6:.0f} MB copied ...")
                except adb_usb.AdbError as err:
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                        break
                    failed_files += 1
                    if failed_files <= 20:
                        log(f"Skipped {path}: {err}")
            if cancelled:
                break
            copied.append(remote)
        sync.close()
    except (adb_usb.AdbError, usbio.UsbError) as err:
        raise AdbError(f"Backup stopped: {err}. Files copied so far are in {target}") from None

    try:
        apps = list_user_apps(dev.serial)
        (target / "installed-apps.txt").write_text("\n".join(apps) + "\n", encoding="utf-8")
        log(f"Saved the list of {len(apps)} installed apps.")
    except (AdbError, OSError):
        pass
    log(f"{files} files, {total / 1e6:.1f} MB copied" + (f", {failed_files} skipped." if failed_files else "."))
    if not copied and not cancelled:
        raise AdbError("Nothing was copied. Is the phone unlocked and file access allowed?")
    return {"copied": copied, "skipped": skipped, "files": files, "bytes": total,
            "failed_files": failed_files, "dest": str(target), "cancelled": cancelled}
