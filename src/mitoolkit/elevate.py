"""Running one of this program's own fixes again with administrator rights, only when a person has chosen it.

Windows asks through UAC, Linux through polkit (pkexec, or sudo in a terminal), macOS through the system's
administrator prompt. The person sees the system's own dialog and can say no. Nothing is elevated without
that, and what runs is always this program with a fixed fix name (see doctor.PRIVILEGED): never a command
built from outside input.

The elevated copy reports back through a small result file, because an elevated process's output cannot be read.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

WAIT_S = 180            # time to answer the system's prompt and for the fix to run


def is_admin() -> bool:
    """True if this process already has administrator (root) rights."""
    try:
        if os.name == "nt":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def program_command() -> List[str]:
    """How to start this program again: the single-file program, or Python running the package."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "mitoolkit"]


def _result(path: Path, code: int) -> Tuple[bool, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("ok")), str(data.get("message", ""))
    except (OSError, ValueError):
        return code == 0, "" if code == 0 else "The administrator step did not finish."


def run_self(args: List[str], timeout: int = WAIT_S) -> Tuple[bool, str]:
    """Run ``mitoolkit <args>`` as administrator and wait. Returns (worked, what it said). A person who
    declines the system's prompt gets (False, "...not given...")."""
    fd, name = tempfile.mkstemp(prefix="mitoolkit-fix-", suffix=".json")
    os.close(fd)
    result = Path(name)
    command = program_command() + list(args) + ["--result-file", name]
    try:
        if os.name == "nt":
            code = _windows(command, timeout)
        elif sys.platform == "darwin":
            code = _macos(command, timeout)
        else:
            code = _posix(command, timeout)
        if code is None:
            return False, "Administrator permission was not given, so nothing was changed."
        return _result(result, code)
    finally:
        result.unlink(missing_ok=True)


def _windows(command: List[str], timeout: int, verb: str = "runas"):
    """UAC through ShellExecuteEx ("runas"). None if the person declined. (``verb`` is "runas" in real use; a test
    uses "open" to check the plumbing without a prompt.)"""
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40                                   # SEE_MASK_NOCLOSEPROCESS: keep the handle to wait on
    info.lpVerb = verb
    info.lpFile = command[0]
    info.lpParameters = subprocess.list2cmdline(command[1:])
    info.nShow = 0                                      # SW_HIDE
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        return None                                     # ERROR_CANCELLED (1223): the person said no
    try:
        kernel32.WaitForSingleObject(info.hProcess, timeout * 1000)
        code = wintypes.DWORD(1)
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return int(code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)


def _posix(command: List[str], timeout: int):
    """polkit's pkexec when there is a desktop session, else sudo (it asks in the terminal)."""
    launcher = ["pkexec"] if shutil.which("pkexec") and os.environ.get("DISPLAY") else ["sudo"]
    if launcher == ["sudo"] and not shutil.which("sudo"):
        return None
    done = subprocess.run(launcher + command, timeout=timeout)
    return None if done.returncode in (126, 127) and launcher == ["pkexec"] else done.returncode   # 126/127: declined


def _macos(command: List[str], timeout: int):
    """The system's administrator prompt through AppleScript."""
    quoted = shlex.join(command).replace("\\", "\\\\").replace('"', '\\"')
    done = subprocess.run(["osascript", "-e", f'do shell script "{quoted}" with administrator privileges'],
                          capture_output=True, text=True, timeout=timeout)
    if "User canceled" in done.stderr:
        return None
    return done.returncode
