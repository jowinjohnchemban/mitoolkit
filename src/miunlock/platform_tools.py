"""
Finding Google's adb and fastboot programs if they are already installed.

miunlock never downloads them; it has its own adb and fastboot. They are only used as a
fallback, when they are present and work better on this computer (see fastboot.AutoBackend
and adb_server.py).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

_EXE = ".exe" if sys.platform == "win32" else ""


def _candidate_dirs() -> List[Path]:
    dirs = []
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            dirs.append(Path(os.environ[var]) / "platform-tools")
    home = Path.home()
    dirs += [home / "platform-tools", home / "Android" / "Sdk" / "platform-tools",
             home / "Library" / "Android" / "sdk" / "platform-tools"]
    if os.environ.get("LOCALAPPDATA"):
        dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "platform-tools")
    return dirs


def find(name: str) -> Optional[str]:
    """Full path of Google's ``adb`` or ``fastboot`` if installed, else None."""
    on_path = shutil.which(name)
    if on_path:
        return on_path
    # next to a running or installed adb (fastboot ships in the same folder)
    adb = shutil.which("adb")
    dirs = ([Path(adb).parent] if adb else []) + _candidate_dirs()
    for folder in dirs:
        exe = folder / (name + _EXE)
        if exe.is_file():
            return str(exe)
    return None
