<p align="center"><img src="assets/logo.png" alt="miunlock logo" width="120"></p>

<h1 align="center">miunlock</h1>

Unlock the bootloader of Xiaomi, Redmi and POCO devices from any operating
system, using Xiaomi's own unlock service.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

`miunlock` logs in to your Mi Account, asks Xiaomi's server for a signed unlock
token for your device (the `encryptData` value, see
[How it works](docs/how-it-works.md)), and hands that token to `fastboot`. It
follows the same official process as Xiaomi's Windows-only Mi Unlock tool, so it
does **not** bypass the waiting period or any account requirement.

> [!WARNING]
> Unlocking a bootloader erases all user data on most devices, voids the
> warranty and lowers the device's security. It cannot be undone once started.
> Back up first. Read the [safety model](docs/safety.md).

## Features

- Works on Windows, macOS, Linux and Android (Termux)
- One program, three ways to drive it: a GUI (default), a command line (`--cli`, JSON output)
  and an AI-agent interface (`--mcp`)
- Uses adb to see your phone, show its details and reboot it into fastboot for you
- Python API for your own scripts and automation
- Login happens on Xiaomi's own page (browser or QR code); your password never
  passes through this program
- The one destructive step is gated behind an explicit `--confirm-wipe`

## Requirements

- Python 3.9 or newer
- A USB data cable and a device that can enter fastboot mode
- A Mi Account that has been added to the device under
  *Developer options → Mi Unlock status* (see the [unlock guide](docs/unlock-guide.md))

`fastboot` is downloaded automatically from Google if it is not already installed.

## Installation

```sh
pip install git+https://github.com/jowinjohnchemban/miunlock.git
```

This project is not published on PyPI; install from source as shown. Prebuilt
Windows, Linux and macOS programs are on the
[Releases page](https://github.com/jowinjohnchemban/miunlock/releases/latest).
Full instructions, including virtual environments and Termux, are in the
[installation guide](docs/installation.md).

## Quick start

1. Add your account and device in *Developer options → Mi Unlock status* and wait
   out Xiaomi's waiting period. See the [unlock guide](docs/unlock-guide.md).
2. Put the device in fastboot mode and connect it.
3. Run `miunlock`: it opens the GUI. The same program is the command line when you
add `--cli`, or give it a command:

```sh
miunlock --cli                    # interactive prompt
miunlock devices                  # phones seen by adb and fastboot
miunlock reboot-fastboot          # adb: reboot a running phone into fastboot
miunlock login                    # log in or reuse a saved session
miunlock status                   # account and device info
miunlock check                    # is this device eligible right now? (read-only)
miunlock unlock --confirm-wipe    # unlock; ERASES THE DEVICE
miunlock --mcp                    # let an AI agent control it (cannot unlock)
```

See the [usage guide](docs/usage.md), the [AI agent guide](docs/agents.md) and the
[Python API](docs/api.md).

## Documentation

| Page | Contents |
|---|---|
| [Installation](docs/installation.md) | Python, virtual environments, Termux |
| [Unlock guide](docs/unlock-guide.md) | Step-by-step process on the device |
| [Usage](docs/usage.md) | Interactive mode, CLI, GUI, session handling |
| [AI agents](docs/agents.md) | Control and read miunlock from an agent over MCP |
| [Python API](docs/api.md) | `miunlock.api` reference |
| [Safety model](docs/safety.md) | What is hardened, what is gated, what to watch for |
| [FAQ](docs/faq.md) | Common questions and device troubleshooting |
| [Error codes](docs/error-codes.md) | Messages returned by Xiaomi's servers |
| [How it works](docs/how-it-works.md) | `deviceToken`, `encryptData`, the unlock sequence |
| [Architecture](docs/architecture.md) | Package layout and request flow |
| [Upstream changelog](docs/upstream-changelog.md) | History of the original MiUnlockTool |

Project files: [CHANGELOG](CHANGELOG.md) · [CONTRIBUTING](CONTRIBUTING.md) ·
[SECURITY](SECURITY.md) · [LICENSE](LICENSE) · [NOTICE](NOTICE)

## Project status

This is an independent, standalone fork. It is **derived from** two projects by
[offici5l](https://github.com/offici5l), and most of the code is theirs:

- [MiForge/MiUnlockTool](https://github.com/MiForge/MiUnlockTool) (Apache-2.0)
- [MiForge/migate](https://github.com/MiForge/migate) (MIT), now merged in as
  `miunlock.auth`

This fork adds the changes listed in the [CHANGELOG](CHANGELOG.md): the password
login path was removed, the saved session file is locked down, and a Python API,
JSON CLI and GUI were added. If you do not need those, use the original projects.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0, see [LICENSE](LICENSE). Code that originated in `migate` is
MIT-licensed by its author; its notice is kept in [NOTICE](NOTICE).

This project is not affiliated with or endorsed by Xiaomi.
