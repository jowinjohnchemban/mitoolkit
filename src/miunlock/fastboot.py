"""
Talking to a phone in fastboot mode.

On Windows, macOS and Linux this is miunlock's own USB client (fastboot_usb); no fastboot
program is downloaded or needed. On Android (Termux) an app cannot open USB devices
directly, so there the termux fastboot command is used, set up by termux.py.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from miunlock import fastboot_usb, usbio
from miunlock.system import IS_TERMUX, NO_WINDOW

_VARS = {
    "product": "product",
    "unlocked": "unlocked",
    "bootloader_version": "version-bootloader",
    "slot": "current-slot",
    "serial": "serialno",
}


class FastbootError(Exception):
    """str(e) is human-readable."""


_termux_cmd: Optional[str] = None


def _termux() -> str:
    global _termux_cmd
    if _termux_cmd is None:
        from miunlock.termux import setup_fastboot
        _termux_cmd = setup_fastboot()
    return _termux_cmd


def ready() -> str:
    """Check fastboot can be used here. Returns a short description of how."""
    if IS_TERMUX:
        _termux()
        return "termux fastboot"
    try:
        usbio.backend()
    except usbio.UsbError as err:
        raise FastbootError(str(err)) from None
    return "built-in USB fastboot"


def devices() -> List[Dict[str, object]]:
    """[{"serial", "accessible"}] for phones in fastboot mode. Read-only."""
    if IS_TERMUX:
        out = subprocess.run([_termux(), "devices"], capture_output=True, text=True, timeout=15).stdout
        return [{"serial": ln.split()[0], "accessible": True}
                for ln in out.splitlines() if len(ln.split()) >= 2 and ln.split()[1] == "fastboot"]
    try:
        return fastboot_usb.devices()
    except usbio.UsbError as err:
        raise FastbootError(str(err)) from None


def wait_for_device(say: bool = True, timeout: Optional[float] = None) -> None:
    """Block until a usable phone is in fastboot mode (Ctrl+C stops it)."""
    start, told = time.monotonic(), False
    while True:
        found = devices()
        if any(d["accessible"] for d in found):
            return
        if found and not told:
            print("A phone in fastboot mode was found but cannot be opened. " + usbio.no_access_advice())
            told = True
        elif say and not told:
            print("Waiting for a phone in fastboot mode... (Ctrl+C to stop)")
            told = True
        if timeout is not None and time.monotonic() - start > timeout:
            raise FastbootError("No phone in fastboot mode is connected.")
        time.sleep(1)


def _open(serial: Optional[str] = None) -> fastboot_usb.FastbootDevice:
    try:
        return fastboot_usb.FastbootDevice(serial)
    except fastboot_usb.FastbootError as err:
        raise FastbootError(str(err)) from None


def info(serial: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Codename, bootloader unlocked yes/no, bootloader version, active slot, serial. Read-only."""
    if IS_TERMUX:
        from miunlock.commands import CheckB
        return {k: (v if isinstance(v, str) else None)
                for k, v in ((k, CheckB(_termux(), var, "getvar", var)) for k, var in _VARS.items())}
    with _open(serial) as fb:
        try:
            return {key: fb.getvar(var) for key, var in _VARS.items()}
        except fastboot_usb.FastbootError as err:
            raise FastbootError(str(err)) from None


def get_product(wait: bool = True) -> str:
    """The phone's codename (getvar product)."""
    if IS_TERMUX:
        from miunlock.commands import get_product as termux_product
        product = termux_product(_termux())
        if isinstance(product, dict):
            raise FastbootError(product["error"])
        return product
    if wait:
        wait_for_device()
    with _open() as fb:
        try:
            product = fb.getvar("product")
        except fastboot_usb.FastbootError as err:
            raise FastbootError(str(err)) from None
    if not product:
        raise FastbootError("The phone did not report its codename.")
    return product


def get_token() -> str:
    """The device token Xiaomi's server needs (oem get_token, or getvar token)."""
    if IS_TERMUX:
        from miunlock.commands import get_device_token
        token = get_device_token(_termux())
        if isinstance(token, dict):
            raise FastbootError(token["error"])
        return token
    with _open() as fb:
        try:
            try:
                _reply, lines = fb.oem("get_token", 20000)
                token = fastboot_usb.parse_token(lines)
            except fastboot_usb.Refused:
                token = None
            token = token or fb.getvar("token")
        except fastboot_usb.FastbootError as err:
            raise FastbootError(str(err)) from None
    if not token:
        raise FastbootError("The phone did not give a device token.")
    return token


def stage_and_unlock(encrypt_data: bytes) -> None:
    """Send Xiaomi's signed unlock data and run oem unlock. ERASES THE PHONE."""
    if IS_TERMUX:
        fd, name = tempfile.mkstemp(prefix="miunlock-", suffix=".encryptData")
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(encrypt_data)
            for args in (["stage", str(path)], ["oem", "unlock"]):
                done = subprocess.run([_termux(), *args], capture_output=True, text=True)
                if done.returncode != 0:
                    raise FastbootError((done.stderr or done.stdout).strip() or "fastboot failed")
        finally:
            if path.exists():
                path.unlink()
        return
    with _open() as fb:
        try:
            fb.download(encrypt_data)
            fb.oem("unlock", 120000)
        except fastboot_usb.FastbootError as err:
            raise FastbootError(str(err)) from None


def reboot(serial: Optional[str] = None) -> None:
    if IS_TERMUX:
        subprocess.run([_termux(), "reboot"], capture_output=True, timeout=15, creationflags=NO_WINDOW)
        return
    with _open(serial) as fb:
        fb.reboot()
