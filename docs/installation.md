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

This also installs the `miunlock-gui` command. To update later, run the same
command with `--upgrade`. To remove it, run `pip uninstall miunlock`.

## fastboot

`miunlock` uses `fastboot`. If it is not on your `PATH`, it downloads Google's
platform-tools into `~/platform-tools` the first time it is needed.

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

## Install from a local clone

```sh
git clone https://github.com/jowinjohnchemban/miunlock.git
cd miunlock
pip install .
```

For development, see [CONTRIBUTING.md](../CONTRIBUTING.md).
