"""What the two ways of reaching a phone share: the adb error type and adb's file transfer session.

adb_usb.py (mitoolkit's own USB client) and adb_server.py (Google's adb server) both build on this, and
neither imports the other's code at module level this way: keeping the shared parts here keeps the import
graph one-directional.
"""
from __future__ import annotations

import os
import stat
import struct
import threading
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

from mitoolkit.errors import MitoolkitError


class AdbError(MitoolkitError):
    """str(e) is human-readable."""


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
