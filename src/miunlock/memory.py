"""Housekeeping: keep the program's memory and resources tidy while it runs for hours.

- A full garbage collection after start-up, then gc.freeze() so the long-lived start-up objects are
  not scanned again by every later collection (cheaper collections, nothing is lost).
- A light collection every 30 seconds and a full one every 5 minutes, because windows, charts and
  threads leave reference cycles that Python only frees when it collects.
- collect_soon(): a full collection right after a window closes, so its charts, images and data go
  away at once, not eventually.
- If the program's memory grows past a limit, drop the caches that can be rebuilt (chart images)
  and collect, and say so in the log.

Nothing here touches the phone or the window from another thread.
"""
from __future__ import annotations

import gc
import os
import sys
from typing import Callable, List, Optional

from miunlock import log

LIGHT_EVERY_MS = 30_000
FULL_EVERY_MS = 300_000
LIMIT_MB = 500


def rss_mb() -> Optional[float]:
    """The program's resident memory in megabytes, or None if the system won't say."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            # the handle is a 64-bit pseudo handle (-1): without argtypes ctypes would pass it as a 32-bit int
            kernel.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            kernel.K32GetProcessMemoryInfo.restype = wintypes.BOOL
            ok = kernel.K32GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
            return counters.WorkingSetSize / 1048576 if ok else None
        if sys.platform.startswith("linux"):
            with open("/proc/self/statm") as f:
                return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss      # macOS reports bytes, Linux kilobytes
        return peak / 1048576 if sys.platform == "darwin" else peak / 1024
    except Exception:
        return None


def collect() -> int:
    """A full garbage collection; returns how many objects it freed."""
    return gc.collect()


def collect_soon(widget) -> None:
    """Collect once the window has finished closing (call right after destroying a window)."""
    try:
        widget.after_idle(collect)
    except Exception:
        collect()


class Housekeeper:
    """Runs the periodic tidying on the window's own timer."""

    def __init__(self, root, release: Optional[List[Callable[[], None]]] = None, limit_mb: float = LIMIT_MB):
        self.root, self.limit_mb = root, limit_mb
        self.release = list(release or [])      # things that can be dropped and rebuilt on demand
        self._ticks = 0
        self._over = False
        self._job: Optional[str] = None

    def start(self) -> None:
        collect()
        gc.freeze()                              # the start-up objects live as long as the program
        self._job = self.root.after(LIGHT_EVERY_MS, self._tick)

    def stop(self) -> None:
        if self._job is not None:
            try:
                self.root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _tick(self) -> None:
        self._ticks += 1
        try:
            if self._ticks % (FULL_EVERY_MS // LIGHT_EVERY_MS) == 0:
                collect()
            else:
                gc.collect(1)
            self.check_memory()
        finally:
            try:
                self._job = self.root.after(LIGHT_EVERY_MS, self._tick)
            except Exception:
                self._job = None

    def check_memory(self) -> Optional[float]:
        """If memory is high, release what can be rebuilt and collect (once per episode in the log)."""
        used = rss_mb()
        if used is None:
            return None
        if used > self.limit_mb:
            for drop in self.release:
                try:
                    drop()
                except Exception:
                    log.get("memory").exception("Could not release a cache")
            freed = collect()
            if not self._over:
                log.get("memory").warning("Memory use is %.0f MB (limit %.0f). Released caches; collected %d objects.",
                                          used, self.limit_mb, freed)
            self._over = True
        else:
            self._over = False
        return used
