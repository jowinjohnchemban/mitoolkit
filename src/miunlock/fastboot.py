"""
Talking to a phone in fastboot mode.

Two interchangeable backends implement the same interface (``Backend``):

- ``UsbBackend`` on Windows, macOS and Linux: miunlock's own USB client (fastboot_usb).
  No fastboot program is downloaded or needed.
- ``TermuxBackend`` on Android (Termux): an Android app cannot open USB devices directly,
  so the termux fastboot command is used, set up by termux.py.

The module-level functions use whichever backend fits this system.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from miunlock import fastboot_usb, usbio
from miunlock.fastboot_usb import FastbootError  # noqa: F401 (the one fastboot error type, re-exported)
from miunlock.system import IS_TERMUX, NO_WINDOW

# Read-only variables shown as device details.
INFO_VARS = {
    "product": "product",
    "unlocked": "unlocked",
    "bootloader_version": "version-bootloader",
    "slot": "current-slot",
    "serial": "serialno",
}


class Backend(ABC):
    """What miunlock needs from fastboot."""

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
    def reboot(self, serial: Optional[str] = None) -> None:
        """Restart the phone normally."""

    def info(self, serial: Optional[str] = None) -> Dict[str, Optional[str]]:
        return {key: self.getvar(var, serial) for key, var in INFO_VARS.items()}


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

    def reboot(self, serial: Optional[str] = None) -> None:
        with self._open(serial) as fb:
            fb.reboot()


class TermuxBackend(Backend):
    name = "termux fastboot"

    def __init__(self):
        self._cmd: Optional[str] = None

    @property
    def cmd(self) -> str:
        if self._cmd is None:
            from miunlock.termux import setup_fastboot
            self._cmd = setup_fastboot()
        return self._cmd

    def _run(self, *args: str, timeout: Optional[int] = 60) -> subprocess.CompletedProcess:
        return subprocess.run([self.cmd, *args], capture_output=True, text=True, timeout=timeout)

    def ready(self) -> None:
        _ = self.cmd

    def devices(self) -> List[Dict[str, object]]:
        out = self._run("devices", timeout=15).stdout
        return [{"serial": ln.split()[0], "accessible": True}
                for ln in out.splitlines() if len(ln.split()) >= 2 and ln.split()[1] == "fastboot"]

    def getvar(self, name: str, serial: Optional[str] = None) -> Optional[str]:
        from miunlock.commands import CheckB
        value = CheckB(self.cmd, name, "getvar", name)
        return value if isinstance(value, str) and value else None

    def token(self) -> Optional[str]:
        from miunlock.commands import get_device_token
        token = get_device_token(self.cmd)
        if isinstance(token, dict):
            raise FastbootError(token["error"])
        return token

    def stage_and_unlock(self, data: bytes) -> None:
        # The fastboot command needs a file: private, unpredictable name, deleted at once.
        fd, name = tempfile.mkstemp(prefix="miunlock-", suffix=".encryptData")
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            for args in (["stage", str(path)], ["oem", "unlock"]):
                done = self._run(*args, timeout=None)
                if done.returncode != 0:
                    raise FastbootError((done.stderr or done.stdout).strip() or "fastboot failed")
        finally:
            if path.exists():
                path.unlink()

    def reboot(self, serial: Optional[str] = None) -> None:
        subprocess.run([self.cmd, "reboot"], capture_output=True, timeout=15, creationflags=NO_WINDOW)


_backend: Optional[Backend] = None


def backend() -> Backend:
    """The backend for this system (created once)."""
    global _backend
    if _backend is None:
        _backend = TermuxBackend() if IS_TERMUX else UsbBackend()
    return _backend


# ------------------------------------------------------------ module functions
def ready() -> str:
    """Check fastboot can be used here. Returns a short description of how."""
    backend().ready()
    return backend().name


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
            print("A phone in fastboot mode was found but cannot be opened. " + usbio.no_access_advice()
                  if found else "Waiting for a phone in fastboot mode... (Ctrl+C to stop)")
            told = True
        if timeout is not None and time.monotonic() - start > timeout:
            raise FastbootError("No phone in fastboot mode is connected.")
        time.sleep(1)


def get_product(wait: bool = True) -> str:
    """The phone's codename (getvar product)."""
    if wait and not IS_TERMUX:  # termux fastboot waits by itself
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


def reboot(serial: Optional[str] = None) -> None:
    backend().reboot(serial)
