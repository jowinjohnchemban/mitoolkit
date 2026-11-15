"""
The RSA key adb uses to identify this computer to a phone.

It is the same file Google's adb uses, ``~/.android/adbkey`` (or $ANDROID_USER_HOME), so a
phone that already trusts this computer for adb trusts miunlock too, and the other way
round. If the file does not exist, a new 2048-bit key is made and saved there, readable
only by you. The key never leaves this computer; only its public half goes to the phone,
over USB, when you are asked to allow USB debugging.

Pure Python (no extra package). RSA here is only adb's challenge signature: PKCS#1 v1.5
over the phone's 20-byte token, treated as a SHA-1 digest, exactly as adb does.
"""
from __future__ import annotations

import base64
import math
import os
import secrets
import socket
import struct
from pathlib import Path
from typing import List, Optional, Tuple

_SHA1_DIGESTINFO = bytes.fromhex("3021300906052b0e03021a05000414")
_RSA_OID = bytes.fromhex("2a864886f70d010101")
_SMALL_PRIMES = [p for p in range(3, 2000, 2) if all(p % d for d in range(3, int(p ** 0.5) + 1, 2))]


def key_dir() -> Path:
    home = os.environ.get("ANDROID_USER_HOME")
    return Path(home) if home else Path.home() / ".android"


# ------------------------------------------------------------------- DER (minimal)
def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _der(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(body)) + body


def _der_int(v: int) -> bytes:
    return _der(0x02, v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big"))


def _der_read(buf: bytes, pos: int) -> Tuple[int, bytes, int]:
    tag, length = buf[pos], buf[pos + 1]
    pos += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(buf[pos:pos + n], "big")
        pos += n
    return tag, buf[pos:pos + length], pos + length


def _der_items(body: bytes) -> List[Tuple[int, bytes]]:
    items, pos = [], 0
    while pos < len(body):
        tag, value, pos = _der_read(body, pos)
        items.append((tag, value))
    return items


# --------------------------------------------------------------------------- keys
class Key:
    def __init__(self, n: int, e: int, d: int, p: int, q: int):
        self.n, self.e, self.d, self.p, self.q = n, e, d, p, q
        self.size = (n.bit_length() + 7) // 8

    def sign_token(self, token: bytes) -> bytes:
        """adb's AUTH signature: PKCS#1 v1.5, SHA-1 DigestInfo, token used as the digest."""
        t = _SHA1_DIGESTINFO + token
        if self.size < len(t) + 11:
            raise ValueError("key too small")
        em = b"\x00\x01" + b"\xff" * (self.size - len(t) - 3) + b"\x00" + t
        m = int.from_bytes(em, "big")
        # CRT for speed
        dp, dq, qinv = self.d % (self.p - 1), self.d % (self.q - 1), pow(self.q, -1, self.p)
        m1, m2 = pow(m, dp, self.p), pow(m, dq, self.q)
        s = (m2 + self.q * ((qinv * (m1 - m2)) % self.p)) % self.n
        return s.to_bytes(self.size, "big")

    def adb_public_key(self) -> bytes:
        """The public key in adb's own format, as sent to the phone (NUL-terminated)."""
        if self.n.bit_length() > 2048:
            raise ValueError("adb keys are 2048-bit")
        n0inv = (-pow(self.n % (1 << 32), -1, 1 << 32)) % (1 << 32)
        rr = pow(2, 4096, self.n)
        blob = (struct.pack("<II", 64, n0inv) + self.n.to_bytes(256, "little")
                + rr.to_bytes(256, "little") + struct.pack("<I", self.e))
        try:
            host = socket.gethostname() or "computer"
        except OSError:
            host = "computer"
        return base64.b64encode(blob) + f" miunlock@{host}".encode() + b"\x00"

    def to_pem(self) -> str:
        """PKCS#8 PEM, the format Google's adb writes."""
        p, q, d = self.p, self.q, self.d
        rsa = _der(0x30, b"".join(_der_int(x) for x in
                                  (0, self.n, self.e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))))
        alg = _der(0x30, _der(0x06, _RSA_OID) + b"\x05\x00")
        der = _der(0x30, _der_int(0) + alg + _der(0x04, rsa))
        b64 = base64.b64encode(der).decode()
        lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
        return "-----BEGIN PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END PRIVATE KEY-----\n"


def from_pem(text: str) -> Key:
    """Read a PKCS#8 ("PRIVATE KEY") or PKCS#1 ("RSA PRIVATE KEY") PEM RSA key."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    der = base64.b64decode("".join(ln for ln in lines if not ln.startswith("-----")))
    _tag, body, _ = _der_read(der, 0)
    items = _der_items(body)
    if len(items) >= 3 and items[2][0] == 0x04:  # PKCS#8: version, algorithm, key
        _tag, body, _ = _der_read(items[2][1], 0)
        items = _der_items(body)
    ints = [int.from_bytes(v, "big") for t, v in items if t == 0x02]
    if len(ints) < 6:
        raise ValueError("not an RSA private key")
    _version, n, e, d, p, q = ints[:6]
    return Key(n, e, d, p, q)


def _probable_prime(n: int, rounds: int = 40) -> bool:
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int, e: int) -> int:
    while True:
        c = secrets.randbits(bits) | (3 << (bits - 2)) | 1  # top two bits set: n gets the full size
        if math.gcd(c - 1, e) == 1 and _probable_prime(c):
            return c


def generate(bits: int = 2048) -> Key:
    e = 65537
    while True:
        p, q = _prime(bits // 2, e), _prime(bits // 2, e)
        if p == q:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        d = pow(e, -1, (p - 1) * (q - 1) // math.gcd(p - 1, q - 1))
        return Key(n, e, d, p, q)


def _write_private(path: Path, text: str) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(text)


_cached: Optional[Key] = None


def load_or_create() -> Key:
    """This computer's adb key, made on first use."""
    global _cached
    if _cached is not None:
        return _cached
    folder = key_dir()
    path = folder / "adbkey"
    if path.exists():
        _cached = from_pem(path.read_text(encoding="ascii"))
        return _cached
    folder.mkdir(parents=True, exist_ok=True)
    key = generate()
    _write_private(path, key.to_pem())
    (folder / "adbkey.pub").write_bytes(key.adb_public_key().rstrip(b"\x00") + b"\n")
    _cached = key
    return key
