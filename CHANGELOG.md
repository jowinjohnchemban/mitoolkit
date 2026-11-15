# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2026-11-15

The first release.

### Unlock
- Unlock the bootloader of Xiaomi, Redmi and POCO phones with Xiaomi's own service, from Windows, macOS or Linux.
  You sign in on Xiaomi's page (browser or QR code); your password never passes through the program.
- The one destructive step is gated: a ticked box and the phone's name in the GUI, `--confirm-wipe` on the
  command line and in the API. AI agents (`--mcp`) can read and check but cannot unlock.
- Built-in adb and fastboot over USB (no platform-tools needed), through Google's adb server when it is running.
  Wireless adb for everything except fastboot and unlocking, which need a cable.
- In fastboot mode: restart into Android, or recovery, to leave without unlocking.

### The phone
- Device details and **Show more**: everything the phone reports over USB (identity, hardware, modem and SIM,
  boot, servicing and debugging, partitions, sensors), or every bootloader variable in fastboot mode.
  Copy, or export as text, CSV or Markdown.
- **Live status**: a dashboard with gauges and smooth, high-resolution graphs (processor and every core, GPU,
  memory, battery, temperature, network), every thermal sensor, and a task-manager style process list.
- **Connections and signal**: Wi-Fi, mobile network (modem), SIM, Bluetooth, USB and power, with plain-language
  findings, signal graphs and an optional network test.
- **Security check**: missing Android security fixes (OSV), Play Protect, app sources and access, known
  stalkerware. A quick local check colours the button as soon as a phone connects.
- **Back up files**: resumable, size-checked, retried, with failures listed in `backup-problems.txt`.
- **App manager**: remove preinstalled apps for your user, with plain ratings, and restore them.
- Log viewer (logcat), restart / recovery / fastboot / power off in one dialog, unplugging noticed within a second.

### The program
- One program: a GUI (default), a JSON command line (`--cli`) and an AI-agent interface (`--mcp`), plus a Python API.
- Updates over the air: Help > Check for updates downloads the latest release of the single-file program, checks it
  against `SHA256SUMS.txt` and restarts; a quiet daily check can be turned off. Releases are automatic.
- Versions read `v1.0.0 (build: DDMMYYYY-commit)`.
- Accessible (WCAG 2.2 AA contrast checked by tests, keyboard access, text up to 200%), native-feeling on each
  system, windows that stay inside the free part of the screen.
- Built to stay up: a watchdog, timeouts on phone calls, crash logging, memory hygiene, debug logging
  (`--debug`, `MIUNLOCK_DEBUG=1`, or Help > Debug logging).

### Security
- The saved session is stored in the OS credential store (with `miunlock[secure]`) or encrypted with Windows DPAPI,
  and expires after 24 hours. A scrubbed `miunlock.log` is written next to the program.
- Error messages and logs never contain tokens or one-time login URLs; URLs from Xiaomi are opened without a shell
  and only if they are https; the signed unlock token goes to a private temporary file.
- No password login. CI pins its actions to commits and uses read-only token permissions.
- See [docs/safety.md](docs/safety.md) for the full model and its limits.
