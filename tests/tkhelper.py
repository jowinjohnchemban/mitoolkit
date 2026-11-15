"""Tk roots for tests. On Windows, creating Tk interpreters in quick succession occasionally fails
with "couldn't read init.tcl" (a file-access race outside our code), so retry a few times."""
import time
import tkinter as tk


def make_root(tries: int = 5) -> tk.Tk:
    for attempt in range(tries):
        try:
            return tk.Tk()
        except tk.TclError as err:
            if "init.tcl" not in str(err) or attempt == tries - 1:
                raise
            time.sleep(0.2)
