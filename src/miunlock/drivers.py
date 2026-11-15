"""
Google's official USB driver for Windows, so adb and fastboot can see the phone.

Only needed on Windows, and only when a phone is not detected. Nothing is installed
unless the user asks: the driver is downloaded over HTTPS from dl.google.com, its
SHA-256 is logged, and installing goes through Windows' own ``pnputil`` after a normal
administrator (UAC) prompt. Windows itself checks the driver's signature.

Google's .inf does not list Xiaomi's USB IDs, so Windows may not pick the driver for a
Xiaomi phone by itself. Once it is in the driver store it can be chosen by hand in Device
Manager (see MANUAL_STEPS). This driver is the only thing miunlock downloads from
Google: adb and fastboot are built in (adb_usb.py, fastboot_usb.py).
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from miunlock.system import NO_WINDOW

USB_DRIVER_URL = "https://dl.google.com/android/repository/usb_driver_r13-windows.zip"
DRIVER_DIR = Path.home() / "miunlock-drivers"
INF_NAME = "android_winusb.inf"


MANUAL_STEPS = (
    "If the phone still shows with a yellow mark in Device Manager: right-click it > Update driver > "
    "Browse my computer > Let me pick > Android Device > Android Bootloader Interface "
    "(fastboot) or Android ADB Interface (phone running Android)."
)


class DriverError(Exception):
    """A driver step failed. str(e) is human-readable."""


def supported() -> bool:
    return sys.platform == "win32"


def download_usb_driver(log: Callable[[str], None] = lambda _t: None) -> Path:
    """Download and unpack Google's USB driver. Returns the folder holding the .inf."""
    if not supported():
        raise DriverError("The USB driver is only needed on Windows.")
    DRIVER_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DRIVER_DIR / "usb_driver.zip"
    log(f"Downloading Google's USB driver from {USB_DRIVER_URL}")
    try:
        with urllib.request.urlopen(USB_DRIVER_URL, timeout=60) as resp:  # https only; fixed URL
            data = resp.read()
    except OSError as err:
        raise DriverError(f"Could not download the driver ({type(err).__name__}). Check your internet connection.") from None
    zip_path.write_bytes(data)
    log(f"Downloaded {len(data) // 1024} KiB, SHA-256 {hashlib.sha256(data).hexdigest()}")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(DRIVER_DIR)  # extractall refuses paths that escape the folder
    except zipfile.BadZipFile:
        raise DriverError("The downloaded driver file is damaged. Try again.") from None
    finally:
        zip_path.unlink(missing_ok=True)
    found = next(DRIVER_DIR.rglob(INF_NAME), None)
    if found is None:
        raise DriverError(f"{INF_NAME} was not in the download.")
    return found.parent


def install_usb_driver(log: Callable[[str], None] = lambda _t: None) -> str:
    """Download the driver and install it with pnputil. Windows shows an administrator
    prompt; if it is declined nothing is installed. Returns a short result message."""
    folder = download_usb_driver(log)
    inf = folder / INF_NAME
    log("Installing the driver. Accept the Windows administrator prompt...")
    command = (
        "$p = Start-Process -FilePath pnputil.exe -ArgumentList "
        f"'/add-driver','{inf}','/install' -Verb RunAs -Wait -PassThru -WindowStyle Hidden; "
        "exit $p.ExitCode"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise DriverError("The install did not finish in time.") from None
    except OSError as err:
        raise DriverError(f"Could not start the installer ({type(err).__name__}).") from None
    # pnputil: 0 = installed, 3010 = installed but a restart is needed
    if done.returncode == 0:
        return "USB driver installed. Unplug and reconnect the phone. " + MANUAL_STEPS
    if done.returncode == 3010:
        return "USB driver installed. Restart the computer, then reconnect the phone. " + MANUAL_STEPS
    if "canceled" in (done.stderr or "").lower() or "cancelled" in (done.stderr or "").lower():
        raise DriverError("The administrator prompt was declined, so nothing was installed.")
    raise DriverError(f"Windows could not install the driver (code {done.returncode}). "
                      f"You can install it by hand: right-click {INF_NAME} in {folder} and choose Install.")
