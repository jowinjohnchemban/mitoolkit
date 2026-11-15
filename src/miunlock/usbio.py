"""
USB access for miunlock's own adb and fastboot clients (pyusb + libusb).

No adb or fastboot program is needed. On Windows the phone needs a WinUSB driver, such
as Google's USB driver (see drivers.py). On Linux your user needs permission for the
device, usually through a udev rule for Android phones.
"""
from __future__ import annotations

import sys
from typing import Any, List, Optional, Tuple

from miunlock.errors import MiunlockError


class UsbError(MiunlockError):
    """A USB step failed. str(e) is human-readable."""


class UsbUnavailable(UsbError):
    """pyusb or libusb is missing."""


class UsbTimeout(UsbError):
    """The phone did not answer in time."""


_backend: Any = None


def backend():
    """The libusb backend, from the libusb-package wheel if present, else the system libusb."""
    global _backend
    if _backend is not None:
        return _backend
    from miunlock.system import IS_ANDROID
    if IS_ANDROID:
        raise UsbUnavailable("miunlock runs on a computer (Windows, macOS or Linux). Running it on an "
                             "Android phone is not supported: connect the phone to a computer instead.")
    try:
        import usb.core  # noqa: F401
        import usb.backend.libusb1 as libusb1
    except ImportError:
        raise UsbUnavailable("pyusb is not installed. Run: pip install pyusb libusb-package") from None
    found = None
    try:
        import libusb_package
        found = libusb_package.get_libusb1_backend()
    except Exception:  # not installed, or no build for this system
        found = None
    if found is None:
        found = libusb1.get_backend()
    if found is None:
        raise UsbUnavailable("libusb was not found. Install it (Linux: sudo apt install libusb-1.0-0; "
                             "macOS: brew install libusb) or run: pip install libusb-package")
    _backend = found
    return found


def available() -> bool:
    try:
        backend()
        return True
    except UsbUnavailable:
        return False


# Programs that open Android phones over USB. Only one program can use a phone at a time,
# so while one of these runs, miunlock gets "access denied".
_BLOCKERS = {
    "adb": "Google's adb", "fastboot": "Google's fastboot", "scrcpy": "scrcpy",
    "studio64": "Android Studio", "studio": "Android Studio",
    "miflash": "Mi Flash", "xiaomiflash": "Mi Flash", "miflash_unlock": "Mi Unlock",
    "miunlock": "Mi Unlock", "miphoneassistant": "Mi PC Suite",
}


def blocking_programs() -> List[str]:
    """Process names (lower case, no .exe) of running programs that may hold the phone."""
    import subprocess
    try:
        if sys.platform == "win32":
            from miunlock.system import NO_WINDOW
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                                 timeout=10, creationflags=NO_WINDOW).stdout
            names = {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line.strip()}
        else:
            out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=10).stdout
            names = {line.strip().rsplit("/", 1)[-1].lower() for line in out.splitlines()}
    except (OSError, subprocess.SubprocessError):
        return []
    names = {n[:-4] if n.endswith(".exe") else n for n in names}
    return sorted(n for n in names if n in _BLOCKERS)


def stop_google_adb() -> bool:
    """End Google's adb server so miunlock can use the phone. It starts again the next time
    you use adb. Returns True if one was running."""
    import subprocess
    if "adb" not in blocking_programs():
        return False
    from miunlock.system import NO_WINDOW
    cmd = ["taskkill", "/IM", "adb.exe", "/F"] if sys.platform == "win32" else ["pkill", "-x", "adb"]
    subprocess.run(cmd, capture_output=True, timeout=15, creationflags=NO_WINDOW)
    return True


# Why a plugged-in phone cannot be opened (None means it can).
BUSY = "busy"                    # another program has it open; the driver is fine
NO_DRIVER = "no-driver"          # Windows has no usable (WinUSB) driver for it
NO_PERMISSION = "no-permission"  # Linux/macOS: this user may not open it


def reason_for(err: Exception) -> str:
    """Classify a failure to open the phone. libusb says "not supported" when Windows has no
    usable driver, and "access denied" when the driver is fine but another program has the
    phone open (on Linux "access denied" means a permission problem instead)."""
    errno = getattr(err, "errno", None)
    text = str(err).lower()
    if isinstance(err, NotImplementedError) or "not supported" in text:
        return NO_DRIVER
    if errno == 16 or "busy" in text:
        return BUSY
    if errno == 13 or "access" in text:
        return BUSY if sys.platform == "win32" else NO_PERMISSION
    return BUSY


def no_access_advice(reason: str = BUSY) -> str:
    """What to do about a phone that is plugged in but cannot be opened."""
    if reason == NO_DRIVER:
        return "Windows has no driver for it: see Help > USB driver help (or run `miunlock driver-help`)."
    if reason == NO_PERMISSION:
        return ("Your user has no permission for it: add a udev rule for Android phones "
                "(for example install the android-sdk-platform-tools-common package) and reconnect.")
    running = blocking_programs()
    if running:
        names = ", ".join(dict.fromkeys(_BLOCKERS[n] for n in running))
        return (f"{names} has the phone open, and only one program can use it at a time. "
                + ("Stop it to continue; it starts again by itself when you next use adb." if "adb" in running
                   else "Close it, then click Rescan."))
    return ("Another program is using it. Close programs that talk to Android phones (adb, Android "
            "Studio, Mi Flash, phone managers), then unplug and reconnect the phone.")


def explain(err: Exception) -> UsbError:
    """Turn a pyusb error into a readable UsbError."""
    import usb.core
    timeout_cls = getattr(usb.core, "USBTimeoutError", None)
    if timeout_cls is not None and isinstance(err, timeout_cls):
        return UsbTimeout("The phone did not answer in time.")
    errno = getattr(err, "errno", None)
    text = str(err).lower()
    if errno == 110 or "timed out" in text or "timeout" in text:
        return UsbTimeout("The phone did not answer in time.")
    if errno == 19 or "no such device" in text:
        return UsbError("The phone was disconnected.")
    if errno in (13, 16) or isinstance(err, NotImplementedError) or any(
            w in text for w in ("access", "busy", "not supported")):
        return UsbError("The phone was found but could not be opened. " + no_access_advice(reason_for(err)))
    return UsbError(f"USB error: {err}")


def find(triple: Tuple[int, int, int]) -> List[Tuple[Any, Any]]:
    """All (device, interface) pairs whose interface class/subclass/protocol match."""
    import usb.core
    result = []
    for dev in usb.core.find(find_all=True, backend=backend()):
        try:
            for cfg in dev:
                for intf in cfg:
                    if (intf.bInterfaceClass, intf.bInterfaceSubClass, intf.bInterfaceProtocol) == triple:
                        result.append((dev, intf))
        except (usb.core.USBError, NotImplementedError, ValueError):
            continue
    return result


def identify(dev) -> Tuple[str, Optional[str]]:
    """(serial, reason). reason is None when the phone can be opened, else BUSY, NO_DRIVER or
    NO_PERMISSION. When it cannot be opened the serial is unreadable, so the USB bus position
    stands in for it."""
    import usb.core
    import usb.util
    fallback = f"usb-{dev.bus}-{dev.address}"
    try:
        dev.ctrl_transfer(0x80, 0x00, 0, 0, 2, timeout=1000)  # GET_STATUS: opens the device
    except NotImplementedError as err:
        return fallback, reason_for(err)
    except usb.core.USBError as err:
        if getattr(err, "errno", None) in (13, 16) or "access" in str(err).lower():
            return fallback, reason_for(err)
        # any other answer (such as a stall) still means the device opened
    try:
        serial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else None
    except Exception:
        serial = None
    finally:
        try:
            usb.util.dispose_resources(dev)  # close the probe; a real connection reopens it
        except Exception:
            pass
    return serial or fallback, None


class Handle:
    """One claimed USB interface with a bulk IN and a bulk OUT endpoint."""

    def __init__(self, dev, intf):
        import usb.core
        import usb.util
        self.dev = dev
        self.number = intf.bInterfaceNumber

        def bulk(direction):
            return usb.util.find_descriptor(
                intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == direction
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK)

        self.ep_out = bulk(usb.util.ENDPOINT_OUT)
        self.ep_in = bulk(usb.util.ENDPOINT_IN)
        if self.ep_out is None or self.ep_in is None:
            raise UsbError("The phone's USB interface has no bulk endpoints.")
        self.max_packet = self.ep_out.wMaxPacketSize or 512
        try:
            try:
                if dev.is_kernel_driver_active(self.number):
                    dev.detach_kernel_driver(self.number)
            except (NotImplementedError, usb.core.USBError):
                pass
            usb.util.claim_interface(dev, self.number)
        except (usb.core.USBError, NotImplementedError) as err:
            raise explain(err) from None

    def write(self, data: bytes, timeout_ms: int = 5000, zlp: bool = False) -> None:
        """Bulk write. zlp=True ends a transfer whose length is a multiple of the packet
        size with a zero-length packet, as Google's adb host does; fastboot must not."""
        import usb.core
        try:
            self.ep_out.write(data, timeout=timeout_ms)
            if zlp and data and len(data) % self.max_packet == 0:
                self.ep_out.write(b"", timeout=timeout_ms)
        except (usb.core.USBError, NotImplementedError) as err:
            raise explain(err) from None

    def read(self, size: int, timeout_ms: int = 5000) -> bytes:
        import usb.core
        try:
            return bytes(self.ep_in.read(size, timeout=timeout_ms))
        except (usb.core.USBError, NotImplementedError) as err:
            raise explain(err) from None

    def close(self) -> None:
        import usb.util
        try:
            usb.util.release_interface(self.dev, self.number)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass


def open_first(triple: Tuple[int, int, int], serial: Optional[str] = None):
    """Open the first accessible interface of this kind, optionally with this serial.
    Returns (handle, serial) or raises UsbError."""
    blocked = None
    for dev, intf in find(triple):
        ser, reason = identify(dev)
        if serial and ser != serial:
            continue
        if reason:
            blocked = reason
            continue
        return Handle(dev, intf), ser
    if blocked:
        raise UsbError("The phone was found but could not be opened. " + no_access_advice(blocked))
    raise UsbError("No phone found.")
