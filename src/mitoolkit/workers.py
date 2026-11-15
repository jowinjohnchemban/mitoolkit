"""A small pool of background threads for work that should not run on the window's thread.

Tk must only be touched from the window's own thread, so workers never draw: they compute (for
example render a chart image with Pillow) and hand the result back, and `Pump` delivers it to a
callback on the window's thread.

Why not concurrent.futures: its threads are not daemons, and Python waits for them when the program
exits, so one worker stuck in a USB call could keep mitoolkit from closing. These are daemon threads.

Jobs are best-effort: if the program closes with jobs queued they are simply dropped.
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable, List, Optional, Tuple

from mitoolkit import log


Callback = Callable[[Any, Optional[BaseException]], None]
Job = Tuple[Callable[[], Any], Callback]                       # what to run, and who to tell
Done = Tuple[Callback, Any, Optional[BaseException]]           # who to tell, the result, the error


class BackgroundPool:
    def __init__(self, workers: int = 2, name: str = "worker", max_waiting: int = 64):
        self._jobs: queue.Queue[Job] = queue.Queue(maxsize=max_waiting)
        self._done: queue.Queue[Done] = queue.Queue()
        self._threads: List[threading.Thread] = []
        for i in range(max(1, workers)):
            t = threading.Thread(target=self._work, daemon=True, name=f"{name}-{i + 1}")
            t.start()
            self._threads.append(t)

    def submit(self, fn: Callable[[], Any], callback: Callable[[Any, Optional[BaseException]], None]) -> bool:
        """Run fn() on a worker; callback(result, error) later, on whoever calls drain(). Returns False
        (and does nothing) if too many jobs are already waiting, so a slow machine sheds load."""
        try:
            self._jobs.put_nowait((fn, callback))
            return True
        except queue.Full:
            return False

    def _work(self) -> None:
        while True:
            fn, callback = self._jobs.get()
            try:
                item = (callback, fn(), None)
            except BaseException as err:  # reported through the callback, never lost or fatal
                item = (callback, None, err)
            self._done.put(item)
            # Forget the job: this thread's variables would otherwise keep the last job's callback
            # (and so the widget it belongs to) alive until the next job arrives.
            del fn, callback, item

    @property
    def waiting(self) -> int:
        return self._jobs.qsize() + self._done.qsize()

    def drain(self) -> int:
        """Run the callbacks of finished jobs. Call this on the window's thread."""
        count = 0
        while True:
            try:
                callback, result, error = self._done.get_nowait()
            except queue.Empty:
                return count
            count += 1
            try:
                callback(result, error)
            except Exception:  # a bad callback must not stop the others
                log.get("workers").exception("A background job's callback failed")


class Pump:
    """Delivers finished jobs on the window's thread: a timer that runs only while jobs are pending."""

    def __init__(self, pool: BackgroundPool, every_ms: int = 20):
        self.pool, self.every_ms = pool, every_ms
        self._root: Any = None
        self._job: Optional[str] = None

    def kick(self, widget: Any) -> None:
        """Make sure finished jobs will be delivered. Call from the window's thread after submitting."""
        root = widget._root()                     # the Tk root (not the dialog the widget sits in)
        if self._job is not None and root is self._root:
            return
        self._root = root                         # first use, or a new window after the old root was destroyed
        self._job = root.after(self.every_ms, self._tick)

    def _tick(self) -> None:
        self._job = "running"
        try:
            self.pool.drain()
        finally:
            if self.pool.waiting and self._root is not None:
                try:
                    self._job = self._root.after(self.every_ms, self._tick)
                except Exception:
                    self._job = None
            else:
                self._job = None


# One pool for drawing work (two threads are plenty: Pillow does most of its work outside the GIL).
render_pool = BackgroundPool(workers=2, name="render")
render_pump = Pump(render_pool)
