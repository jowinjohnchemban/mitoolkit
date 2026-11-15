"""Keeping the program safe: nothing a phone, a cable or a driver does should freeze or crash it.

Three guards:

- call_with_timeout(): run a call that talks to the phone on a helper thread and stop waiting for it
  after a deadline, so one stuck USB read can't hang a screen for ever.
- UiWatchdog: a heartbeat from the window's own event loop. A second thread checks it; if the window
  stops answering for a few seconds it writes what every thread is doing to the log file (that is
  what tells us what froze), and writes a line when it recovers.
- install_crash_logging(): errors in background threads, and hard crashes of the interpreter, are
  written to the log file instead of vanishing.

The log never holds tokens (see log.py). The watchdog only watches and records: it never touches the
window from its thread (Tk is not thread safe).
"""
from __future__ import annotations

import faulthandler
import sys
import threading
import time
import traceback
from typing import Callable, Optional, TextIO, TypeVar

from mitoolkit import log

T = TypeVar("T")


class Stalled(TimeoutError):
    """A call to the phone did not finish in time."""


def call_with_timeout(fn: Callable[[], T], seconds: float, what: str = "the phone") -> T:
    """Run fn() and return its result, or raise Stalled if it takes longer than `seconds`.

    fn runs on a daemon helper thread. If it never returns, that thread is abandoned (it ends with the
    program) and the caller carries on, which is the point: a blocked USB read can't be interrupted from
    outside, but it no longer blocks anything that matters.
    """
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except (Exception, SystemExit, KeyboardInterrupt) as err:  # handed to the caller below, with its traceback
            box["error"] = err

    worker = threading.Thread(target=run, daemon=True, name=f"call:{what}")
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise Stalled(f"{what.capitalize()} did not answer in {seconds:g} seconds.")
    if "error" in box:
        raise box["error"]
    return box["value"]


class UiWatchdog:
    """Watches that the window keeps handling events. Start it once the window exists."""

    def __init__(self, root, warn_after: float = 4.0, check_every: float = 1.0,
                 on_stall: Optional[Callable[[float], None]] = None, clock: Callable[[], float] = time.monotonic):
        self.root, self.warn_after, self.check_every, self.clock = root, warn_after, check_every, clock
        self.on_stall = on_stall
        self._beat = clock()
        self._stalled_since: Optional[float] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.stalls = 0

    # ---- on the window's thread
    def start(self) -> None:
        self._beat = self.clock()
        self._pulse()
        self._thread = threading.Thread(target=self._watch, daemon=True, name="ui-watchdog")
        self._thread.start()

    def _pulse(self) -> None:
        self._beat = self.clock()
        if not self._stop.is_set():
            try:
                self.root.after(250, self._pulse)
            except Exception:  # the window is closing
                self._stop.set()

    def stop(self) -> None:
        self._stop.set()

    # ---- on the watchdog's own thread
    def _watch(self) -> None:
        while not self._stop.wait(self.check_every):
            self.check()

    def check(self) -> None:
        """One look at the heartbeat (also called directly by tests)."""
        behind = self.clock() - self._beat
        if behind >= self.warn_after and self._stalled_since is None:
            self._stalled_since = self._beat
            self.stalls += 1
            log.get("watchdog").warning("The window has not answered for %.0f s. What every thread is doing:\n%s",
                                        behind, thread_stacks())
            if self.on_stall:
                self.on_stall(behind)
        elif behind < self.warn_after and self._stalled_since is not None:
            log.get("watchdog").info("The window answers again after %.1f s.", self.clock() - self._stalled_since)
            self._stalled_since = None


def thread_stacks() -> str:
    """The current stack of every thread, as text (for the log when something stalls)."""
    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for ident, frame in sys._current_frames().items():
        out.append(f"--- {names.get(ident, ident)} ---\n" + "".join(traceback.format_stack(frame)[-8:]))
    return "\n".join(out)


_crash_file: Optional[TextIO] = None


def install_crash_logging() -> None:
    """Write background-thread errors and hard crashes to the log file."""
    global _crash_file
    path = log.log_path()
    if path is not None and _crash_file is None:
        try:
            _crash_file = open(path.with_name("crash.log"), "a", encoding="utf-8")
            faulthandler.enable(file=_crash_file, all_threads=True)  # a crash of the interpreter itself
        except Exception:
            _crash_file = None

    def thread_hook(args) -> None:
        if args.exc_type is SystemExit:
            return
        log.get("thread").error("Error in thread %s: %s", getattr(args.thread, "name", "?"),
                                "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    threading.excepthook = thread_hook
