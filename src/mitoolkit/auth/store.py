"""Where the saved Mi Account session lives, and how it is protected.

The session holds a long-lived ``passToken``, so it is stored in the strongest
place the system offers, tried in this order:

1. The operating system's credential store (Windows Credential Manager, macOS
   Keychain, Linux Secret Service) through the optional ``keyring`` package.
2. Windows only: a file encrypted with DPAPI, which only your Windows account can
   decrypt (no extra package needed).
3. A plain JSON file readable only by your user (mode 0600, or an NTFS ACL).

``save`` returns which one was used so the caller can tell the user honestly.
"""
import json
import os
import platform
import stat
import subprocess
import time
from pathlib import Path
from typing import Optional

SERVICE = "mitoolkit"
STAMP = "_saved_at"
DEFAULT_TTL_HOURS = 24.0
ROOT = Path.home() / ".mitoolkitsession"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

KEYRING = "OS credential store"
DPAPI = "encrypted with Windows DPAPI"
FILE = "owner-only file"
FILE_OPEN = "file (could not restrict permissions)"


def _dir(sid: str) -> Path:
    return ROOT / sid


# ----------------------------------------------------------------------- TTL
def ttl_seconds() -> float:
    """How long a saved session is trusted. ``MITOOLKIT_SESSION_TTL_HOURS`` overrides it
    (0 means never save for reuse: every run logs in again)."""
    try:
        hours = float(os.environ.get("MITOOLKIT_SESSION_TTL_HOURS", DEFAULT_TTL_HOURS))
    except ValueError:
        hours = DEFAULT_TTL_HOURS
    return max(hours, 0.0) * 3600


def _fresh(data: dict) -> bool:
    try:
        return 0 <= time.time() - float(data[STAMP]) < ttl_seconds()
    except (KeyError, TypeError, ValueError):
        return False  # no timestamp (older version): treat as expired


# ---------------------------------------------------------------- permissions
def restrict_to_current_user(path: Path) -> bool:
    """Limit a file or folder to the current user. True only if it was applied."""
    try:
        if platform.system() == "Windows":
            user = os.environ.get("USERNAME")
            if not user:
                return False
            grant = f"{user}:(OI)(CI)F" if path.is_dir() else f"{user}:F"
            result = subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", grant],
                capture_output=True, text=True, check=False, creationflags=_NO_WINDOW,
            )
            return result.returncode == 0
        os.chmod(path, stat.S_IRWXU if path.is_dir() else stat.S_IRUSR | stat.S_IWUSR)
        return True
    except Exception:
        return False


def _write_private(path: Path, payload: bytes) -> bool:
    """Write a file that is never readable by other users, not even briefly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = restrict_to_current_user(path.parent)
    if os.name == "nt":
        path.write_bytes(payload)
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
    return restrict_to_current_user(path) and safe


# ------------------------------------------------------------------- keyring
def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


# --------------------------------------------------------------------- DPAPI
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# --------------------------------------------------------------- public API
def save(sid: str, data: dict) -> str:
    """Store the session and return how it is protected (one of the constants)."""
    raw = json.dumps({**data, STAMP: time.time()}).encode("utf-8")
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, sid, raw.decode("utf-8"))
            delete_files(sid)  # never leave an older copy on disk
            return KEYRING
        except Exception:
            pass  # e.g. value too large or store locked: fall through
    if os.name == "nt":
        try:
            _write_private(_dir(sid) / "session.dpapi", _dpapi(raw, True))
            (_dir(sid) / "session.json").unlink(missing_ok=True)
            return DPAPI  # encrypted even if the extra ACL step failed
        except Exception:
            pass
    ok = _write_private(_dir(sid) / "session.json", raw)
    return FILE if ok else FILE_OPEN


def load(sid: str) -> Optional[dict]:
    """Return the saved session, or None if there is none or it has expired.

    An expired session is deleted, and so is any session without a timestamp (saved by
    an older version).
    """
    data = _load_raw(sid)
    if data is None:
        return None
    if not _fresh(data):
        delete(sid)
        return None
    data.pop(STAMP, None)
    return data


def _load_raw(sid: str) -> Optional[dict]:
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, sid)
            if value:
                return json.loads(value)
        except Exception:
            pass
    enc = _dir(sid) / "session.dpapi"
    if os.name == "nt" and enc.exists():
        try:
            return json.loads(_dpapi(enc.read_bytes(), False))
        except Exception:
            enc.unlink(missing_ok=True)
            return None
    plain = _dir(sid) / "session.json"
    if plain.exists():
        try:
            return json.loads(plain.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            plain.unlink(missing_ok=True)
            return None
    return None


def delete_files(sid: str) -> None:
    for name in ("session.json", "session.dpapi"):
        try:
            (_dir(sid) / name).unlink(missing_ok=True)
        except OSError:
            pass


def delete(sid: str) -> None:
    """Remove the session from every place it could be."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, sid)
        except Exception:
            pass
    delete_files(sid)


def delete_all() -> None:
    """Forget every saved session (used by sign out)."""
    for sid in ("passport", "unlockApi"):
        delete(sid)
    if ROOT.exists():
        import shutil
        shutil.rmtree(ROOT, ignore_errors=True)
