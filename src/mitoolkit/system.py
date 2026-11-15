import os
import platform
import stat
import subprocess

from mitoolkit.auth.config import console, ORANGE, WHITE, DIM, RED, GREEN

SYSTEM = platform.system()
# Stops a console window flashing up for every fastboot call when running the
# windowed GUI on Windows. It is 0 (a no-op) everywhere else.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# mitoolkit runs on computers. On Android (for example in Termux) apps cannot open USB
# devices directly, so it is not supported there.
IS_ANDROID = ("ANDROID_ROOT" in os.environ and "ANDROID_DATA" in os.environ) or "com.termux" in os.environ.get("PREFIX", "")


def make_executable(path):
    if SYSTEM not in ("Linux", "Darwin"):
        return
    st = os.stat(path)
    if os.getuid() == st.st_uid:
        x_bit = stat.S_IXUSR
    elif os.getgid() == st.st_gid:
        x_bit = stat.S_IXGRP
    else:
        x_bit = stat.S_IXOTH
    if not (st.st_mode & x_bit):
        os.chmod(path, st.st_mode | x_bit)
