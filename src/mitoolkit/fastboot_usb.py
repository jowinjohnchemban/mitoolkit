"""
mitoolkit's own fastboot client: the fastboot USB protocol, for the few commands the
unlock needs. No fastboot program is used.

Protocol (from AOSP's fastboot documentation): the host writes one ASCII command; the
phone answers with packets that start with INFO or TEXT (progress, may repeat), DATA
(ready for N bytes), OKAY (done) or FAIL (refused).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from mitoolkit import usbio
from mitoolkit.adb_core import describe_link
from mitoolkit.errors import MitoolkitError

FASTBOOT = (0xFF, 0x42, 0x03)  # USB interface class, subclass, protocol
_READ = 256  # responses are at most 256 bytes (fastboot README)
_CHUNK = 1024 * 1024


class FastbootError(MitoolkitError):
    """str(e) is human-readable."""


class Refused(FastbootError):
    """The phone answered FAIL."""


def devices() -> List[Dict[str, object]]:
    """Phones in fastboot mode: [{"serial", "accessible", "reason"}]. reason says why a phone
    cannot be opened (usbio.BUSY, NO_DRIVER, NO_PERMISSION) or is None."""
    out = []
    for dev, _intf in usbio.find(FASTBOOT):
        serial, reason = usbio.identify(dev)
        out.append({"serial": serial, "accessible": reason is None, "reason": reason,
                    "link": describe_link(serial, usbio.location(dev))})
    return out


class FastbootDevice:
    """Use with ``with open_device() as fb:`` so the USB interface is always released."""

    def __init__(self, serial: Optional[str] = None):
        try:
            self._h, self.serial = usbio.open_first(FASTBOOT, serial)
        except usbio.UsbError as err:
            if str(err) == "No phone found.":
                raise FastbootError("No phone in fastboot mode is connected.") from None
            raise FastbootError(str(err)) from None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self) -> None:
        self._h.close()

    def _reply(self, timeout_ms: int, info: Optional[List[str]]) -> Tuple[str, str]:
        while True:
            try:
                packet = self._h.read(_READ, timeout_ms)
            except usbio.UsbError as err:
                raise FastbootError(str(err)) from None
            head, body = packet[:4], packet[4:].decode("utf-8", "replace")
            if head in (b"INFO", b"TEXT"):
                if info is not None:
                    info.append(body)
                continue
            if head == b"FAIL":
                raise Refused(f"The phone refused: {body or 'no reason given'}")
            if head in (b"OKAY", b"DATA"):
                return head.decode(), body
            raise FastbootError(f"Unexpected reply from the phone: {packet[:16]!r}")

    def command(self, cmd: str, timeout_ms: int = 10000, info: Optional[List[str]] = None) -> str:
        logging.getLogger("mitoolkit.fastboot").debug("fastboot command: %s", cmd.split(":")[0] + (
            ":" + cmd.split(":", 1)[1][:40] if ":" in cmd and not cmd.startswith("oem") else ""))
        try:
            self._h.write(cmd.encode("ascii"))
        except usbio.UsbError as err:
            raise FastbootError(str(err)) from None
        kind, body = self._reply(timeout_ms, info)
        if kind != "OKAY":
            raise FastbootError(f"Unexpected DATA reply to '{cmd}'.")
        return body

    def getvar(self, name: str) -> Optional[str]:
        """The variable's value, or None if this phone does not have it."""
        try:
            return self.command(f"getvar:{name}", 5000).strip() or None
        except Refused:
            return None

    def all_vars(self) -> List[str]:
        """Every variable the bootloader reports (`getvar all`), as the raw INFO lines."""
        lines: List[str] = []
        try:
            self.command("getvar:all", 20000, lines)
        except Refused:
            return []
        return lines

    def oem(self, sub: str, timeout_ms: int = 60000) -> Tuple[str, List[str]]:
        info: List[str] = []
        reply = self.command(f"oem {sub}", timeout_ms, info)
        return reply, info

    def download(self, data: bytes) -> None:
        """Send data to the phone's staging buffer (what `fastboot stage` does)."""
        if not data:
            raise FastbootError("Nothing to upload.")  # Google's fastboot refuses empty downloads too
        try:
            self._h.write(f"download:{len(data):08x}".encode("ascii"))
        except usbio.UsbError as err:
            raise FastbootError(str(err)) from None
        kind, body = self._reply(10000, None)
        if kind != "DATA" or int(body or "0", 16) != len(data):
            raise FastbootError("The phone did not accept the upload.")
        try:
            for i in range(0, len(data), _CHUNK):
                self._h.write(data[i:i + _CHUNK], 30000)  # no zero-length packet, as in Google's fastboot
        except usbio.UsbError as err:
            raise FastbootError(str(err)) from None
        self._reply(30000, None)

    def reboot(self, mode: str = "") -> None:
        """mode: "" (Android), "recovery" or "bootloader"."""
        try:
            self.command({"": "reboot", "recovery": "reboot-recovery", "bootloader": "reboot-bootloader"}[mode], 5000)
        except FastbootError:
            pass  # the phone may drop off USB before it answers


def parse_token(info: List[str]) -> Optional[str]:
    """Xiaomi prints the device token as one or more 'token:<part>' lines."""
    parts = [line.split("token:", 1)[1].strip() for line in info if "token:" in line]
    return "".join(parts) or None
