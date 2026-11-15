"""Logging to ``miunlock.log`` next to the program.

The log is for diagnosing problems and for bug reports, so it records what
happened (steps, result codes, error types) and never secrets. Messages pass
through a scrubber that hides token-like values even if one slips into a message.
The file is restricted to your user account and rotated at 512 KB, keeping three
old copies.

Location: the folder of the executable when running a built program, otherwise
the current directory. If that folder is not writable, logging to a file is
skipped and the program carries on.
"""
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from miunlock.auth.store import restrict_to_current_user

NAME = "miunlock.log"
_log = logging.getLogger("miunlock")
_path: Optional[Path] = None

_SECRET_FIELD = re.compile(
    r"(?i)\b(passToken|serviceToken|ssecurity|nonce|userId|deviceId|encryptData|deviceToken|"
    r"cUserId|token|password|ticket|sign|location)\b(['\"]?\s*[:=]\s*['\"]?)[^\s,'\"}\])]+"
)
_LONG_BLOB = re.compile(r"[A-Za-z0-9+/=_\-]{32,}")


class Scrubber(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        text = record.getMessage()
        text = _SECRET_FIELD.sub(r"\1\2<hidden>", text)
        text = _LONG_BLOB.sub("<hidden>", text)
        record.msg, record.args = text, None
        return True


def log_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def log_path() -> Optional[Path]:
    """Where the log is being written, or None if file logging is off."""
    return _path


def env_debug() -> bool:
    """True when MIUNLOCK_DEBUG is set to anything but 0/false/off."""
    return os.environ.get("MIUNLOCK_DEBUG", "").strip().lower() not in ("", "0", "false", "off", "no")


def set_debug(on: bool) -> None:
    """Debug mode: also write what the program does step by step (each adb and fastboot request with how
    long it took, scans, connections). Secrets are still scrubbed. Off by default: it makes the log larger."""
    _log.setLevel(logging.DEBUG if on else logging.INFO)
    _log.info("Debug logging %s", "on" if on else "off")


def debug_enabled() -> bool:
    return _log.isEnabledFor(logging.DEBUG)


def setup(verbose: Optional[bool] = None) -> Optional[Path]:
    """Start file logging once. Safe to call repeatedly. ``verbose`` (debug mode) defaults to the
    MIUNLOCK_DEBUG environment variable."""
    global _path
    if _path is not None:
        return _path
    verbose = env_debug() if verbose is None else verbose
    _log.setLevel(logging.DEBUG if verbose else logging.INFO)
    _log.propagate = False
    path = log_dir() / NAME
    try:
        handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
    except OSError:
        return None  # read-only folder: run without a log file
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    handler.addFilter(Scrubber())
    _log.addHandler(handler)
    restrict_to_current_user(path)
    _path = path
    from miunlock import build
    _log.info("miunlock %s started (python %s, %s)", build.full_version(), sys.version.split()[0], sys.platform)
    return path


def get(name: str = "") -> logging.Logger:
    return _log.getChild(name) if name else _log
