# Changelog

Highlights of the project's changes. Every merge to `main` is released automatically with a
[Semantic Versioning](https://semver.org) number worked out from [Conventional Commits](https://www.conventionalcommits.org)
pull request titles (see CONTRIBUTING.md); the full, generated notes of each release are on the
[Releases page](https://github.com/jowinjohnchemban/mitoolkit/releases).

## Since 1.0.0

### Fixed
- The list of programs that can hold a phone (and make MiToolkit say "another program is using it") named
  `mitoolkit`, which is this program, instead of Xiaomi's `miunlock` tool, since the rename.
- The Wireless adb window fits its content (Close was cut off), keeps one size while you change pairing method, and
  hides actions that do not apply.
- After pairing, MiToolkit waits for the phone to start listening a few seconds later and connects by itself,
  instead of asking to pair again. Phones that Google's adb lists by their network name now count as wireless.
- A phone on Wi-Fi is found even when the network never delivers the announcements adb listens for (a PC on a cable
  and a phone on Wi-Fi often cannot hear each other): its address is remembered and its Wireless debugging port is
  looked for directly on that one address. Connect by address works with the address alone.
- The Connections window's Network test pinged the mobile carrier's gateway and reported the router as failed; it now
  pings the Wi-Fi router.
- The Serial row showed the Wi-Fi address for a phone on Wi-Fi; it shows the phone's own serial, with the address on
  its own row.
- Refreshing the phone's details no longer rebuilds the Phone section (it flickered): values change in place.
- The log file and crash.log are written in a `logs` folder next to the program instead of beside it, and that folder
  is ignored by git (a rotated `mitoolkit.log.1` was once committed by accident).

- Live status listed things that are not temperatures as sensors: the battery's charge as a "54 °C, warm" hottest
  sensor, battery voltage and current limits as a few degrees, and the thermal governor's derived `-step` and `lowf`
  zones. They are left out. The SoC page's note about temperatures now says what it means.
- The Processor gauge waited for a second reading before it showed anything (about 15 s over USB); the first
  reading now already has a load.
- With the selector on Wi-Fi, a phone plugged in with a cable showed "The phone isn't answering"; the app now
  switches to USB. A phone on Wi-Fi says up front that fastboot needs a cable. The footer shows the USB port
  (`USB port 2-8`) even when adb's device list does not say where the phone is plugged in.

- Text is written one way everywhere: Title Case for labels (buttons, menus, window titles), sentence case for
  sentences and messages with a capital after "Step 2:", no "..." and no decorative symbols (middle dots, bullets, arrows).
  A test keeps it so.

- The window follows what an AI agent does: the status bar says what it is doing and when it is done, a device or
  reboot call makes the window look at the phone again, and an agent's security check colours the Security Check
  button. Device details given to agents leave out addresses and IDs in every section (a "Wi-Fi IP address" row got
  through). The line announcing the agent connection is no longer shown in red.

### Added
- MCP in the app: Help > AI Agent Connection lets an AI agent use the running MiToolkit (local address and secret token,
  off until turned on). Changing things asks the person first, unlocking is never offered, and the status bar shows the
  agent's name in green while it is connected.
- AGENTS.md (how to work on the project, the text standard, and to listen to the two upstream repositories for
  patches, updates and ideas) and docs/upstream.md (what was last reviewed).
- Check for updates can download the latest release file (checked against its SHA-256, saved in Downloads with the
  version in its name, nothing installed) as well as install it, for every kind of install, and opens the release
  page. The window grows to fit its buttons.
- A USB | Wi-Fi selector in the Phone section (USB by default; both choices always visible, the labels fade as the
  thumb slides). Wi-Fi mode finds phones with Wireless debugging on the network, connects the ones that already
  trust this computer, and guides pairing for a new one: with a QR code that the phone scans, or with the pairing
  code. Friendlier messages when a connection fails; example addresses in the address boxes.
- The footer says how the phone is connected: its USB port (`USB port 1-3`) or its Wi-Fi address and port.
- Malware scan, as part of Security check: risky access in apps that did not come from a store, hidden or fake
  system apps, leftover programs in `/data/local/tmp`, root, and debug builds. Read through adb; nothing is uploaded.
- Live status: the Processor tab is now SoC, with the processor, GPU and memory each showing load, speed and
  temperature.
- The Phone section's Copy details, Export and Rescan are quiet icon buttons with tooltips, on one line with the
  selector. The Wireless adb menu item and window are now called Wi-Fi connection, to match the selector.
- Closing MiToolkit lets go of the phone: its USB connections are closed, a Google fastboot it started is stopped,
  and so is the Google adb server it started (one already running is left alone). The log file and crash.log are
  closed too.
- Automatic releases: every merge to `main` is released with a Semantic Versioning number worked out from the
  Conventional Commits pull request titles; the doctor can ask for administrator rights (UAC, polkit, the macOS
  prompt) for the few fixes that need them, and only after a person chooses.
- The doctor: Help > Check and fix problems, and `mitoolkit doctor [--fix] [--all]`. It looks for what stops
  MiToolkit working (USB access, the adb key, the saved session's permissions, settings, update leftovers, a phone
  waiting to be allowed or held by another program) and says what is wrong in plain words. Safe fixes run by
  themselves at start-up; fixes that need a decision run only when chosen. Agents get the diagnosis, not fixes.
- Wireless adb pairing (Android 11 and newer, no cable): Phone > Wireless adb > Pair a new phone. Find phones on
  the Wi-Fi network, enter the pairing code, and the phone trusts this computer from then on. The window says
  plainly when a phone is waiting for you to allow it, and what to tick.

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
  (`--debug`, `MITOOLKIT_DEBUG=1`, or Help > Debug logging).

### Security
- The saved session is stored in the OS credential store (with `mitoolkit[secure]`) or encrypted with Windows DPAPI,
  and expires after 24 hours. A scrubbed `mitoolkit.log` is written next to the program.
- Error messages and logs never contain tokens or one-time login URLs; URLs from Xiaomi are opened without a shell
  and only if they are https; the signed unlock token goes to a private temporary file.
- No password login. CI pins its actions to commits and uses read-only token permissions.
- See [docs/safety.md](docs/safety.md) for the full model and its limits.
