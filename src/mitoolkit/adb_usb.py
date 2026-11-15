"""
mitoolkit's own adb client: the adb USB protocol, for what mitoolkit needs (device
details, reboot to fastboot, copying files, managing preinstalled apps). No adb
program or adb server is used.

Checked against AOSP's adb sources (adb.cpp, adb.h, client/auth.cpp,
daemon/file_sync_service.cpp). Protocol: every message is a 24-byte little-endian header
(command, arg0, arg1, data length, data checksum, command ^ 0xffffffff) followed by the
data. CNXN/AUTH set up the connection; OPEN/OKAY/WRTE/CLSE carry streams such as
``shell:...``, ``reboot:...`` and ``sync:`` (file transfer).
"""
from __future__ import annotations

import os
import stat
import struct
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from mitoolkit import adbkey, usbio
from mitoolkit.errors import MitoolkitError

ADB = (0xFF, 0x42, 0x01)  # USB interface class, subclass, protocol

A_SYNC, A_CNXN, A_AUTH = 0x434E5953, 0x4E584E43, 0x48545541
A_OPEN, A_OKAY, A_CLSE, A_WRTE = 0x4E45504F, 0x59414B4F, 0x45534C43, 0x45545257
VERSION = 0x01000001
MAX_DATA = 256 * 1024
AUTH_TOKEN, AUTH_SIGNATURE, AUTH_RSAPUBLICKEY = 1, 2, 3


class AdbError(MitoolkitError):
    """str(e) is human-readable."""


def _checksum(data: bytes) -> int:
    return sum(data) & 0xFFFFFFFF


def pack(cmd: int, arg0: int, arg1: int, data: bytes = b"") -> bytes:
    return struct.pack("<6I", cmd, arg0, arg1, len(data), _checksum(data), cmd ^ 0xFFFFFFFF)


class AdbDevice:
    """One phone over USB. Thread-safe: one stream at a time."""

    def __init__(self, dev, intf, serial: str):
        self.serial = serial
        self.port = (getattr(dev, "bus", None), getattr(dev, "address", None))  # recognise it without reopening
        self.state = "offline"
        self.max_data = 4096
        self._lock = threading.RLock()
        self._next_id = 1
        try:
            self._h = usbio.Handle(dev, intf)
        except usbio.UsbError as err:
            raise AdbError(str(err)) from None

    # ------------------------------------------------------------- transport
    def _send(self, cmd: int, arg0: int, arg1: int, data: bytes = b"") -> None:
        try:
            self._h.write(pack(cmd, arg0, arg1, data))
            if data:
                self._h.write(data, zlp=True)
        except usbio.UsbError as err:
            self.state = "offline"
            raise AdbError(str(err)) from None

    def _recv(self, timeout_ms: int) -> Tuple[int, int, int, bytes]:
        try:
            header = self._h.read(24, timeout_ms)
            if len(header) != 24:
                raise AdbError("The phone sent a damaged message.")
            cmd, arg0, arg1, length, _check, magic = struct.unpack("<6I", header)
            if magic != cmd ^ 0xFFFFFFFF:
                raise AdbError("The phone sent a damaged message.")
            data = b""
            while len(data) < length:
                data += self._h.read(length - len(data), timeout_ms)
            return cmd, arg0, arg1, data
        except usbio.UsbTimeout:
            raise
        except usbio.UsbError as err:
            self.state = "offline"
            raise AdbError(str(err)) from None

    def close(self) -> None:
        self.state = "offline"
        self._h.close()

    # ------------------------------------------------------------ connection
    def connect(self, timeout_ms: int = 3000) -> str:
        """Handshake. Returns "device", or "unauthorized" while the phone shows the
        "Allow USB debugging?" prompt (call poll_authorized() later)."""
        key = adbkey.load_or_create()
        with self._lock:
            # Same as Google's host: "<banner>::features=<list>", no NUL. No features are
            # offered, so the phone uses the plain protocol (no delayed acks, shell v1).
            self._send(A_CNXN, VERSION, MAX_DATA, b"host::features=")
            signed = False
            deadline = time.monotonic() + timeout_ms / 1000
            while True:
                try:
                    cmd, arg0, arg1, data = self._recv(max(int((deadline - time.monotonic()) * 1000), 50))
                except usbio.UsbTimeout:
                    self.state = "offline"
                    raise AdbError("The phone did not answer. Unplug it and plug it back in.") from None
                if cmd == A_CNXN:
                    self.max_data = min(arg1 or 4096, MAX_DATA)
                    self.state = "device"
                    return self.state
                if cmd == A_AUTH and arg0 == AUTH_TOKEN:
                    if not signed:  # maybe the phone already trusts this key
                        self._send(A_AUTH, AUTH_SIGNATURE, 0, key.sign_token(data))
                        signed = True
                        continue
                    self._send(A_AUTH, AUTH_RSAPUBLICKEY, 0, key.adb_public_key())
                    self.state = "unauthorized"
                    return self.state

    def poll_authorized(self, timeout_ms: int = 100) -> str:
        """After the prompt was shown: "device" once the person tapped Allow."""
        with self._lock:
            try:
                cmd, _a0, arg1, _data = self._recv(timeout_ms)
            except usbio.UsbTimeout:
                return self.state
            if cmd == A_CNXN:
                self.max_data = min(arg1 or 4096, MAX_DATA)
                self.state = "device"
            return self.state

    def _require(self) -> None:
        if self.state != "device":
            raise AdbError("USB debugging is not allowed on the phone yet. Tap Allow on its screen."
                           if self.state == "unauthorized" else "The phone is not connected.")

    # ---------------------------------------------------------------- streams
    def _open(self, service: str, timeout_ms: int = 10000) -> Tuple[int, int]:
        local = self._next_id
        self._next_id += 1
        self._send(A_OPEN, local, 0, service.encode() + b"\x00")
        while True:
            try:
                cmd, arg0, arg1, _data = self._recv(timeout_ms)
            except usbio.UsbTimeout:
                raise AdbError("The phone did not answer in time.") from None
            if arg1 != local:
                continue  # leftovers of an earlier stream
            if cmd == A_OKAY:
                return local, arg0
            if cmd == A_CLSE:
                raise AdbError(f"The phone refused the request ({service.split(':')[0]}).")

    def shell(self, command: str, timeout_ms: int = 60000) -> str:
        """Run a command on the phone and return its output."""
        self._require()
        with self._lock:
            local, remote = self._open("shell:" + command)
            out = bytearray()
            while True:
                try:
                    cmd, _arg0, arg1, data = self._recv(timeout_ms)
                except usbio.UsbTimeout:
                    raise AdbError("The phone did not answer in time.") from None
                if arg1 != local:
                    continue
                if cmd == A_WRTE:
                    out += data
                    self._send(A_OKAY, local, remote)
                elif cmd == A_CLSE:
                    break
            return out.decode("utf-8", "replace").replace("\r\n", "\n")

    def reboot(self, target: str = "") -> None:
        """target "" (normal), "bootloader" (fastboot) or "recovery". Erases nothing."""
        self._require()
        with self._lock:
            self._send(A_OPEN, self._next_id, 0, f"reboot:{target}".encode() + b"\x00")
            self._next_id += 1
            try:
                self._recv(2000)
            except (AdbError, usbio.UsbError):
                pass  # the phone may restart before it answers
            self.state = "offline"

    def tcpip(self, port: int = 5555) -> None:
        """Make the phone listen for adb over Wi-Fi on this port (until it restarts)."""
        self._require()
        with self._lock:
            try:
                self._open(f"tcpip:{int(port)}")
            except AdbError:
                pass  # the phone restarts its adb daemon and drops the connection

    def _open_stream(self, service: str) -> "_Stream":
        local, remote = self._open(service)
        return _Stream(self, local, remote)

    def sync(self) -> "SyncSession":
        self._require()
        return SyncSession(lambda: self._open_stream("sync:"), self._lock)


class _Stream:
    """A byte stream over adb WRTE/OKAY messages."""

    def __init__(self, dev: AdbDevice, local: int, remote: int):
        self.dev, self.local, self.remote = dev, local, remote
        self.buf = bytearray()
        self.closed = False

    def _pump(self, timeout_ms: int) -> int:
        try:
            cmd, _arg0, arg1, data = self.dev._recv(timeout_ms)
        except usbio.UsbTimeout:
            raise AdbError("The phone did not answer in time.") from None
        if arg1 != self.local:
            return 0
        if cmd == A_WRTE:
            self.buf += data
            self.dev._send(A_OKAY, self.local, self.remote)
        elif cmd == A_CLSE:
            self.closed = True
        return cmd

    def write(self, data: bytes, timeout_ms: int = 30000) -> None:
        for i in range(0, len(data), self.dev.max_data):
            self.dev._send(A_WRTE, self.local, self.remote, data[i:i + self.dev.max_data])
            while True:
                cmd = self._pump(timeout_ms)
                if cmd == A_OKAY:
                    break
                if self.closed:
                    raise AdbError("The phone closed the connection.")

    def read(self, n: int, timeout_ms: int = 30000) -> bytes:
        while len(self.buf) < n:
            if self.closed:
                raise AdbError("The phone closed the connection.")
            self._pump(timeout_ms)
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def close(self) -> None:
        if not self.closed:
            try:
                self.dev._send(A_CLSE, self.local, self.remote)
            except AdbError:
                # the phone may already be gone; the stream is closed on our side either way
                pass
            self.closed = True


class SyncSession:
    """adb's file transfer service (``sync:``): stat, list and receive files. Works over any
    byte stream with read(n), write(data), close() and .closed: a USB stream here, or a
    socket to Google's adb server (adb_server.py). ``opener`` makes a new one, because the
    phone ends the session after a failed transfer."""

    def __init__(self, opener: Callable[[], object], lock):
        self._opener = opener
        self._lock = lock
        self._stream = None

    def _s(self):
        if self._stream is None or self._stream.closed:
            self._stream = self._opener()
        return self._stream

    def _request(self, ident: bytes, path: str):
        raw = path.encode("utf-8")
        s = self._s()
        s.write(ident + struct.pack("<I", len(raw)) + raw)
        return s

    def stat(self, path: str) -> Tuple[int, int, int]:
        """(mode, size, mtime); mode 0 means it does not exist."""
        with self._lock:
            s = self._request(b"STAT", path)
            reply = s.read(16)
            if reply[:4] != b"STAT":
                raise AdbError("Unexpected reply to a file request.")
            return struct.unpack("<III", reply[4:])

    def listdir(self, path: str) -> List[Tuple[str, int, int, int]]:
        """[(name, mode, size, mtime)] without . and .."""
        with self._lock:
            s = self._request(b"LIST", path)
            out = []
            while True:
                head = s.read(20)
                if head[:4] == b"DONE":
                    return out
                if head[:4] != b"DENT":
                    raise AdbError("Unexpected reply while listing a folder.")
                mode, size, mtime, namelen = struct.unpack("<IIII", head[4:])
                name = s.read(namelen).decode("utf-8", "replace")
                if name not in (".", ".."):
                    out.append((name, mode, size, mtime))

    def recv(self, path: str, local: Path, cancel: Optional[threading.Event] = None) -> int:
        """Copy one file from the phone. Returns bytes written. Raises AdbError on failure."""
        with self._lock:
            s = self._request(b"RECV", path)
            tmp = local.with_name(local.name + ".part")
            written = 0
            try:
                with open(tmp, "wb") as f:
                    while True:
                        head = s.read(8)
                        ident, length = head[:4], struct.unpack("<I", head[4:])[0]
                        if ident == b"DATA":
                            f.write(s.read(length))
                            written += length
                            if cancel is not None and cancel.is_set():
                                s.close()  # abandon this transfer; the next request reopens
                                raise AdbError("Cancelled.")
                        elif ident == b"DONE":
                            break
                        elif ident == b"FAIL":
                            msg = s.read(length).decode("utf-8", "replace")
                            s.close()  # the phone ends the sync session after FAIL
                            raise AdbError(msg or "The phone could not send the file.")
                        else:
                            s.close()
                            raise AdbError("Unexpected reply while copying a file.")
                os.replace(tmp, local)
            finally:
                if tmp.exists():
                    tmp.unlink()
            return written

    def walk(self, root: str) -> Iterator[Tuple[str, int, int, int]]:
        """Every regular file under root: (remote path, mode, size, mtime)."""
        stack = [root.rstrip("/")]
        while stack:
            folder = stack.pop()
            try:
                entries = self.listdir(folder + "/")
            except AdbError:
                continue
            for name, mode, size, mtime in entries:
                full = f"{folder}/{name}"
                if stat.S_ISDIR(mode):
                    stack.append(full)
                elif stat.S_ISREG(mode):
                    yield full, mode, size, mtime

    def close(self) -> None:
        if self._stream is not None and not self._stream.closed:
            try:
                self._stream.write(b"QUIT" + struct.pack("<I", 0))
            except AdbError:
                # a polite goodbye: if the phone is gone there is nobody to say it to
                pass
            self._stream.close()


# --------------------------------------------------------------- registry
# Phones mitoolkit is talking to, by serial: AdbDevice (own USB connection) or
# adb_server.ServerDevice (through Google's adb server).
_devices: Dict[str, object] = {}
_reg_lock = threading.Lock()
_real_serials: Dict[str, str] = {}      # Wi-Fi address -> the phone's own serial


def _scan_server() -> List[Dict[str, str]]:
    from mitoolkit import adb_server
    found = adb_server.devices()
    for serial, dev in list(_devices.items()):  # our own USB connections would conflict
        if not isinstance(dev, adb_server.ServerDevice):
            dev.close()
            _devices.pop(serial)
    seen = set()
    for d in found:
        seen.add(d["serial"])
        known = _devices.get(d["serial"])
        if known is None:
            _devices[d["serial"]] = adb_server.ServerDevice(d["serial"], d["state"])
        else:
            known.state = d["state"]
    for serial in list(_devices):
        if serial not in seen:
            _devices.pop(serial)
    # A phone plugged in AND on Wi-Fi shows up twice: keep the USB entry (fastboot needs the cable anyway)
    wired = {s for s in _devices if ":" not in s}
    out = []
    for d in found:
        dev = _devices[d["serial"]]
        if dev.wireless and d["state"] == "device" and wired:
            if d["serial"] not in _real_serials:        # asked once; the entry is recreated every scan
                try:
                    _real_serials[d["serial"]] = dev.shell("getprop ro.serialno", 5000).strip()
                except AdbError:
                    _real_serials[d["serial"]] = ""
            if _real_serials[d["serial"]] in wired:
                _devices.pop(d["serial"], None)
                continue
        out.append({"serial": d["serial"], "state": d["state"], "via": "adb server"})
    return out


def _scan_usb() -> List[Dict[str, str]]:
    results, seen = [], set()
    held = {dev.port: dev for dev in _devices.values() if isinstance(dev, AdbDevice) and dev.state != "offline"}
    for dev, intf in usbio.find(ADB):
        known = held.get((dev.bus, dev.address))
        if known is not None:
            # Already connected: probing it again would fail with "access denied" because
            # mitoolkit itself has it open, so just use the connection we have.
            seen.add(known.serial)
            if known.state == "unauthorized":
                try:
                    known.poll_authorized()
                except AdbError:
                    # still waiting for the person to tap Allow: the next scan asks again
                    pass
            results.append({"serial": known.serial, "state": known.state})
            continue
        serial, reason = usbio.identify(dev)
        seen.add(serial)
        stale = _devices.pop(serial, None)
        if stale is not None:
            stale.close()
        if reason:
            results.append({"serial": serial, "state": "no-access", "reason": reason})
            continue
        try:
            fresh = AdbDevice(dev, intf, serial)
            fresh.connect()
        except AdbError as err:
            results.append({"serial": serial, "state": "offline", "error": str(err)})
            continue
        _devices[serial] = fresh
        results.append({"serial": serial, "state": fresh.state})
    for serial in list(_devices):
        if serial not in seen:
            _devices.pop(serial).close()
    return results


def scan() -> List[Dict[str, str]]:
    """Phones with adb enabled: [{"serial", "state"}]. state is "device" (ready),
    "unauthorized" (waiting for Allow on the phone), "offline" or "no-access" (found but
    cannot be opened; "reason" says why: usbio.BUSY, NO_DRIVER or NO_PERMISSION).

    If Google's adb server is running it owns the phones, so mitoolkit goes through it
    (entries then have "via": "adb server"); otherwise mitoolkit uses its own USB connection,
    kept open between calls."""
    from mitoolkit import adb_server
    with _reg_lock:
        if adb_server.running():
            try:
                return _scan_server()
            except AdbError:
                pass  # the server stopped in between; fall back to USB
        return _scan_usb()


def get(serial: Optional[str] = None):
    """A ready phone (state "device"), connecting first if needed."""
    if serial is None or serial not in _devices:
        scan()
    with _reg_lock:
        ready = [d for s, d in _devices.items() if d.state == "device" and (serial is None or s == serial)]
    if not ready:
        raise AdbError("No phone with USB debugging allowed is connected.")
    if serial is None and len(ready) > 1:
        raise AdbError("More than one phone is connected; choose one by its serial.")
    return ready[0]


def forget(serial: str) -> None:
    with _reg_lock:
        dev = _devices.pop(serial, None)
    if dev is not None:
        dev.close()
