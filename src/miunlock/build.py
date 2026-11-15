"""The version as shown to people: ``v1.8.0 (build: 15112026-8ae71a1)``.

``1.8.0`` is major.minor.patch (``miunlock.__version__``). The build is the date of the commit the
program was made from, as DDMMYYYY, and that commit's short id, so a bug report names the exact code.

Release builds read them from ``miunlock/_build.py``, which the release workflow writes just before
building. A program run from a git checkout asks git. Anywhere else (an install from a source archive) only
``v1.8.0`` is shown.
"""
from __future__ import annotations

import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

from miunlock import __version__


@lru_cache(maxsize=1)
def info() -> Optional[Tuple[str, str]]:
    """(DDMMYYYY, commit id) of this build, or None when it is not known."""
    try:
        from miunlock import _build  # written by the release workflow
        return str(_build.DATE), str(_build.COMMIT)
    except (ImportError, AttributeError):
        pass
    if getattr(sys, "frozen", False):
        return None
    return _from_git(Path(__file__).resolve().parent)


def _from_git(folder: Path) -> Optional[Tuple[str, str]]:
    try:
        from miunlock.system import NO_WINDOW
        out = subprocess.run(["git", "-C", str(folder), "log", "-1", "--format=%cd%n%h", "--date=format:%d%m%Y"],
                             capture_output=True, text=True, timeout=3, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = out.stdout.split()
    if out.returncode != 0 or len(lines) != 2:
        return None
    return lines[0], lines[1]


def full_version() -> str:
    """``v1.8.0 (build: 15112026-8ae71a1)``, or ``v1.8.0`` when the build is not known."""
    known = info()
    return f"v{__version__}" + (f" (build: {known[0]}-{known[1]})" if known else "")
