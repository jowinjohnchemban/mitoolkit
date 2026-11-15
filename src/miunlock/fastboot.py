import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from miunlock.system import SYSTEM, IS_TERMUX, console, make_executable, WHITE, ORANGE, RED
from miunlock.termux import setup_fastboot as setup_termux_fastboot

PLATFORM_TOOLS_OS = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}


def download_platform_tools():
    os_name = PLATFORM_TOOLS_OS.get(SYSTEM)
    if not os_name:
        console.print(f"[{RED}]✗ platform-tools do not support {SYSTEM}. Install fastboot manually and rerun.[/]")
        raise SystemExit(1)

    tools_dir = Path.home() / "platform-tools"
    zip_path = tools_dir.parent / "platform-tools.zip"
    url = f"https://dl.google.com/android/repository/platform-tools-latest-{os_name}.zip"

    with console.status(f"[{WHITE}]Installing platform-tools for {os_name} (first time only) ...[/]"):
        tools_dir.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, str(zip_path))
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(str(tools_dir.parent))
        zip_path.unlink()

    fastboot_path = tools_dir / ("fastboot.exe" if SYSTEM == "Windows" else "fastboot")
    make_executable(str(fastboot_path))
    return str(fastboot_path)


def update_platform_tools():
    """Download the latest adb and fastboot from Google again (platform-tools), replacing the
    copy in ~/platform-tools. Returns the folder. A system-wide install is left alone."""
    tools_dir = Path.home() / "platform-tools"
    adb = tools_dir / ("adb.exe" if SYSTEM == "Windows" else "adb")
    if adb.exists():  # a running adb server would keep its file locked on Windows
        try:
            subprocess.run([str(adb), "kill-server"], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (subprocess.SubprocessError, OSError):
            pass
    download_platform_tools()
    return str(tools_dir)


def get_fastboot():
    if IS_TERMUX:
        return setup_termux_fastboot()

    cmd = shutil.which("fastboot")
    if cmd is not None:
        make_executable(cmd)
        return str(cmd)

    tools_dir = Path.home() / "platform-tools"
    fastboot_path = tools_dir / ("fastboot.exe" if SYSTEM == "Windows" else "fastboot")
    if fastboot_path.exists():
        make_executable(str(fastboot_path))
        return str(fastboot_path)

    console.print(f"\n[{ORANGE}]fastboot is not installed, downloading...\n[/]")
    return download_platform_tools()