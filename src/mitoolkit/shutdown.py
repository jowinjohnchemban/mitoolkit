"""What MiToolkit puts away when it closes, so it never leaves the phone held behind it.

* the files it keeps open (the log file, crash.log) are flushed and closed, last of all;
* the AI agent connection (MCP in the app), if it is on, is stopped first, so no agent is using a phone while it closes;
* its own USB connections to phones (adb) are closed;
* any Google ``fastboot`` it started and that is still running is stopped;
* the Google adb server it started (for Wi-Fi) is stopped. A server that was already running when MiToolkit
  began is left alone, because Android Studio or a terminal may be using it; set ``stop_any_adb_on_exit`` to true
  in ``~/.mitoolkit/settings.json`` to stop that one too, or ``stop_adb_on_exit`` to false to stop none.

It only looks at modules that were loaded (a run that never touched a phone has nothing to put away), runs once,
and never raises: closing the program must not fail because cleaning up did.
"""
from __future__ import annotations

import atexit
import sys
import threading
from typing import Callable, List

_done = threading.Event()


def _close_usb() -> str:
    module = sys.modules.get("mitoolkit.adb_usb")
    count = module.close_all() if module else 0
    return f"Closed {count} USB connection(s) to phones." if count else ""


def _stop_agents() -> str:
    """The AI agent connection (MCP in the app): agents lose it the moment the window closes."""
    module = sys.modules.get("mitoolkit.mcp_http")
    return module.stop_all() if module else ""


def _stop_fastboot() -> str:
    module = sys.modules.get("mitoolkit.fastboot")
    count = module.terminate_children() if module else 0
    return f"Stopped {count} running fastboot program(s)." if count else ""


def _stop_adb() -> str:
    module = sys.modules.get("mitoolkit.adb_server")
    if module is None:
        return ""
    from mitoolkit import settings
    if not settings.get("stop_adb_on_exit", True):
        return ""
    return module.stop_started(also_others=bool(settings.get("stop_any_adb_on_exit", False)))


def _close_files() -> None:
    """Close the files MiToolkit keeps open: crash.log, and the log file (flushed first). Done last, after the
    steps above have said what they did, so nothing is written to a log that is already closed."""
    import logging
    module = sys.modules.get("mitoolkit.watchdog")
    if module is not None:
        module.close_crash_log()
    logging.shutdown()          # flushes and closes every log handler, so the log file is released (Windows can then move it)


STEPS: List[Callable[[], str]] = [_stop_agents, _close_usb, _stop_fastboot, _stop_adb]


def run() -> List[str]:
    """Put everything away, once. Returns what was done."""
    if _done.is_set():
        return []
    _done.set()
    messages: List[str] = []
    for step in STEPS:
        try:
            message = step()
        except Exception as err:
            message = ""
            _log().debug("Closing step %s failed: %s", step.__name__, err)
        if message:
            messages.append(message)
            _log().info(message)
    try:
        _close_files()
    except Exception as err:             # the log may already be closed: say nothing, closing must not fail
        print(f"Could not close a file: {err}", file=sys.stderr)
    return messages


def register() -> None:
    """Run at exit, however the program ends normally (window closed, command finished, sys.exit)."""
    atexit.register(run)


def _log():
    from mitoolkit import log
    return log.get("shutdown")
