"""adb features used before and around the unlock: see the phone, show its details, send
it to fastboot, copy files off it, and manage preinstalled apps.

Everything goes through miunlock's own adb client (adb_usb); no adb program is needed.
``Phone`` is the object to use; the module-level functions are short forms of it, kept for
the CLI, API and MCP.

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
from miunlock.adb_usb import AdbError  # noqa: F401 (the one adb error type, re-exported)
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


def _check() -> None:
    if IS_TERMUX:
        raise AdbError("adb features are not available on Termux.")
    try:
        usbio.backend()
    except usbio.UsbError as err:
        raise AdbError(str(err)) from None


def _valid(package: str) -> str:
    """Package names go into a shell command, so only real package names are accepted."""
    if not _PACKAGE.match(package):
        raise AdbError(f"Not a valid package name: {package!r}")
    return package


def devices() -> List[Dict[str, str]]:
    """Phones with adb: [{"serial", "state"}]. State is "device" when ready,
    "unauthorized" while the phone waits for you to allow USB debugging, "no-access" when
    there is no driver or permission for it, or "offline"."""
    _check()
    try:
        return adb_usb.scan()
    except usbio.UsbError as err:
        raise AdbError(str(err)) from None


class Phone:
    """A phone running Android with USB debugging allowed."""

    def __init__(self, serial: Optional[str] = None):
        _check()
        try:
            self._dev = adb_usb.get(serial)
        except usbio.UsbError as err:
            raise AdbError(str(err)) from None
        self.serial = self._dev.serial

    # ----------------------------------------------------------------- basics
    def shell(self, command: str, timeout_ms: int = 60000) -> str:
        try:
            return self._dev.shell(command, timeout_ms)
        except (AdbError, usbio.UsbError) as err:
            if self._dev.state == "offline":
                adb_usb.forget(self.serial)
            raise AdbError(str(err)) from None

    def info(self) -> Dict[str, object]:
        """Non-sensitive details: model, codename, Android and MIUI/HyperOS version, security
        patch, whether the bootloader is locked, battery level."""
        props: Dict[str, str] = {}
        for line in self.shell("getprop").splitlines():
            m = re.match(r"\[(.+?)\]: \[(.*)\]", line.strip())
            if m:
                props[m.group(1)] = m.group(2)
        info: Dict[str, object] = {key: (props.get(prop) or None) for key, prop in _PROPS.items()}
        flag = info.pop("bootloader_locked")
        info["bootloader_locked"] = None if flag is None else flag == "1"
        info["battery"] = self.battery()
        return info

    def battery(self) -> Optional[int]:
        try:
            for line in self.shell("dumpsys battery").splitlines():
                if line.strip().startswith("level:"):
                    return int(line.split(":", 1)[1])
        except (AdbError, ValueError):
            pass
        return None

    def reboot_to_bootloader(self) -> None:
        """Reboot into fastboot mode. It does not erase anything."""
        try:
            self._dev.reboot("bootloader")
        except usbio.UsbError as err:
            raise AdbError(str(err)) from None
        finally:
            adb_usb.forget(self.serial)

    def sync(self) -> adb_usb.SyncSession:
        """adb's file-transfer session (stat, list, receive)."""
        try:
            return self._dev.sync()
        except usbio.UsbError as err:
            raise AdbError(str(err)) from None

    # ------------------------------------------------------------------- apps
    def _packages(self, flags: str = "") -> set:
        out = self.shell(f"pm list packages {flags}".strip())
        return {line.split(":", 1)[1].strip() for line in out.splitlines() if line.startswith("package:")}

    def user_apps(self) -> List[str]:
        """Package names of the apps you installed (not the preinstalled ones)."""
        return sorted(self._packages("-3"))

    def packages(self) -> List[Dict[str, object]]:
        """Every app, including preinstalled ones removed for your user:
        [{"package", "system", "installed", "disabled"}]."""
        every, installed = self._packages("-u"), self._packages()
        system, disabled = self._packages("-s -u"), self._packages("-d")
        return [{"package": p, "system": p in system, "installed": p in installed, "disabled": p in disabled}
                for p in sorted(every)]

    def uninstall_for_user(self, package: str) -> str:
        """Remove an app for your user only (``pm uninstall -k --user 0``). A preinstalled app
        stays on the system partition and can be restored; an app you installed yourself is
        removed and has to be installed again from the store."""
        out = self.shell(f"pm uninstall -k --user 0 {_valid(package)}").strip()
        if "Success" not in out:
            raise AdbError(out or "The phone did not confirm the removal.")
        return out

    def restore_for_user(self, package: str) -> str:
        """Bring back a preinstalled app removed with uninstall_for_user."""
        pkg = _valid(package)
        out = self.shell(f"cmd package install-existing {pkg}").strip()
        if "installed" not in out.lower():
            out = self.shell(f"pm install-existing {pkg}").strip()
        if "installed" not in out.lower():
            raise AdbError(out or "The phone did not confirm the restore.")
        return out

    # ----------------------------------------------------------------- backup
    def backup(self, dest: str, sets: List[str], log: Callable[[str], None] = lambda _t: None,
               cancel: Optional[threading.Event] = None) -> Dict[str, object]:
        """Copy the chosen folders to ``dest``, plus a list of installed apps. Read-only for
        the phone. Returns {"copied", "skipped", "files", "bytes", "failed_files", "dest",
        "cancelled"}. Raises AdbError if nothing could be copied."""
        return _Backup(self, Path(dest).expanduser(), sets, log, cancel).run()


class _Backup:
    """One backup run: walks the chosen folders over adb sync and copies every file."""

    def __init__(self, phone: Phone, target: Path, sets: List[str], log: Callable[[str], None],
                 cancel: Optional[threading.Event]):
        unknown = [k for k in sets if k not in BACKUP_SETS]
        if unknown:
            raise AdbError(f"Unknown backup choice: {', '.join(unknown)}")
        self.phone, self.target, self.log, self.cancel = phone, target, log, cancel
        # "everything" already contains the other folders; do not copy them twice.
        self.wanted = ["/sdcard"] if "everything" in sets else [p for k in sets for p in BACKUP_SETS[k][1]]
        self.copied: List[str] = []
        self.skipped: List[str] = []
        self.files = self.bytes = self.failed = 0
        self.cancelled = False

    def _stop(self) -> bool:
        if self.cancel is not None and self.cancel.is_set():
            self.cancelled = True
        return self.cancelled

    def _folder(self, sync: adb_usb.SyncSession, remote: str) -> None:
        try:
            mode, _size, _mtime = sync.stat(remote.rstrip("/") + "/")
        except AdbError:
            mode = 0
        if mode == 0:
            self.skipped.append(remote)  # not on this phone
            return
        self.log(f"Copying {remote} ...")
        root = remote.rstrip("/")
        base = self.target / root.rsplit("/", 1)[-1]
        for path, _mode, _size, mtime in sync.walk(remote):
            if self._stop():
                return
            parts = [p for p in path[len(root) + 1:].split("/") if p not in ("", ".", "..")]
            local = base.joinpath(*parts)
            local.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.bytes += sync.recv(path, local, self.cancel)
                os.utime(local, (mtime, mtime))
                self.files += 1
                if self.files % 50 == 0:
                    self.log(f"{self.files} files, {self.bytes / 1e6:.0f} MB copied ...")
            except AdbError as err:
                if self._stop():
                    return
                self.failed += 1
                if self.failed <= 20:
                    self.log(f"Skipped {path}: {err}")
        self.copied.append(remote)

    def _save_app_list(self) -> None:
        try:
            apps = self.phone.user_apps()
            (self.target / "installed-apps.txt").write_text("\n".join(apps) + "\n", encoding="utf-8")
            self.log(f"Saved the list of {len(apps)} installed apps.")
        except (AdbError, OSError):
            pass

    def run(self) -> Dict[str, object]:
        self.target.mkdir(parents=True, exist_ok=True)
        try:
            sync = self.phone.sync()
            for remote in self.wanted:
                if self._stop():
                    break
                self._folder(sync, remote)
            sync.close()
        except (AdbError, usbio.UsbError) as err:
            raise AdbError(f"Backup stopped: {err}. Files copied so far are in {self.target}") from None
        self._save_app_list()
        self.log(f"{self.files} files, {self.bytes / 1e6:.1f} MB copied"
                 + (f", {self.failed} skipped." if self.failed else "."))
        if not self.copied and not self.cancelled:
            raise AdbError("Nothing was copied. Is the phone unlocked and file access allowed?")
        return {"copied": self.copied, "skipped": self.skipped, "files": self.files, "bytes": self.bytes,
                "failed_files": self.failed, "dest": str(self.target), "cancelled": self.cancelled}


# ------------------------------------------------- short forms of Phone methods
def device_info(serial: Optional[str] = None) -> Dict[str, object]:
    return Phone(serial).info()


def reboot_to_bootloader(serial: Optional[str] = None) -> None:
    Phone(serial).reboot_to_bootloader()


def list_user_apps(serial: Optional[str] = None) -> List[str]:
    return Phone(serial).user_apps()


def list_packages(serial: Optional[str] = None) -> List[Dict[str, object]]:
    return Phone(serial).packages()


def uninstall_for_user(package: str, serial: Optional[str] = None) -> str:
    return Phone(serial).uninstall_for_user(package)


def restore_for_user(package: str, serial: Optional[str] = None) -> str:
    return Phone(serial).restore_for_user(package)


def backup_files(serial: Optional[str], dest: str, sets: List[str],
                 log: Callable[[str], None] = lambda _t: None,
                 cancel: Optional[threading.Event] = None) -> Dict[str, object]:
    return Phone(serial).backup(dest, sets, log, cancel)
