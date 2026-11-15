"""
Talking to phones through Google's adb server, when one is already running.

Only one program can open a phone's adb interface. If Google's adb server is running (for
example because you used ``adb`` or Android Studio), it holds every phone, so instead of
competing with it mitoolkit asks it to do the work, the same way the ``adb`` command does:
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
import re
import socket
import threading
from typing import Dict, List, Optional

from mitoolkit.adb_usb import AdbError, SyncSession

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
                # closing a socket that is already gone is fine
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
    mitoolkit's own adb speaks USB only. Returns True when a server is running afterwards."""
    if running():
        return True
    from mitoolkit import platform_tools
    from mitoolkit.system import NO_WINDOW
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


def valid_address(text: str, require_port: bool = False) -> Optional[str]:
    """"192.168.1.5" or "192.168.1.5:5555" as "host:port", or None when it is not an address.
    With ``require_port`` the port must be given (pairing ports are different every time)."""
    text = text.strip()
    host, _, port = text.partition(":")
    parts = host.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return None
    if port and not (port.isdigit() and 1 <= int(port) <= 65535):
        return None
    if require_port and not port:
        return None
    return f"{host}:{port or 5555}"


NEEDS_GOOGLE_ADB = "Wi-Fi needs Google's adb (platform-tools), which was not found on this computer."


def pair(address: str, code: str) -> str:
    """Pair with a phone over Wi-Fi (Android 11 or newer, no cable). On the phone: Settings > Developer options >
    Wireless debugging > Pair device with pairing code. It shows an address with a port and a 6-digit code, both
    valid only while that screen is open. Pairing makes the phone trust this computer's adb key, so the phone
    does not ask "Allow debugging?" again. Returns the pairing address. The code is never logged."""
    target = valid_address(address, require_port=True)
    if target is None:
        raise AdbError("Use the pairing address shown on the phone, with its port, like 192.168.1.5:41234.")
    code = code.strip()
    if not re.fullmatch(r"\d{6}", code):
        raise AdbError("The pairing code is the 6 digits shown on the phone.")
    if not start():
        raise AdbError(NEEDS_GOOGLE_ADB)
    try:
        answer = _host_command(f"host:pair:{code}:{target}", timeout=30.0)
    except AdbError as err:
        raise AdbError(f"The phone did not accept the pairing: {err} Open Pair device with pairing code on the "
                       "phone again and use the new code.") from None
    logging.getLogger("miunlock.adb").debug("adb pair %s: %s", target, answer)
    if "successfully paired" not in answer.lower():
        raise AdbError(answer or "The phone did not accept the pairing code.")
    return target


def mdns_services(timeout: float = 8.0) -> List[Dict[str, str]]:
    """Phones that announce themselves on the Wi-Fi network: [{"name", "kind", "address"}] with kind "pairing"
    (the Pair device with pairing code screen is open) or "connect" (Wireless debugging is on). Needs Google's
    adb server with mDNS; on a network that blocks it nothing is found and the address is typed instead."""
    if not start():
        raise AdbError(NEEDS_GOOGLE_ADB)
    if "unavailable" in _host_command("host:mdns:check", timeout=timeout).lower():
        raise AdbError("Google's adb cannot look for phones on this network. Type the address shown on the phone.")
    found = []
    for line in _host_command("host:mdns:services", timeout=timeout).splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and valid_address(parts[2], require_port=True):
            kind = "pairing" if "pairing" in parts[1] else "connect" if "connect" in parts[1] else ""
            if kind:
                found.append({"name": parts[0], "kind": kind, "address": parts[2].strip()})
    return found


def connect(address: str) -> str:
    """Connect to a phone over Wi-Fi ("192.168.1.5" or "192.168.1.5:5555"). Needs the phone's wireless
    adb switched on (see ServerDevice.tcpip) and Google's adb server running. Returns its answer."""
    target = valid_address(address)
    if target is None:
        raise AdbError("That is not an address. Use the phone's Wi-Fi address, like 192.168.1.5.")
    if not start():
        raise AdbError(NEEDS_GOOGLE_ADB)
    answer = _host_command(f"host:connect:{target}")
    logging.getLogger("mitoolkit.adb").debug("adb server connect %s: %s", target, answer)
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
                # the phone restarts its adb daemon and drops the connection: that is the answer
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
                # the phone goes away before it can answer
                pass
        self.state = "offline"

    def sync(self) -> SyncSession:
        return SyncSession(lambda: self._service("sync:"), self._lock)

    def close(self) -> None:
        self.state = "offline"
