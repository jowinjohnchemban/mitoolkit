"""
Help with the USB driver Windows needs before adb or fastboot can use a phone.

mitoolkit does not download or install drivers. It explains the steps and opens Google's
official download page in your browser; you install the driver with Windows' own Device
Manager. macOS and Linux need no driver.
"""
from __future__ import annotations

import os
import sys
import webbrowser

DOWNLOAD_PAGE = "https://developer.android.com/studio/run/win-usb"

STEPS = [
    "Open Google's download page and download the Google USB Driver ZIP. Unzip it.",
    ("Connect the phone. In Device Manager it shows with a yellow mark, often under "
     "Other devices (it may be called Android, Fastboot or your phone's name)."),
    ("Right-click it > Update driver > Browse my computer for drivers > Let me pick from a "
     "list > Have Disk..., and choose android_winusb.inf in the unzipped folder."),
    ("Pick Android Bootloader Interface when the phone is in fastboot mode, or Android ADB "
     "Interface when it is running Android, and accept the warning."),
    "Unplug the phone, plug it back in, and click Rescan in mitoolkit.",
]

NOTE = ("Google's driver does not list Xiaomi's USB IDs, which is why Windows does not pick it "
        "by itself and you choose it with Have Disk. The steps are Windows' own; nothing is "
        "installed by mitoolkit.")


def supported() -> bool:
    """Only Windows needs a driver."""
    return sys.platform == "win32"


def open_download_page() -> None:
    webbrowser.open(DOWNLOAD_PAGE)


def open_device_manager() -> None:
    """Through the shell, which handles Windows' administrator prompt."""
    os.startfile("devmgmt.msc")  # type: ignore[attr-defined]  # Windows only


def instructions() -> str:
    """The steps as plain text, for the command line."""
    lines = [f"{i}. {step}" for i, step in enumerate(STEPS, 1)]
    return "\n".join(lines + ["", NOTE, "", f"Download page: {DOWNLOAD_PAGE}"])
