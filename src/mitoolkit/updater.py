"""Updating mitoolkit over the air: find a newer release on GitHub, download it, check it, swap it in.

* Where from: this project's GitHub Releases, only. A download link that points anywhere else is refused.
* Check: the program is compared with the SHA-256 listed in the release's ``SHA256SUMS.txt`` before it is
  installed. That catches damaged or incomplete downloads. It cannot prove who published the release (the
  programs are not code-signed), which is why updates are never installed without the person pressing the button.
* Who can self-update: the single-file programs from the Releases page. A pip or source install is told how
  to update instead, because replacing files inside a Python environment is not this program's job.
* How the swap works: the new program is saved next to the running one, the running one is renamed to
  ``.old`` (Windows cannot overwrite a program that is running), the new one takes its name, and mitoolkit
  starts it. The ``.old`` file is removed the next time the program starts.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import requests

from mitoolkit import __version__, settings
from mitoolkit.errors import MitoolkitError

REPO = "jowinjohnchemban/mitoolkit"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
SUMS = "SHA256SUMS.txt"
CHECK_EVERY_S = 24 * 3600


class UpdateError(MitoolkitError):
    pass


@dataclass
class Release:
    tag: str
    version: Tuple[int, ...]
    notes: str
    page: str
    assets: Dict[str, str] = field(default_factory=dict)       # file name -> download address


def parse_version(text: str) -> Optional[Tuple[int, ...]]:
    """"v1.8.1" -> (1, 8, 1); None when it is not a plain major.minor.patch."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(release: Release, current: str = __version__) -> bool:
    mine = parse_version(current)
    return mine is not None and release.version > mine


def latest(timeout: float = 10.0) -> Release:
    """The newest release published on GitHub. Sends nothing about you or the phone."""
    try:
        reply = requests.get(API, timeout=timeout, headers={"Accept": "application/vnd.github+json",
                                                            "User-Agent": "mitoolkit-updater"})
        reply.raise_for_status()
        data = reply.json()
    except (requests.RequestException, ValueError) as err:
        raise UpdateError(f"Could not reach GitHub to look for updates ({err.__class__.__name__}).") from None
    version = parse_version(str(data.get("tag_name", "")))
    if version is None:
        raise UpdateError("GitHub's latest release has a version number mitoolkit does not understand.")
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])
              if str(a.get("browser_download_url", "")).startswith(DOWNLOADS)}
    return Release(str(data["tag_name"]), version, str(data.get("body") or "").strip(),
                   str(data.get("html_url") or f"https://github.com/{REPO}/releases"), assets)


# ----------------------------------------------------------------- which file, and can we replace ourselves
def asset_name() -> Optional[str]:
    """The release file made for this system, or None when there is none."""
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in ("amd64", "x86_64"):
        return "mitoolkit-windows-x64.exe"
    if sys.platform.startswith("linux") and machine in ("x86_64", "amd64"):
        return "mitoolkit-linux-x64"
    if sys.platform == "darwin" and machine in ("arm64", "aarch64"):
        return "mitoolkit-macos-arm64"
    return None


def running_program() -> Optional[Path]:
    """The single-file program that is running, or None (a Python install or a source checkout)."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def can_self_update() -> bool:
    exe = running_program()
    return exe is not None and asset_name() is not None and os.access(exe.parent, os.W_OK)


# ------------------------------------------------------------------------------ download and check
def checksum_for(sums_text: str, name: str) -> Optional[str]:
    """The SHA-256 listed for ``name`` in a sha256sum file ("hash  name" per line)."""
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _get_text(url: str, timeout: float) -> str:
    try:
        reply = requests.get(url, timeout=timeout, headers={"User-Agent": "mitoolkit-updater"})
        reply.raise_for_status()
        return reply.text
    except requests.RequestException as err:
        raise UpdateError(f"Could not download {url.rsplit('/', 1)[-1]} ({err.__class__.__name__}).") from None


def download(release: Release, dest: Path, progress: Callable[[int, int], None] = lambda _d, _t: None,
             cancel: Optional[threading.Event] = None) -> Path:
    """Download this system's program from the release to ``dest`` and check it against SHA256SUMS.txt.
    ``dest`` is removed again if anything is wrong. progress(done, total) is called as it goes."""
    name = asset_name()
    if name is None or name not in release.assets:
        raise UpdateError("This release has no program for this system. Download it from the release page.")
    if SUMS not in release.assets:
        raise UpdateError("This release has no SHA256SUMS.txt, so the download cannot be checked.")
    expected = checksum_for(_get_text(release.assets[SUMS], 15), name)
    if expected is None:
        raise UpdateError("SHA256SUMS.txt does not list this program.")
    try:
        with requests.get(release.assets[name], stream=True, timeout=20,
                          headers={"User-Agent": "mitoolkit-updater"}) as reply:
            reply.raise_for_status()
            total, done = int(reply.headers.get("Content-Length") or 0), 0
            with open(dest, "wb") as out:
                for block in reply.iter_content(1 << 16):
                    if cancel is not None and cancel.is_set():
                        raise UpdateError("Cancelled.")
                    out.write(block)
                    done += len(block)
                    progress(done, total)
        if sha256(dest) != expected:
            raise UpdateError("The download does not match its checksum, so it was not installed.")
    except requests.RequestException as err:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"The download stopped ({err.__class__.__name__}).") from None
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return dest


# ------------------------------------------------------------------------------------------- the swap
def old_copy(exe: Path) -> Path:
    return exe.with_name(exe.name + ".old")


def install(new_file: Path, exe: Optional[Path] = None) -> Path:
    """Put ``new_file`` in place of the running program ``exe``. Returns the program's path. If the swap
    fails half way the old program is put back."""
    exe = exe or running_program()
    if exe is None:
        raise UpdateError("Only the single-file program can update itself.")
    old = old_copy(exe)
    old.unlink(missing_ok=True)
    if sys.platform != "win32":
        new_file.chmod(0o755)
    try:
        os.replace(exe, old)
        os.replace(new_file, exe)
    except OSError as err:
        if old.exists() and not exe.exists():
            os.replace(old, exe)
        new_file.unlink(missing_ok=True)
        raise UpdateError(f"Could not replace the program ({err}).") from None
    return exe


def cleanup() -> None:
    """At start-up: remove the copy a previous update left behind."""
    exe = running_program()
    if exe is not None:
        try:
            old_copy(exe).unlink(missing_ok=True)
        except OSError:
            pass


def restart(exe: Path) -> None:
    """Start the new program. The caller then closes this one."""
    kwargs = {"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}
    subprocess.Popen([str(exe)], close_fds=True, **kwargs)


# ------------------------------------------------------------------------- automatic check (once a day)
def auto_enabled() -> bool:
    return bool(settings.get("auto_update_check", True))


def check_due(now: Optional[float] = None) -> bool:
    return auto_enabled() and (now or time.time()) - float(settings.get("update_checked", 0)) >= CHECK_EVERY_S


def mark_checked(now: Optional[float] = None) -> None:
    settings.set("update_checked", now or time.time())
