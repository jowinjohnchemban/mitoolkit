<p align="center"><img src="assets/logo.png" alt="mitoolkit logo" width="120"></p>

<h1 align="center">MiToolkit</h1>

<p align="center">A toolkit for Xiaomi, Redmi and POCO phones: unlock the bootloader with Xiaomi's own service,
and see, test and look after the phone before and after.</p>

<p align="center">
  <a href="https://github.com/jowinjohnchemban/mitoolkit/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/jowinjohnchemban/mitoolkit?display_name=tag&sort=semver"></a>
  <a href="https://github.com/jowinjohnchemban/mitoolkit/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/jowinjohnchemban/mitoolkit/ci.yml?branch=main&label=CI"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <a href="pyproject.toml"><img alt="Python" src="https://img.shields.io/badge/python-3.9%2B-blue.svg"></a>
  <img alt="Platforms" src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg">
  <a href="https://github.com/jowinjohnchemban/mitoolkit/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/jowinjohnchemban/mitoolkit/total"></a>
  <a href="https://github.com/jowinjohnchemban/mitoolkit/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/jowinjohnchemban/mitoolkit"></a>
  <a href="https://github.com/jowinjohnchemban/mitoolkit/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/jowinjohnchemban/mitoolkit?style=flat"></a>
</p>

`mitoolkit` logs in to your Mi Account, asks Xiaomi's server for a signed unlock
token for your device (the `encryptData` value, see
[How it works](docs/how-it-works.md)), and hands that token to `fastboot`. It
follows the same official process as Xiaomi's Windows-only Mi Unlock tool, so it
does **not** bypass the waiting period or any account requirement.

> [!WARNING]
> Unlocking a bootloader erases all user data on most devices, voids the
> warranty and lowers the device's security. It cannot be undone once started.
> Back up first. Read the [safety model](docs/safety.md).

## Features

- Works on Windows, macOS and Linux
- One program, three ways to drive it: a GUI (default), a command line (`--cli`, JSON output)
  and an AI-agent interface (`--mcp`)
- Built-in adb and fastboot (no platform-tools needed; uses Google's adb server when it is
  running): see your phone, show its details, reboot it into fastboot, back up its files
- Device details, and a **Show more** view of everything the phone gives over USB (identity,
  hardware, modem and SIM, boot, servicing and debugging, partitions, sensors)
- **Live status**: a dashboard with gauges and smooth graphs (processor and every core, GPU, memory,
  battery, temperature, network), every thermal sensor, and a task-manager style process list
- **Connections and signal**: Wi-Fi, mobile network (modem), SIM, Bluetooth and USB, with plain-language
  findings and an optional network test, for debugging Wi-Fi and telecom problems
- Log viewer (logcat); one dialog to restart into Android, recovery or fastboot, or power off (and to leave
  fastboot without unlocking); export device details as text, CSV or Markdown
- Updates over the air for the single-file program (checked against the release's SHA-256 list), and
  automatic releases from GitHub
- A doctor (`mitoolkit doctor`, or Help > Check and fix problems) that finds what is wrong with the setup, and fixes
  what is safe to fix by itself
- Wireless adb: use the phone over Wi-Fi for everything except fastboot and unlocking (those need a cable)
- App manager: remove preinstalled bloat for your user, with plain ratings, and restore it
- Security check: missing Android security fixes (from OSV / Android Security Bulletins),
  Google Play Protect, where apps came from, apps with powerful access, known stalkerware
- Python API for your own scripts and automation
- Login happens on Xiaomi's own page (browser or QR code); your password never
  passes through this program
- The one destructive step is gated behind an explicit `--confirm-wipe`

## Requirements

- Python 3.9 or newer
- A USB data cable and a device that can enter fastboot mode
- A Mi Account that has been added to the device under
  *Developer options → Mi Unlock status* (see the [unlock guide](docs/unlock-guide.md))

adb and fastboot are built in: no Android platform-tools are needed. On Windows the phone
needs a USB driver; the program shows the steps and opens Google's download page (Help >
USB driver help), but it never downloads or installs a driver itself.

## Installation

```sh
pip install git+https://github.com/jowinjohnchemban/mitoolkit.git
```

This project is not published on PyPI; install from source as shown. Prebuilt
Windows, Linux and macOS programs are on the
[Releases page](https://github.com/jowinjohnchemban/mitoolkit/releases/latest).
Full instructions, including virtual environments and USB drivers, are in the
[installation guide](docs/installation.md).

## Quick start

1. Add your account and device in *Developer options → Mi Unlock status* and wait
   out Xiaomi's waiting period. See the [unlock guide](docs/unlock-guide.md).
2. Put the device in fastboot mode and connect it.
3. Run `mitoolkit`: it opens the GUI. The same program is the command line when you
add `--cli`, or give it a command:

```sh
mitoolkit --cli                    # interactive prompt
mitoolkit devices                  # phones seen by adb and fastboot
mitoolkit reboot-fastboot          # adb: reboot a running phone into fastboot
mitoolkit login                    # log in or reuse a saved session
mitoolkit status                   # account and device info
mitoolkit check                    # is this device eligible right now? (read-only)
mitoolkit unlock --confirm-wipe    # unlock; ERASES THE DEVICE
mitoolkit --mcp                    # let an AI agent control it (cannot unlock)
```

See the [usage guide](docs/usage.md), the [AI agent guide](docs/agents.md) and the
[Python API](docs/api.md).

## Documentation

| Page | Contents |
|---|---|
| [Installation](docs/installation.md) | Python, virtual environments, USB drivers |
| [Unlock guide](docs/unlock-guide.md) | Step-by-step process on the device |
| [Usage](docs/usage.md) | Interactive mode, CLI, GUI, session handling |
| [AI agents](docs/agents.md) | Control and read mitoolkit from an agent over MCP |
| [Python API](docs/api.md) | `mitoolkit.api` reference |
| [Safety model](docs/safety.md) | What is hardened, what is gated, what to watch for |
| [FAQ](docs/faq.md) | Common questions and device troubleshooting |
| [Error codes](docs/error-codes.md) | Messages returned by Xiaomi's servers |
| [How it works](docs/how-it-works.md) | `deviceToken`, `encryptData`, the unlock sequence |
| [Architecture](docs/architecture.md) | Package layout and request flow |

Project files: [CHANGELOG](CHANGELOG.md) · [CONTRIBUTING](CONTRIBUTING.md) ·
[SECURITY](SECURITY.md) · [CREDITS](CREDITS.md) · [LICENSE](LICENSE) · [NOTICE](NOTICE)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0, see [LICENSE](LICENSE); third-party notices are in [NOTICE](NOTICE).
This project is not affiliated with or endorsed by Xiaomi.
