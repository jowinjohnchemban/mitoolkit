"""Tk roots for tests. On Windows, creating Tk interpreters in quick succession occasionally fails
with "couldn't read init.tcl" (a file-access race outside our code), so retry a few times."""
import time
import tkinter as tk

# Every root made here stays referenced for the whole run. A destroyed root that the garbage collector frees later
# deletes its Tcl interpreter on whichever thread happens to be collecting; Tcl then aborts the whole process with
# "Tcl_AsyncDelete: async handler deleted by the wrong thread" (seen on Windows with Python 3.9).
_KEPT: list = []


def make_root(tries: int = 5) -> tk.Tk:
    for attempt in range(tries):
        try:
            root = tk.Tk()
            _KEPT.append(root)
            return root
        except tk.TclError as err:
            if "init.tcl" not in str(err) or attempt == tries - 1:
                raise
            time.sleep(0.2)
    raise tk.TclError("could not create a Tk root")        # (only reached with tries <= 0)
