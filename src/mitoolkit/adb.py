"""adb features used before and around the unlock: see the phone, show its details, send
it to fastboot, copy files off it, and manage preinstalled apps.

Everything goes through mitoolkit's own adb client (adb_usb); no adb program is needed.
``Phone`` is the object to use; the module-level functions are short forms of it, kept for
the CLI, API and MCP.

The only commands that change the phone are the reboot and, when you choose them in the
app manager, uninstalling or restoring apps for your user (``pm uninstall --user 0`` /
``cmd package install-existing``). Nothing runs as root, installs software or deletes
your files.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from mitoolkit import adb_core, adb_usb, usbio
from mitoolkit.adb_usb import AdbError  # noqa: F401 (the one adb error type, re-exported)

_debug = logging.getLogger("mitoolkit.adb")     # written only in debug mode

_PROPS = {
    "model": "ro.product.model",
    "codename": "ro.product.device",
    "android": "ro.build.version.release",
    "miui": "ro.miui.ui.version.name",
    "hyperos": "ro.mi.os.version.name",
    "bootloader_locked": "ro.boot.flash.locked",
    "brand": "ro.product.brand",
    "security_patch": "ro.build.version.security_patch",
    "manufacturer": "ro.product.manufacturer",
    "build": "ro.build.display.id",
    "sdk": "ro.build.version.sdk",
    "chipset": "ro.soc.model",
    "platform": "ro.board.platform",
    "region": "ro.miui.region",
    "variant": "ro.product.mod_device",
    "baseband": "gsm.version.baseband",
    "verified_boot": "ro.boot.verifiedbootstate",
    "encryption": "ro.crypto.state",
    "slot": "ro.boot.slot_suffix",
    "serialno": "ro.serialno",                 # the phone's own serial (over Wi-Fi the connection is named by address)
}

# What "Back up files" can copy. Each choice is a list of folders in the phone's shared
# storage. Copying only reads from the phone; nothing on it is changed or deleted.
BACKUP_SETS = {
    "photos": ("Photos and videos", ["/sdcard/DCIM", "/sdcard/Pictures", "/sdcard/Movies"]),
    "documents": ("Documents and downloads", ["/sdcard/Documents", "/sdcard/Download"]),
    "chats": ("Chat app media (WhatsApp, Telegram, and others)",
              ["/sdcard/WhatsApp", "/sdcard/Android/media", "/sdcard/Telegram"]),
    "audio": ("Music and recordings", ["/sdcard/Music", "/sdcard/Recordings", "/sdcard/MIUI/sound_recorder"]),
    "everything": ("Everything in shared storage (can be very large)", ["/sdcard"]),
}

_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


def _check() -> None:
    try:
        usbio.backend()
    except usbio.UsbError as err:
        raise AdbError(str(err)) from None


def valid_package(package: str) -> str:
    """Package names go into a shell command, so only real package names are accepted."""
    if not _PACKAGE.match(package):
        raise AdbError(f"Not a valid package name: {package!r}")
    return package


_valid = valid_package


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
        started = time.monotonic()
        try:
            out = self._dev.shell(command, timeout_ms)
            _debug.debug("shell %s: %s (%d bytes, %.0f ms)", self.serial, command[:100], len(out),
                         1000 * (time.monotonic() - started))
            return out
        except (AdbError, usbio.UsbError) as err:
            _debug.debug("shell %s: %s failed after %.0f ms: %s", self.serial, command[:100],
                         1000 * (time.monotonic() - started), err)
            if self._dev.state == "offline":
                adb_usb.forget(self.serial)
            raise AdbError(str(err)) from None

    def info(self) -> Dict[str, object]:
        """The basic details shown at once: model, versions, build, security patch, chipset,
        memory, storage, screen, kernel, boot and encryption state, battery. Identifiers such
        as the IMEI come only from details.phone_details (the "Show more" button)."""
        props: Dict[str, str] = {}
        for line in self.shell("getprop").splitlines():
            m = re.match(r"\[(.+?)\]: \[(.*)\]", line.strip())
            if m:
                props[m.group(1)] = m.group(2)
        info: Dict[str, object] = {key: (props.get(prop) or None) for key, prop in _PROPS.items()}
        flag = info.pop("bootloader_locked")
        info["bootloader_locked"] = None if flag is None else flag == "1"
        info["serialno"] = info["serialno"] or props.get("ro.boot.serialno") or None
        info.update(self._hardware())
        return info

    def _hardware(self) -> Dict[str, object]:
        """Kernel, RAM, storage, screen and battery in one round trip."""
        marker = "@@mitoolkit@@"
        cmd = "; ".join(f"echo {marker}; {c}" for c in (
            "uname -r", "grep MemTotal /proc/meminfo", "df -k /data | tail -n 1", "wm size",
            "dumpsys battery"))
        try:
            parts = self.shell(cmd).split(marker)[1:]
        except AdbError:
            return {"battery": None}
        parts += [""] * (5 - len(parts))
        kernel, mem, df, screen, battery = (x.strip() for x in parts[:5])
        out: Dict[str, object] = {"kernel": kernel.split()[0] if kernel else None}
        m = re.search(r"(\d+)\s*kB", mem)
        out["ram_gb"] = round(int(m.group(1)) / 1024 / 1024, 1) if m else None
        cols = df.split()
        if len(cols) >= 4 and cols[1].isdigit() and cols[2].isdigit():
            out["storage_total_gb"] = round(int(cols[1]) / 1024 / 1024, 1)
            out["storage_used_gb"] = round(int(cols[2]) / 1024 / 1024, 1)
        m = re.search(r"(?:Override|Physical) size:\s*(\d+x\d+)", screen)
        out["screen"] = m.group(1) if m else None
        levels = dict(re.findall(r"^\s*(level|temperature|health|status):\s*(\d+)", battery, re.M))
        out["battery"] = int(levels["level"]) if "level" in levels else None
        out["battery_temp_c"] = int(levels["temperature"]) / 10 if "temperature" in levels else None
        return out

    def battery(self) -> Optional[int]:
        try:
            for line in self.shell("dumpsys battery").splitlines():
                if line.strip().startswith("level:"):
                    return int(line.split(":", 1)[1])
        except (AdbError, ValueError):
            # the battery level is optional: unreadable means "not known" (None below)
            pass
        return None

    def reboot_to_bootloader(self) -> None:
        """Reboot into fastboot mode. It does not erase anything."""
        if self.wireless:
            raise AdbError("Fastboot mode works over a USB cable only. Connect the phone with a USB cable "
                           "first (a Wi-Fi connection cannot follow it into fastboot).")
        try:
            self._dev.reboot("bootloader")
        except usbio.UsbError as err:
            raise AdbError(str(err)) from None
        finally:
            adb_usb.forget(self.serial)

    def reboot(self, mode: str = "") -> None:
        """Restart the phone: "" (normal), "recovery" or "bootloader". Nothing is erased."""
        if mode not in ("", "recovery", "bootloader"):
            raise AdbError(f"Unknown restart mode: {mode!r}")
        try:
            self._dev.reboot(mode)
        except usbio.UsbError as err:
            raise AdbError(str(err)) from None
        finally:
            adb_usb.forget(self.serial)

    def power_off(self) -> None:
        """Shut the phone down (it stays off until you press the power button)."""
        try:
            self.shell("reboot -p", 5000)
        except AdbError:
            pass  # the phone goes away before it can answer
        finally:
            adb_usb.forget(self.serial)

    def logcat(self, lines: int = 1500) -> str:
        """The phone's recent system log (logcat -d: it is dumped and not followed), newest last."""
        count = max(50, min(int(lines), 20000))
        return self.shell(f"logcat -d -v threadtime -t {count}", 60000)

    @property
    def via(self) -> str:
        """How mitoolkit reaches the phone: "adb server" (Google's) or "usb" (built in)."""
        from mitoolkit.adb_server import ServerDevice
        return "adb server" if isinstance(self._dev, ServerDevice) else "usb"

    @property
    def wireless(self) -> bool:
        """True when the phone is reached over Wi-Fi (its serial is an address like 192.168.1.5:5555)."""
        return adb_core.is_wireless(self.serial)

    def wifi_address(self) -> Optional[str]:
        """The phone's address on Wi-Fi (for example 192.168.1.5), or None when it is not on Wi-Fi."""
        for command in ("ip -f inet addr show wlan0", "ip route get 1.1.1.1"):
            try:
                out = self.shell(command, 8000)
            except AdbError:
                continue
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out) or re.search(r"src (\d+\.\d+\.\d+\.\d+)", out)
            if m:
                return m.group(1)
        return None

    def enable_wireless(self, port: int = 5555) -> str:
        """Let this computer reach the phone over Wi-Fi: switch the phone's adb to listen on a network
        port and connect to it. Returns "address:port". The phone goes back to USB-only when it restarts."""
        from mitoolkit import adb_server
        address = self.wifi_address()
        if not address:
            raise AdbError("The phone is not on Wi-Fi. Connect it to the same network as this computer.")
        if not hasattr(self._dev, "tcpip"):
            raise AdbError("This connection cannot switch the phone to Wi-Fi.")
        if not adb_server.start():
            raise AdbError(adb_server.NEEDS_GOOGLE_ADB)
        try:
            self._dev.tcpip(port)
        except usbio.UsbError as err:
            raise AdbError(str(err)) from None
        import time
        last = ""
        for _ in range(6):                               # the phone restarts its adb daemon first
            time.sleep(1.0)
            try:
                return adb_server.connect(f"{address}:{port}")
            except AdbError as err:
                last = str(err)
        raise AdbError(last or "The phone did not accept the Wi-Fi connection.")

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
        self.files = self.bytes = self.failed = self.unchanged = 0
        self.failures: List[str] = []
        self.in_a_row = 0                  # files that failed one after another
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
        self.log(f"Copying {remote}")
        root = remote.rstrip("/")
        base = self.target / root.rsplit("/", 1)[-1]
        for path, _mode, size, mtime in sync.walk(remote):
            if self._stop():
                return
            parts = [p for p in path[len(root) + 1:].split("/") if p not in ("", ".", "..")]
            local = base.joinpath(*parts)
            local.parent.mkdir(parents=True, exist_ok=True)
            if self._unchanged(local, size, mtime):          # copied by an earlier run: a backup can be resumed
                self.unchanged += 1
                continue
            try:
                self.bytes += self._copy(sync, path, local, size, mtime)
                self.files += 1
                self.in_a_row = 0
                if self.files % 50 == 0:
                    self.log(f"{self.files} files, {self.bytes / 1e6:.0f} MB copied")
            except AdbError as err:
                if self._stop():
                    return
                self.failed += 1
                self.in_a_row += 1
                self.failures.append(f"{path}: {err}")
                if self.failed <= 20:
                    self.log(f"Skipped {path}: {err}")
                if self.in_a_row >= 6:                       # unplugged or locked: stop instead of failing every file
                    raise AdbError("The phone stopped answering")
        self.copied.append(remote)

    @staticmethod
    def _unchanged(local: Path, size: int, mtime: int) -> bool:
        """Already here with the same size and modification time (the copy keeps the phone's time)."""
        try:
            st = local.stat()
        except OSError:
            return False
        return st.st_size == size and abs(st.st_mtime - mtime) <= 2

    def _copy(self, sync: adb_usb.SyncSession, path: str, local: Path, size: int, mtime: int) -> int:
        """One file, safely: written to a temporary name and moved into place only when complete, checked
        against the size the phone reported, and tried up to three times (a busy phone or a dropped
        transfer is usually fine the second time)."""
        last: Optional[AdbError] = None
        for attempt in range(3):
            try:
                written = sync.recv(path, local, self.cancel)
                if written != size:
                    local.unlink(missing_ok=True)
                    raise AdbError(f"received {written} of {size} bytes")
                os.utime(local, (mtime, mtime))
                return written
            except AdbError as err:
                last = err
                if self._stop():
                    raise
                if attempt < 2:
                    time.sleep(0.5)
        raise last or AdbError("The file could not be copied.")

    def _save_app_list(self) -> None:
        try:
            apps = self.phone.user_apps()
            (self.target / "installed-apps.txt").write_text("\n".join(apps) + "\n", encoding="utf-8")
            self.log(f"Saved the list of {len(apps)} installed apps.")
        except (AdbError, OSError):
            # the app list is a bonus next to the files, which are already copied
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
        self._save_report()
        self.log(f"{self.files} files, {self.bytes / 1e6:.1f} MB copied"
                 + (f", {self.unchanged} already there" if self.unchanged else "")
                 + (f", {self.failed} could not be copied." if self.failed else "."))
        if not self.copied and not self.cancelled:
            raise AdbError("Nothing was copied. Is the phone unlocked and file access allowed?")
        return {"copied": self.copied, "skipped": self.skipped, "files": self.files, "bytes": self.bytes,
                "unchanged": self.unchanged, "failed_files": self.failed, "dest": str(self.target),
                "cancelled": self.cancelled}

    def _save_report(self) -> None:
        """Files that could not be copied, listed in the backup folder, so nothing fails silently."""
        report = self.target / "backup-problems.txt"
        try:
            if self.failures:
                report.write_text("Files that could not be copied (run the backup again to retry them):\n\n"
                                  + "\n".join(self.failures) + "\n", encoding="utf-8")
            else:
                report.unlink(missing_ok=True)
        except OSError:
            # the problems list is a convenience: a read-only folder must not fail the backup
            pass


# ------------------------------------------------- short forms of Phone methods
def device_info(serial: Optional[str] = None) -> Dict[str, object]:
    return Phone(serial).info()


def reboot_to_bootloader(serial: Optional[str] = None) -> None:
    Phone(serial).reboot_to_bootloader()


def reboot(mode: str = "", serial: Optional[str] = None) -> None:
    Phone(serial).reboot(mode)


def power_off(serial: Optional[str] = None) -> None:
    Phone(serial).power_off()


def logcat(serial: Optional[str] = None, lines: int = 1500) -> str:
    return Phone(serial).logcat(lines)


def more_details(serial: Optional[str] = None):
    """All the extra details (identifiers, software, hardware, network, battery) in sections."""
    from mitoolkit import details
    return details.phone_details(Phone(serial))


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
