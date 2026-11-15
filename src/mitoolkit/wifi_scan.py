"""Finding a phone's Wireless debugging port without mDNS.

Wireless debugging listens on a random port (Linux picks it from 32768 to 60999) that changes every time the switch
is turned on. Google's adb learns it from mDNS announcements, but many networks never deliver those to this computer:
a wired PC and a Wi-Fi phone on different segments of the router, client isolation, a firewall. When the phone's
address is known (the person typed it, or it was connected before), this looks for the port directly: it tries to
open a connection to each port of that one address, then asks the ones that answer whether they speak TLS, which
adb's wireless ports do and most other things do not.

Only the one address that was given is probed, never a range of addresses.
"""
from __future__ import annotations

import selectors
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List

LOW, HIGH = 32768, 60999        # where the phone's kernel picks a random listening port from
LEGACY = 5555                   # the port "adb tcpip 5555" uses (plain adb, no TLS)
NOT_TLS = {"WRONG_VERSION_NUMBER", "UNKNOWN_PROTOCOL", "HTTP_REQUEST", "HTTPS_PROXY_REQUEST", "PACKET_LENGTH_TOO_LONG"}
BATCH = 400                     # connections tried at once per worker (Windows' select() allows 512)
WORKERS = 8


def _open_in(host: str, ports: List[int], timeout: float) -> List[int]:
    """The ports among ``ports`` that accept a connection within ``timeout`` seconds."""
    found: List[int] = []
    selector = selectors.DefaultSelector()
    sockets = []
    try:
        for port in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setblocking(False)
            try:
                s.connect_ex((host, port))
            except OSError:
                s.close()
                continue
            sockets.append(s)
            selector.register(s, selectors.EVENT_WRITE, port)
        end = time.monotonic() + timeout
        left = len(sockets)
        while left and time.monotonic() < end:
            for key, _events in selector.select(max(0.0, end - time.monotonic())):
                s = key.fileobj
                if s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:      # writable and no error: it connected
                    found.append(key.data)
                selector.unregister(s)
                left -= 1
    finally:
        selector.close()
        for s in sockets:
            s.close()
    return found


def open_ports(host: str, ports: List[int], timeout: float = 0.5) -> List[int]:
    """The ports of ``host`` that accept a connection, found with many attempts in parallel (a few seconds for the
    whole range: a phone's firewall drops the others instead of refusing, so each batch waits out ``timeout``)."""
    chunks = [ports[i:i + BATCH] for i in range(0, len(ports), BATCH)]
    with ThreadPoolExecutor(WORKERS) as pool:
        return sorted(p for found in pool.map(lambda chunk: _open_in(host, chunk, timeout), chunks) for p in found)


def speaks_tls(host: str, port: int, timeout: float = 1.5) -> bool:
    """True when the port answers a TLS handshake (right away, even if it then refuses us because we have no
    certificate). adb's wireless ports do; most other things on a phone do not answer at all."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2          # adb's wireless debugging uses TLS 1.3; nothing older
    # Nothing is sent or trusted here: the handshake only shows whether the port answers in TLS. The phone's
    # certificate is self-signed, so it cannot be verified (and is not used for anything).
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            raw.settimeout(timeout)
            context.wrap_socket(raw, server_hostname=host).close()
        return True
    except ssl.SSLError as err:
        # a TLS server that says no to us (it closes, or wants a certificate) is the one we look for; a service that
        # answers in something else (HTTP, SSH ...) is not
        return getattr(err, "reason", "") not in NOT_TLS
    except OSError:
        # a refused or dropped connection, or no answer in time (a TimeoutError is an OSError): not a TLS server
        return False


def candidates(host: str) -> List[int]:
    """Ports of ``host`` that could be its adb: those that speak TLS (Wireless debugging), then the legacy port 5555
    when it is open. Other open ports are left out (adb would wait ten seconds on each). Empty when the phone is off,
    or Wireless debugging is."""
    ports = open_ports(host, [LEGACY] + list(range(LOW, HIGH + 1)))
    with ThreadPoolExecutor(WORKERS) as pool:
        tls = dict(zip(ports, pool.map(lambda p: speaks_tls(host, p), ports)))
    return sorted((p for p in ports if tls[p] or p == LEGACY), key=lambda p: (p == LEGACY, p))
