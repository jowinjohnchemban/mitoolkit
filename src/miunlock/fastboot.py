"""
Talking to a phone in fastboot mode.

``Backend`` is what the rest of miunlock needs from fastboot; ``UsbBackend`` implements it
with miunlock's own USB client (fastboot_usb), so no fastboot program is needed. Another
transport (for example an Android app's USB host API) would be a new Backend subclass.

The module-level functions use the backend for this system.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from miunlock import fastboot_usb, usbio
from miunlock.fastboot_usb import FastbootError  # noqa: F401 (the one fastboot error type, re-exported)

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


_backend: Optional[Backend] = None


def backend() -> Backend:
    """The backend for this system (created once)."""
    global _backend
    if _backend is None:
        _backend = UsbBackend()
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


def reboot(serial: Optional[str] = None) -> None:
    backend().reboot(serial)
