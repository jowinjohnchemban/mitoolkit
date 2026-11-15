# Installation

`mitoolkit` needs Python 3.9 or newer. It is not published on PyPI; install it
from this repository.

> [!NOTE]
> Install from this repository, as shown below, so the code you run is the code you can read.

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
python3 -m venv mitoolkit-env
```

Activate it:

| Shell | Command |
|---|---|
| bash / zsh (macOS, Linux) | `source mitoolkit-env/bin/activate` |
| fish | `source mitoolkit-env/bin/activate.fish` |
| Windows PowerShell | `mitoolkit-env\Scripts\Activate.ps1` |
| Windows cmd | `mitoolkit-env\Scripts\activate.bat` |

On Windows, use `python` instead of `python3` if `python3` is not found. You must
activate the environment again in every new terminal.

## 3. Install mitoolkit

```sh
pip install git+https://github.com/jowinjohnchemban/mitoolkit.git
```

Check it works:

```sh
mitoolkit --help
```

Run `mitoolkit` for the GUI or `mitoolkit --cli` for the command line. To update later, run the same
command with `--upgrade`. To remove it, run `pip uninstall mitoolkit`.

## adb, fastboot and USB drivers

adb and fastboot are built into `mitoolkit`; Google's platform-tools are not needed. The
program talks to the phone over USB with [libusb](https://libusb.info), which `pip`
installs with it (the `libusb-package` wheel) on Windows, macOS and 64-bit Linux. Elsewhere,
install libusb from your system's packages.

- **Windows** needs a USB driver for the phone. *Help > USB driver help* in the GUI (or
  `mitoolkit driver-help --open`) lists the steps and opens Google's download page; you install
  the driver yourself with Device Manager: right-click the phone > *Update driver > Browse my
  computer > Let me pick > Have Disk*, choose `android_winusb.inf`, then *Android Bootloader
  Interface* (fastboot mode) or *Android ADB Interface* (Android running). mitoolkit does not
  download or install drivers.
- **Linux** needs permission for the phone: add a udev rule for Android devices, for
  example by installing `android-sdk-platform-tools-common` (Debian/Ubuntu), then reconnect.
- **macOS** needs nothing extra.

Only one program can open the phone at a time. If Google's adb server is running,
mitoolkit works through it, so you do not need to stop it. If Google's `fastboot` is
already installed, mitoolkit uses it for a phone its own fastboot cannot open. Close Mi
Unlock, Mi Flash or other phone tools while using mitoolkit.

The first time adb connects, the phone asks *Allow USB debugging?*. `mitoolkit` uses the same
key file as Google's adb (`~/.android/adbkey`), creating it if needed, so a computer you
already allowed is recognised.

## Android

Running `mitoolkit` on an Android phone (for example in Termux, to unlock another phone over
OTG) is not supported: Android apps cannot open USB devices directly. Connect the phone to
a computer instead.

## Prebuilt executables

If you would rather not install Python, download a ready-made program from the
[Releases page](https://github.com/jowinjohnchemban/mitoolkit/releases/latest):

| File | What it is |
|---|---|
| `mitoolkit-windows-x64.exe`, `mitoolkit-linux-x64`, `mitoolkit-macos-arm64` | The program: opens the GUI, or runs on the command line with `--cli` |
| `mitoolkit-<version>-py3-none-any.whl`, `mitoolkit-<version>.tar.gz` | Python packages |
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
Get-FileHash .\mitoolkit-windows-x64.exe -Algorithm SHA256
```

**Windows SmartScreen.** SmartScreen warns about any program it has not seen many times, and trusts one
only when it is code-signed with a certificate it knows or has built up a reputation. The Windows program
has proper file properties (product, version, publisher name) but is **not code-signed until a signing
certificate is added to the repository** (see CONTRIBUTING.md > Signing), so you may see "Windows protected
your PC". Check the download against `SHA256SUMS.txt` as above, then choose **More info > Run anyway**.
Updating from inside mitoolkit (Help > Check for updates) downloads the new program without the web-download
mark, so it does not trigger the warning again. macOS Gatekeeper may warn in the same way, and some antivirus
tools flag programs made with PyInstaller. If that worries you, install from source instead. On Linux the GUI also needs Tk on the system
(for example `sudo apt install python3-tk`). The macOS build is for Apple silicon.

## Install from a local clone

```sh
git clone https://github.com/jowinjohnchemban/mitoolkit.git
cd mitoolkit
pip install .
```

For development, see [CONTRIBUTING.md](../CONTRIBUTING.md).
