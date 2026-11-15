"""
Talking to a phone in fastboot mode.

``Backend`` is what the rest of mitoolkit needs from fastboot. Implementations:

- ``UsbBackend``: mitoolkit's own USB client (fastboot_usb). No program needed.
- ``ExeBackend``: Google's ``fastboot`` program, only if it is already installed.
- ``AutoBackend`` (the default): uses the built-in client, and falls back to Google's
  fastboot for a phone the built-in client cannot open, when that program is present.

Another transport (for example an Android app's USB host API) would be a new subclass.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Set

from mitoolkit import fastboot_usb, platform_tools, usbio
from mitoolkit.system import NO_WINDOW
from mitoolkit.fastboot_usb import FastbootError  # noqa: F401 (the one fastboot error type, re-exported)

# Read-only variables shown as device details.
INFO_VARS = {
    "product": "product",
    "unlocked": "unlocked",
    "bootloader_version": "version-bootloader",
    "baseband": "version-baseband",
    "slot": "current-slot",
    "serial": "serialno",
    "secure": "secure",
    "variant": "variant",
    "hw_revision": "hw-revision",
    "anti_rollback": "anti",              # Xiaomi's anti-rollback index
    "userspace": "is-userspace",          # "yes" in fastbootd (not the bootloader)
    "battery_voltage": "battery-voltage",
}


class Backend(ABC):
    """What mitoolkit needs from fastboot."""

    name = "fastboot"

    @abstractmethod
    def ready(self) -> None:
        """Raise FastbootError if this backend cannot work here."""

    @abstractmethod
    def devices(self) -> List[Dict[str, object]]:
        """[{"serial", "accessible"}] for phones in fastboot mode."""

    @abstractmethod
    def getvar(self, name: str, serial: Optional[str] = None) -> Optional[str]:
        """A variable's value, or None if the phone does not have it."""

    @abstractmethod
    def token(self) -> Optional[str]:
        """The device token (oem get_token), or None."""

    @abstractmethod
    def stage_and_unlock(self, data: bytes) -> None:
        """Upload Xiaomi's signed data and run oem unlock. ERASES THE PHONE."""

    @abstractmethod
    def reboot(self, serial: Optional[str] = None, mode: str = "") -> None:
        """Restart the phone: normally (mode ""), or into recovery mode ("recovery")."""

    def info(self, serial: Optional[str] = None) -> Dict[str, Optional[str]]:
        return {key: self.getvar(var, serial) for key, var in INFO_VARS.items()}

    def all_vars(self, serial: Optional[str] = None) -> List[str]:
        """Every variable the bootloader reports, as raw "name: value" lines."""
        return []


class UsbBackend(Backend):
    name = "built-in USB fastboot"

    def ready(self) -> None:
        try:
            usbio.backend()
        except usbio.UsbError as err:
            raise FastbootError(str(err)) from None

    def _open(self, serial: Optional[str] = None) -> fastboot_usb.FastbootDevice:
        return fastboot_usb.FastbootDevice(serial)

    def devices(self) -> List[Dict[str, object]]:
        try:
            return fastboot_usb.devices()
        except usbio.UsbError as err:
            raise FastbootError(str(err)) from None

    def getvar(self, name: str, serial: Optional[str] = None) -> Optional[str]:
        with self._open(serial) as fb:
            return fb.getvar(name)

    def all_vars(self, serial: Optional[str] = None) -> List[str]:
        with self._open(serial) as fb:
            return fb.all_vars()

    def info(self, serial: Optional[str] = None) -> Dict[str, Optional[str]]:
        with self._open(serial) as fb:  # one USB session for all variables
            return {key: fb.getvar(var) for key, var in INFO_VARS.items()}

    def token(self) -> Optional[str]:
        with self._open() as fb:
            try:
                _reply, lines = fb.oem("get_token", 20000)
                token = fastboot_usb.parse_token(lines)
            except fastboot_usb.Refused:
                token = None
            return token or fb.getvar("token")

    def stage_and_unlock(self, data: bytes) -> None:
        with self._open() as fb:
            fb.download(data)
            fb.oem("unlock", 120000)

    def reboot(self, serial: Optional[str] = None, mode: str = "") -> None:
        with self._open(serial) as fb:
            fb.reboot(mode)


_children: Set["subprocess.Popen"] = set()      # Google's fastboot programs MiToolkit is running right now
_children_lock = threading.Lock()


def _run_tracked(cmd: List[str], timeout: Optional[float]) -> "subprocess.CompletedProcess":
    """Like subprocess.run for a short program, but the process is remembered while it runs, so closing MiToolkit
    in the middle of a call can stop it instead of leaving a fastboot holding the phone."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=NO_WINDOW)
    with _children_lock:
        _children.add(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    finally:
        with _children_lock:
            _children.discard(proc)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def terminate_children() -> int:
    """Stop the Google fastboot programs MiToolkit started that are still running. Returns how many."""
    with _children_lock:
        running = [p for p in _children if p.poll() is None]
    for proc in running:
        try:
            proc.kill()
        except OSError:
            # it ended by itself a moment ago
            pass
    return len(running)


class ExeBackend(Backend):
    """Google's fastboot program (already installed; never downloaded)."""

    name = "Google's fastboot"

    def __init__(self, path: str):
        self.path = path

    def _run(self, *args: str, serial: Optional[str] = None, timeout: Optional[int] = 30) -> str:
        cmd = [self.path] + (["-s", serial] if serial else []) + list(args)
        try:
            done = _run_tracked(cmd, timeout)
        except subprocess.TimeoutExpired:
            raise FastbootError("Google's fastboot did not answer in time.") from None
        except OSError as err:
            raise FastbootError(f"Could not run Google's fastboot ({err}).") from None
        out = (done.stderr or "") + (done.stdout or "")  # fastboot reports on stderr
        if done.returncode != 0:
            raise fastboot_usb.Refused(out.strip().splitlines()[-1] if out.strip() else "fastboot failed")
        return out

    def ready(self) -> None:
        if not Path(self.path).is_file():
            raise FastbootError("Google's fastboot is not installed.")

    def devices(self) -> List[Dict[str, object]]:
        out = _run_tracked([self.path, "devices"], 10).stdout
        return [{"serial": ln.split()[0], "accessible": True, "via": self.name}
                for ln in out.splitlines() if len(ln.split()) >= 2 and ln.split()[1] == "fastboot"]

    def getvar(self, name: str, serial: Optional[str] = None) -> Optional[str]:
        try:
            out = self._run("getvar", name, serial=serial, timeout=15)
        except fastboot_usb.Refused:
            return None
        for line in out.splitlines():
            if line.startswith(name + ":"):
                return line.split(":", 1)[1].strip() or None
        return None

    def all_vars(self, serial: Optional[str] = None) -> List[str]:
        try:
            return self._run("getvar", "all", serial=serial, timeout=30).splitlines()
        except fastboot_usb.Refused:
            return []

    def token(self) -> Optional[str]:
        try:
            out = self._run("oem", "get_token", timeout=30)
            token = fastboot_usb.parse_token([ln.replace("(bootloader)", "").strip() for ln in out.splitlines()])
        except fastboot_usb.Refused:
            token = None
        return token or self.getvar("token")

    def stage_and_unlock(self, data: bytes) -> None:
        # The program needs a file: private, unpredictably named, deleted at once.
        fd, name = tempfile.mkstemp(prefix="mitoolkit-", suffix=".encryptData")
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            self._run("stage", str(path), timeout=120)
            self._run("oem", "unlock", timeout=180)
        finally:
            if path.exists():
                path.unlink()

    def reboot(self, serial: Optional[str] = None, mode: str = "") -> None:
        try:
            self._run("reboot", *([mode] if mode else []), serial=serial, timeout=15)
        except FastbootError:
            # the phone leaves fastboot before the program can answer
            pass


class AutoBackend(Backend):
    """The best way for each phone: the built-in client, or Google's fastboot (if installed)
    for a phone the built-in client cannot open."""

    def __init__(self):
        self.usb = UsbBackend()
        self._exe: Optional[ExeBackend] = None
        self._exe_checked = False

    @property
    def exe(self) -> Optional[ExeBackend]:
        if not self._exe_checked:
            path = platform_tools.find("fastboot")
            self._exe = ExeBackend(path) if path else None
            self._exe_checked = True
        return self._exe

    @property
    def name(self) -> str:
        return self.usb.name + (" (Google's fastboot as a fallback)" if self.exe else "")

    def ready(self) -> None:
        try:
            self.usb.ready()
        except FastbootError:
            if self.exe is None:
                raise

    def devices(self) -> List[Dict[str, object]]:
        try:
            found = self.usb.devices()
        except FastbootError:
            found = []
        if all(d["accessible"] for d in found) or self.exe is None:
            return found
        via_exe = self.exe.devices()
        if not via_exe:
            return found
        return [d for d in found if d["accessible"]] + via_exe

    def pick(self, serial: Optional[str] = None) -> Backend:
        """Built-in client if it can open the phone, else Google's fastboot if that sees it."""
        try:
            usable = [d for d in self.usb.devices() if d["accessible"]]
        except FastbootError:
            usable = []
        if usable and (serial is None or any(d["serial"] == serial for d in usable)):
            return self.usb
        if self.exe is not None and self.exe.devices():
            return self.exe
        return self.usb

    def getvar(self, name: str, serial: Optional[str] = None) -> Optional[str]:
        return self.pick(serial).getvar(name, serial)

    def info(self, serial: Optional[str] = None) -> Dict[str, Optional[str]]:
        chosen = self.pick(serial)
        data = chosen.info(serial)
        data["via"] = chosen.name
        return data

    def all_vars(self, serial: Optional[str] = None) -> List[str]:
        return self.pick(serial).all_vars(serial)

    def token(self) -> Optional[str]:
        return self.pick().token()

    def stage_and_unlock(self, data: bytes) -> None:
        self.pick().stage_and_unlock(data)

    def reboot(self, serial: Optional[str] = None, mode: str = "") -> None:
        self.pick(serial).reboot(serial, mode)


_backend: Optional[Backend] = None


def backend() -> Backend:
    """The backend for this system (created once)."""
    global _backend
    if _backend is None:
        _backend = AutoBackend()
    return _backend


# ------------------------------------------------------------ module functions
def ready() -> str:
    """Check fastboot can be used here. Returns a short description of how."""
    backend().ready()
    return backend().name


def all_vars(serial: Optional[str] = None) -> List[str]:
    """Every variable the bootloader reports, as raw lines (see details.parse_fastboot_vars)."""
    return backend().all_vars(serial)


def devices() -> List[Dict[str, object]]:
    return backend().devices()


def info(serial: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Codename, bootloader unlocked yes/no, bootloader version, active slot, serial. Read-only."""
    return backend().info(serial)


def wait_for_device(say: bool = True, timeout: Optional[float] = None) -> None:
    """Block until a usable phone is in fastboot mode (Ctrl+C stops it)."""
    start, told = time.monotonic(), False
    while True:
        found = devices()
        if any(d["accessible"] for d in found):
            return
        if not told and (found or say):
            print("A phone in fastboot mode was found but cannot be opened. "
                  + usbio.no_access_advice(found[0].get("reason") or usbio.BUSY)
                  if found else "Waiting for a phone in fastboot mode... (Ctrl+C to stop)")
            told = True
        if timeout is not None and time.monotonic() - start > timeout:
            raise FastbootError("No phone in fastboot mode is connected.")
        time.sleep(1)


def get_product(wait: bool = True) -> str:
    """The phone's codename (getvar product)."""
    if wait:
        wait_for_device()
    product = backend().getvar("product")
    if not product:
        raise FastbootError("The phone did not report its codename.")
    return product


def get_token() -> str:
    """The device token Xiaomi's server needs (oem get_token, or getvar token)."""
    token = backend().token()
    if not token:
        raise FastbootError("The phone did not give a device token.")
    return token


def stage_and_unlock(encrypt_data: bytes) -> None:
    """Send Xiaomi's signed unlock data and run oem unlock. ERASES THE PHONE."""
    backend().stage_and_unlock(encrypt_data)


def reboot(serial: Optional[str] = None, mode: str = "") -> None:
    """Leave fastboot: into Android (mode "") or recovery mode ("recovery"). Erases nothing."""
    if mode not in ("", "recovery"):
        raise FastbootError(f"Unknown restart mode: {mode!r}")
    backend().reboot(serial, mode)
