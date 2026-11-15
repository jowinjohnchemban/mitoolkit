# Installation

`miunlock` needs Python 3.9 or newer. It is not published on PyPI; install it
from this repository.

> [!NOTE]
> The package named `miunlock` on PyPI is the original upstream project, not this
> fork. Use the commands below so you get this version.

## 1. Install Python

**Windows**

Download the installer from [python.org](https://www.python.org/downloads/) and
tick *Add Python to PATH*, or use WinGet:

```sh
winget install python
```

**macOS**

```sh
brew install --cask python
```

**Debian / Ubuntu**

```sh
sudo apt install python3 python3-venv python3-pip
```

**Fedora**

```sh
sudo dnf install python3
```

**Arch Linux**

```sh
sudo pacman -S python
```

## 2. Create a virtual environment (recommended)

A virtual environment keeps the install separate from your system Python and avoids
`externally-managed-environment` errors.

```sh
python3 -m venv miunlock-env
```

Activate it:

| Shell | Command |
|---|---|
| bash / zsh (macOS, Linux) | `source miunlock-env/bin/activate` |
| fish | `source miunlock-env/bin/activate.fish` |
| Windows PowerShell | `miunlock-env\Scripts\Activate.ps1` |
| Windows cmd | `miunlock-env\Scripts\activate.bat` |

On Windows, use `python` instead of `python3` if `python3` is not found. You must
activate the environment again in every new terminal.

## 3. Install miunlock

```sh
pip install git+https://github.com/jowinjohnchemban/miunlock.git
```

Check it works:

```sh
miunlock --help
```

Run `miunlock` for the GUI or `miunlock --cli` for the command line. To update later, run the same
command with `--upgrade`. To remove it, run `pip uninstall miunlock`.

## adb, fastboot and USB drivers

adb and fastboot are built into `miunlock`; Google's platform-tools are not needed. The
program talks to the phone over USB with [libusb](https://libusb.info), which `pip`
installs with it (the `libusb-package` wheel) on Windows, macOS and 64-bit Linux. Elsewhere,
install libusb from your system's packages.

- **Windows** needs a USB driver for the phone. Run *File > Install Google USB driver* in
  the GUI, or `miunlock install-driver`, which installs Google's official driver after an
  administrator prompt. If the phone still has a yellow mark in Device Manager, right-click
  it > *Update driver > Browse my computer > Let me pick > Android Device > Android
  Bootloader Interface* (or *Android ADB Interface* while Android is running).
- **Linux** needs permission for the phone: add a udev rule for Android devices, for
  example by installing `android-sdk-platform-tools-common` (Debian/Ubuntu), then reconnect.
- **macOS** needs nothing extra.

Only one program can use the phone at a time. Close Google's adb (`adb kill-server`),
Android Studio, Mi Unlock or Mi Flash before using `miunlock`.

The first time adb connects, the phone asks *Allow USB debugging?*. `miunlock` uses the same
key file as Google's adb (`~/.android/adbkey`), creating it if needed, so a computer you
already allowed is recognised.

## Android (Termux)

Install both apps from the same source, for example from GitHub:

- [Termux](https://github.com/termux/termux-app/releases/latest)
- [Termux:API](https://github.com/termux/termux-api/releases/latest)

Then either run the helper script:

```sh
curl -sS https://raw.githubusercontent.com/jowinjohnchemban/miunlock/main/.install | bash
```

or install by hand:

```sh
pkg install python-pip
pip install git+https://github.com/jowinjohnchemban/miunlock.git
```

The first time you run `miunlock` it installs
[termux-fastboot](https://github.com/nohajc/termux-adb) from the third-party
`nohajc/termux-adb` project, which downloads and runs its install script. You can do
that yourself first:

```sh
curl -s https://raw.githubusercontent.com/nohajc/termux-adb/master/install.sh | bash
```

Read scripts before piping them to a shell, including `.install` here.

## Prebuilt executables

If you would rather not install Python, download a ready-made program from the
[Releases page](https://github.com/jowinjohnchemban/miunlock/releases/latest):

| File | What it is |
|---|---|
| `miunlock-windows-x64.exe`, `miunlock-linux-x64`, `miunlock-macos-arm64` | The program: opens the GUI, or runs on the command line with `--cli` |
| `miunlock-<version>-py3-none-any.whl`, `miunlock-<version>.tar.gz` | Python packages |
| `SHA256SUMS.txt` | Checksums |

They are built by GitHub Actions from the tagged source. Check your download
against `SHA256SUMS.txt` before running it:

```sh
# Linux
sha256sum -c SHA256SUMS.txt --ignore-missing
# macOS
shasum -a 256 -c SHA256SUMS.txt --ignore-missing
```

```powershell
# Windows PowerShell: compare the printed hash with the line in SHA256SUMS.txt
Get-FileHash .\miunlock-windows-x64.exe -Algorithm SHA256
```

The programs are **not code-signed**, so Windows SmartScreen or macOS Gatekeeper may
warn, and some antivirus tools flag programs made with PyInstaller. If that worries
you, install from source instead. On Linux the GUI also needs Tk on the system
(for example `sudo apt install python3-tk`). The macOS build is for Apple silicon.

## Install from a local clone

```sh
git clone https://github.com/jowinjohnchemban/miunlock.git
cd miunlock
pip install .
```

For development, see [CONTRIBUTING.md](../CONTRIBUTING.md).
