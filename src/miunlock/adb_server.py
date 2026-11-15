"""
Talking to phones through Google's adb server, when one is already running.

Only one program can open a phone's adb interface. If Google's adb server is running (for
example because you used ``adb`` or Android Studio), it holds every phone, so instead of
competing with it miunlock asks it to do the work, the same way the ``adb`` command does:
over a local socket (127.0.0.1:5037), with the "smart socket" protocol from AOSP's
adb/SERVICES.TXT. Nothing leaves this computer.

    request:  4 hex digits (length) + text, for example "000chost:version"
    answer:   "OKAY", or "FAIL" + 4 hex digits + message
    host:devices                 list phones as "serial<TAB>state" lines
    host:transport:<serial>      route the rest of this connection to that phone
    shell:<command>, reboot:<target>, sync:   then the same services as over USB
"""
from __future__ import annotations

import logging
import socket
import threading
from typing import Dict, List, Optional

from miunlock.adb_usb import AdbError, SyncSession

HOST, PORT = "127.0.0.1", 5037


class _Conn:
    """One connection to the adb server."""

    def __init__(self, timeout: float = 10.0):
        try:
            self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        except OSError:
            raise AdbError("Google's adb server is not running.") from None
        self.closed = False

    def request(self, text: str) -> None:
        raw = text.encode("utf-8")
        self.sock.sendall(f"{len(raw):04x}".encode() + raw)
        status = self.read(4)
        if status == b"OKAY":
            return
        if status == b"FAIL":
            msg = self.read(int(self.read(4), 16)).decode("utf-8", "replace")
            raise AdbError(_readable(msg))
        raise AdbError("Unexpected answer from Google's adb server.")

    def read(self, n: int, timeout_ms: int = 30000) -> bytes:
        self.sock.settimeout(timeout_ms / 1000)
        out = bytearray()
        try:
            while len(out) < n:
                chunk = self.sock.recv(n - len(out))
                if not chunk:
                    self.closed = True
                    raise AdbError("The phone closed the connection.")
                out += chunk
        except socket.timeout:
            raise AdbError("The phone did not answer in time.") from None
        except OSError as err:
            self.closed = True
            raise AdbError(f"Lost the connection to Google's adb server ({err}).") from None
        return bytes(out)

    def read_all(self, timeout_ms: int = 60000) -> bytes:
        self.sock.settimeout(timeout_ms / 1000)
        out = bytearray()
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                out += chunk
        except socket.timeout:
            raise AdbError("The phone did not answer in time.") from None
        self.close()
        return bytes(out)

    def write(self, data: bytes, timeout_ms: int = 30000) -> None:
        self.sock.settimeout(timeout_ms / 1000)
        try:
            self.sock.sendall(data)
        except OSError as err:
            self.closed = True
            raise AdbError(f"Lost the connection to Google's adb server ({err}).") from None

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                self.sock.close()
            except OSError:
                pass


def _readable(msg: str) -> str:
    low = msg.lower()
    if "unauthorized" in low:
        return "USB debugging is not allowed on the phone yet. Tap Allow on its screen."
    if "not found" in low:
        return "The phone is no longer connected."
    if "offline" in low:
        return "The phone is offline. Unplug it and plug it back in."
    return msg


def running() -> bool:
    """True if Google's adb server answers on this computer."""
    try:
        conn = _Conn(timeout=0.3)
    except AdbError:
        return False
    try:
        conn.request("host:version")
        return True
    except AdbError:
        return False
    finally:
        conn.close()


def devices() -> List[Dict[str, str]]:
    """[{"serial", "state"}] as Google's adb server sees them."""
    conn = _Conn()
    try:
        conn.request("host:devices")
        body = conn.read(int(conn.read(4), 16)).decode("utf-8", "replace")
    finally:
        conn.close()
    out = []
    for line in body.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append({"serial": parts[0], "state": parts[1].strip()})
    return out


def start() -> bool:
    """Start Google's adb server if it is installed and not running. Wi-Fi connections need it:
    miunlock's own adb speaks USB only. Returns True when a server is running afterwards."""
    if running():
        return True
    from miunlock import platform_tools
    from miunlock.system import NO_WINDOW
    exe = platform_tools.find("adb")
    if not exe:
        return False
    import subprocess
    try:
        subprocess.run([exe, "start-server"], capture_output=True, timeout=20, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return running()


def _host_command(text: str, timeout: float = 15.0) -> str:
    """Send a "host:" service and return its text answer (connecting can take a few seconds)."""
    conn = _Conn(timeout=timeout)
    try:
        conn.request(text)
        return conn.read(int(conn.read(4), 16), int(timeout * 1000)).decode("utf-8", "replace").strip()
    finally:
        conn.close()


def valid_address(text: str) -> Optional[str]:
    """"192.168.1.5" or "192.168.1.5:5555" as "host:port", or None when it is not an address."""
    text = text.strip()
    host, _, port = text.partition(":")
    parts = host.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return None
    if port and not (port.isdigit() and 1 <= int(port) <= 65535):
        return None
    return f"{host}:{port or 5555}"


def connect(address: str) -> str:
    """Connect to a phone over Wi-Fi ("192.168.1.5" or "192.168.1.5:5555"). Needs the phone's wireless
    adb switched on (see ServerDevice.tcpip) and Google's adb server running. Returns its answer."""
    target = valid_address(address)
    if target is None:
        raise AdbError("That is not an address. Use the phone's Wi-Fi address, like 192.168.1.5.")
    if not start():
        raise AdbError("Wi-Fi needs Google's adb (platform-tools), which was not found on this computer.")
    answer = _host_command(f"host:connect:{target}")
    logging.getLogger("miunlock.adb").debug("adb server connect %s: %s", target, answer)
    low = answer.lower()
    if "connected to" not in low:
        raise AdbError(answer or "The phone did not answer. Check it is on the same Wi-Fi.")
    return target


def disconnect(address: str) -> None:
    target = valid_address(address)
    if target is not None and running():
        _host_command(f"host:disconnect:{target}")


class ServerDevice:
    """A phone reached through Google's adb server. Same interface as adb_usb.AdbDevice
    (serial, state, shell, reboot, sync, close), so adb.Phone works with either."""

    def __init__(self, serial: str, state: str = "device"):
        self.serial, self.state = serial, state
        self._lock = threading.RLock()
        self.real_serial: Optional[str] = None      # the phone's own serial (a Wi-Fi entry is named by address)

    @property
    def wireless(self) -> bool:
        return ":" in self.serial

    def tcpip(self, port: int = 5555) -> None:
        """Make the phone listen for adb over Wi-Fi on this port (until it restarts)."""
        with self._lock:
            conn = self._service(f"tcpip:{int(port)}")
            try:
                conn.read_all(5000)
            except AdbError:
                pass

    def _service(self, service: str) -> _Conn:
        conn = _Conn()
        try:
            conn.request(f"host:transport:{self.serial}")
            conn.request(service)
        except AdbError:
            conn.close()
            raise
        return conn

    def shell(self, command: str, timeout_ms: int = 60000) -> str:
        with self._lock:
            out = self._service("shell:" + command).read_all(timeout_ms)
        return out.decode("utf-8", "replace").replace("\r\n", "\n")

    def reboot(self, target: str = "") -> None:
        with self._lock:
            conn = self._service(f"reboot:{target}")
            try:
                conn.read_all(5000)
            except AdbError:
                pass
        self.state = "offline"

    def sync(self) -> SyncSession:
        return SyncSession(lambda: self._service("sync:"), self._lock)

    def close(self) -> None:
        self.state = "offline"
