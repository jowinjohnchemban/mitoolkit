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


def no_access_advice() -> str:
    if sys.platform == "win32":
        return "Windows has no usable driver for it: use File > Install Google USB driver (or `miunlock install-driver`)."
    if sys.platform.startswith("linux"):
        return ("Your user has no permission for it: add a udev rule for Android phones "
                "(for example install the android-sdk-platform-tools-common package) and reconnect.")
    return "Reconnect the phone and try again."


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
    if errno == 13 or "access" in text:
        return UsbError("The phone was found but could not be opened. " + no_access_advice())
    if errno == 16 or "busy" in text:
        return UsbError("Another program is using the phone. Close Google's adb (`adb kill-server`), "
                        "Android Studio, Mi Unlock or Mi Flash and try again.")
    if errno == 19 or "no such device" in text:
        return UsbError("The phone was disconnected.")
    if isinstance(err, NotImplementedError) or "not supported" in text:
        return UsbError("The phone was found but could not be opened. " + no_access_advice())
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


def identify(dev) -> Tuple[str, bool]:
    """(serial, accessible). Reading the serial needs the device open, so failing to read it
    means no driver or no permission; the bus position then stands in for the serial."""
    import usb.util
    try:
        if dev.iSerialNumber:
            serial = usb.util.get_string(dev, dev.iSerialNumber)
            if serial:
                return serial, True
        return f"usb-{dev.bus}-{dev.address}", True
    except Exception:
        return f"usb-{dev.bus}-{dev.address}", False


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
        ser, accessible = identify(dev)
        if serial and ser != serial:
            continue
        if not accessible:
            blocked = ser
            continue
        return Handle(dev, intf), ser
    if blocked:
        raise UsbError("The phone was found but could not be opened. " + no_access_advice())
    raise UsbError("No phone found.")
