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

from mitoolkit import settings, wifi_scan
from mitoolkit.adb_core import AdbError, SyncSession, is_wireless

HOST, PORT = "127.0.0.1", 5037
HOSTS_KEY, MAX_HOSTS = "wifi_hosts", 5          # the addresses of phones that were connected over Wi-Fi, newest first


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
    """Plain words for what Google's adb says."""
    low = msg.lower()
    if "unauthorized" in low:
        return "The phone has not allowed this computer yet. Unlock it and tap Allow."
    if "not found" in low:
        return "The phone is no longer connected."
    if "offline" in low:
        return "The phone is offline. Unplug it and plug it back in, or turn Wireless debugging off and on."
    if "refused" in low or "10061" in low:
        return ("The phone refused the connection. Wireless debugging uses a different number (port) every time it "
                "is switched on, so use the address shown on its Wireless debugging screen.")
    if "timed out" in low or "10060" in low or "10065" in low or "unreachable" in low:
        return "The phone did not answer. Check that it is on the same Wi-Fi as this computer, and awake."
    if low.startswith("failed to connect to "):
        return "Could not connect to " + msg[len("failed to connect to "):].strip(" '.") + "."
    if low.startswith("failed to authenticate"):
        return "The phone did not accept this computer. Pair it first, or tap Allow on the phone."
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
        body = _read_text(conn)
    finally:
        conn.close()
    out = []
    for line in body.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append({"serial": parts[0], "state": parts[1].strip()})
    return out


def usb_locations() -> Dict[str, str]:
    """Where each cable-connected phone is plugged in, as Google's adb reports it: {serial: "1-3"} (the ``usb:`` field
    of ``adb devices -l``). Best effort: an empty answer only means the footer shows no port."""
    conn = _Conn()
    try:
        conn.request("host:devices-l")
        body = _read_text(conn)
    except AdbError:
        return {}
    finally:
        conn.close()
    found = {}
    for line in body.splitlines():
        match = re.match(r"^(\S+)\s+.*\busb:(\S+)", line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


_started = {"by_us": False}      # did MiToolkit start the adb server that is running? (then it also stops it)


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
    up = running()
    _started["by_us"] = _started["by_us"] or up
    return up


def stop_started(also_others: bool = False) -> str:
    """Stop Google's adb server so it does not keep holding phones after MiToolkit closes. Only a server MiToolkit
    started is stopped: one that was already running may belong to Android Studio or a terminal. ``also_others``
    stops that one too. Returns what was done ("" when nothing)."""
    if not (_started["by_us"] or also_others) or not running():
        return ""
    from mitoolkit import platform_tools
    from mitoolkit.system import NO_WINDOW
    exe = platform_tools.find("adb")
    if not exe:
        return ""
    import subprocess
    try:
        subprocess.run([exe, "kill-server"], capture_output=True, timeout=10, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ""
    _started["by_us"] = False
    return "Stopped Google's adb server."


def _host_command(text: str, timeout: float = 15.0) -> str:
    """Send a "host:" service and return its text answer (connecting can take a few seconds)."""
    conn = _Conn(timeout=timeout)
    try:
        conn.request(text)
        return _read_text(conn, int(timeout * 1000))
    finally:
        conn.close()


def _read_text(conn: "_Conn", timeout_ms: int = 30000) -> str:
    """The length-prefixed text that follows an OKAY. Some services (host:connect when the phone refuses) send a
    FAIL with its message after the OKAY instead, so that is read too, and shown as the error it is."""
    head = conn.read(4, timeout_ms)
    failed = head == b"FAIL"
    if failed:
        head = conn.read(4, timeout_ms)
    try:
        size = int(head, 16)
    except ValueError:
        raise AdbError("Unexpected answer from Google's adb server.") from None
    text = conn.read(size, timeout_ms).decode("utf-8", "replace").strip()
    if failed:
        raise AdbError(_readable(text))
    return text


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


PAIR_HINT = (" If this phone uses Wireless debugging (Developer options), pair it first with Pair a new phone: "
             "a QR code or the pairing code. It is needed once.")
NEEDS_GOOGLE_ADB ="Wi-Fi needs Google's adb (platform-tools), which was not found on this computer."


def pair(address: str, code: str) -> str:
    """Pair with a phone over Wi-Fi (Android 11 or newer, no cable). On the phone: Settings > Developer options >
    Wireless debugging > Pair device with pairing code. It shows an address with a port and a 6-digit code, both
    valid only while that screen is open. Pairing makes the phone trust this computer's adb key, so the phone
    does not ask "Allow debugging?" again. Returns the pairing address. The code is never logged."""
    target = valid_address(address, require_port=True)
    if target is None:
        raise AdbError("Use the pairing address shown on the phone, with its port, like 192.168.1.xx:41234.")
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
    remember_host(target.rsplit(":", 1)[0])
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


class NothingListening(AdbError):
    """Nothing at that address is waiting for adb (the phone is off or asleep, or Wireless debugging is)."""


def known_hosts() -> List[str]:
    """Addresses of phones connected over Wi-Fi before, newest first. The port changes, the address mostly does not."""
    hosts = settings.get(HOSTS_KEY, [])
    return [h for h in hosts if isinstance(h, str) and valid_address(h)] if isinstance(hosts, list) else []


def remember_host(host: str) -> None:
    """Keep ``host`` so the phone can be found again even when the network does not announce it."""
    hosts = [host] + [h for h in known_hosts() if h != host]
    if hosts != known_hosts():
        settings.set(HOSTS_KEY, hosts[:MAX_HOSTS])


def connect(address: str) -> str:
    """Connect to a phone over Wi-Fi: "192.168.1.xx:39865" (the address on the Wireless debugging screen) or only
    "192.168.1.xx", in which case its port is looked for. Needs Google's adb server. Returns the address connected."""
    target = valid_address(address)
    if target is None:
        raise AdbError("That is not an address. Use the phone's Wi-Fi address, like 192.168.1.xx.")
    if not start():
        raise AdbError(NEEDS_GOOGLE_ADB)
    if ":" not in address.strip():                 # no port given: Wireless debugging picks a random one
        return find_on_host(target.rsplit(":", 1)[0])
    return _connect_to(target)


def _connect_to(target: str) -> str:
    try:
        answer = _host_command(f"host:connect:{target}")
    except AdbError as err:
        raise AdbError(f"{_readable(str(err))}{PAIR_HINT}") from None
    logging.getLogger("mitoolkit.adb").debug("adb server connect %s: %s", target, answer)
    if "connected to" not in answer.lower():
        raise AdbError((answer or "The phone did not answer. Check it is on the same Wi-Fi.") + PAIR_HINT)
    remember_host(target.rsplit(":", 1)[0])
    return target


def find_on_host(host: str, limit: int = 3) -> str:
    """Connect to the phone at ``host`` when its port is not known (and the network does not announce it): look for
    the port, then connect. Returns the address. Raises NothingListening when no port answers, AdbError when one does
    but the phone refuses (usually: it needs pairing first)."""
    log = logging.getLogger("mitoolkit.adb")
    ports = wifi_scan.candidates(host)
    log.debug("ports of %s that may be adb: %s", host, ports)
    if not ports:
        raise NothingListening(f"Nothing at {host} is waiting for adb. Check the phone is awake and on the same "
                               "Wi-Fi, with Wireless debugging on.")
    last: Optional[AdbError] = None
    for port in ports[:limit]:
        try:
            return _connect_to(f"{host}:{port}")
        except AdbError as err:
            last = err
    raise last or AdbError("The phone did not answer.")


def pairing_qr() -> Dict[str, str]:
    """A fresh request to pair by QR code (Android 11 and newer: Wireless debugging > Pair device with QR code).
    The QR text is ``WIFI:T:ADB;S:<name>;P:<password>;;``: the phone scans it, then announces a pairing service on the
    network under that name, and this computer pairs with it using that password. Both are random and used once."""
    import secrets
    import string
    name = "mitoolkit-" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    password = f"{secrets.randbelow(10 ** 6):06d}"
    return {"payload": f"WIFI:T:ADB;S:{name};P:{password};;", "name": name, "password": password}


def wait_for_qr_pairing(name: str, password: str, cancel, timeout: float = 120.0, poll: float = 2.0) -> str:
    """After the phone scanned the QR code: wait for its pairing service (named ``name``) to show up on the network,
    then pair with it. Returns its address. ``cancel`` is a threading.Event that stops the wait."""
    import time
    end = time.monotonic() + timeout
    while not cancel.is_set() and time.monotonic() < end:
        for service in mdns_services():
            if service["kind"] == "pairing" and name in service["name"]:
                return pair(service["address"], password)
        cancel.wait(poll)
    if cancel.is_set():
        raise AdbError("Cancelled.")
    raise AdbError("The phone did not scan the code in time. Try again, or use Pairing Code instead. If the phone did "
                   "scan it, this network may hide phones from this computer (a PC on a cable and a phone on Wi-Fi "
                   "often cannot see each other): Pairing Code works there.")


_tried: Dict[str, float] = {}       # address -> when MiToolkit last tried to connect to it (so it is not hammered)
_scanned: Dict[str, tuple] = {}     # host -> (when, state, address) of the last port search, for phones nothing announces


def _search_known_hosts(serials: List[str], skip: set, scan_gap: float) -> List[Dict[str, str]]:
    """The phones whose address is remembered, for networks that do not announce them: already connected, or look for
    the port (at most every ``scan_gap`` seconds) and connect. State is "connected" or "needs-pairing"; a phone that
    is off or has Wireless debugging off is simply not listed."""
    import time
    out: List[Dict[str, str]] = []
    for host in known_hosts():
        if host in skip:
            continue
        live = next((s for s in serials if s.startswith(host + ":")), None)
        if live:
            out.append({"address": live, "name": "", "state": "connected"})
            continue
        when, state, address = _scanned.get(host, (-1e9, "", ""))
        if time.monotonic() - when >= scan_gap:
            try:
                state, address = "connected", find_on_host(host)
            except NothingListening:
                state, address = "", ""
            except AdbError:
                state, address = "needs-pairing", host
            _scanned[host] = (time.monotonic(), state, address)
        if state:
            out.append({"address": address, "name": "", "state": state})
    return out


def discover_and_connect(min_gap: float = 20.0, scan_gap: float = 45.0) -> List[Dict[str, str]]:
    """Wireless mode's look around: phones announcing Wireless debugging on this network, connected when they already
    trust this computer, then the phones connected before (their port is looked for directly, for networks that never
    deliver the announcements). Returns [{"address", "name", "state"}] with state "connected" or "needs-pairing" (the
    phone is there but has not been paired: pairing is a one-time step with a code shown on the phone). A phone that
    did not accept is not tried again for ``min_gap`` seconds."""
    import time
    if not start():
        raise AdbError(NEEDS_GOOGLE_ADB)
    try:
        announced = [s for s in mdns_services() if s["kind"] == "connect"]
    except AdbError:
        announced = []                              # this network does not pass announcements: see the known hosts
    serials = [d["serial"] for d in devices() if d["state"] == "device"]
    out: List[Dict[str, str]] = []
    for service in announced:
        address, name = service["address"], service["name"]
        # connected already: listed by its address (192.168.1.5:39865) or by its network name (adb-6a81a217-xxxx._adb-tls-...)
        if address in serials or any(s.startswith(name) for s in serials):
            out.append({"address": address, "name": name, "state": "connected"})
            continue
        if time.monotonic() - _tried.get(address, -1e9) < min_gap:
            out.append({"address": address, "name": name, "state": "needs-pairing"})
            continue
        _tried[address] = time.monotonic()
        try:
            connect(address)
            out.append({"address": address, "name": name, "state": "connected"})
        except AdbError:
            # not paired with this computer (or it refused): the person is shown how to pair it
            out.append({"address": address, "name": name, "state": "needs-pairing"})
    announced_hosts = {s["address"].rsplit(":", 1)[0] for s in announced}
    return out + _search_known_hosts(serials, announced_hosts, scan_gap)


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
        return is_wireless(self.serial)

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
