# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The history of the original MiUnlockTool (versions 1.4.8 through 1.7.5)
is kept in [docs/upstream-changelog.md](docs/upstream-changelog.md).

## [Unreleased]

### Added

- GUI shows device details when a phone is connected: model, codename, Android and HyperOS/MIUI
  version, security patch, bootloader state, battery and a masked serial (fastboot mode shows
  codename, bootloader state and version, and active slot).
- Built-in adb and fastboot: miunlock speaks both USB protocols itself (pyusb + libusb),
  checked against AOSP's sources. Google's platform-tools are no longer downloaded. adb uses
  the same `~/.android/adbkey` as Google's adb.
- App manager (debloat): **Manage apps...** in the GUI and `miunlock apps list|remove|restore`
  list every app with a rating from a curated Xiaomi bloat list, remove ticked apps for your
  user (`pm uninstall --user 0`) and restore them.
- Windows: `miunlock install-driver` / *File > Install Google USB driver* installs Google's
  USB driver with pnputil after a UAC prompt.
- Back up files before unlocking: a **Back up files...** dialog in the GUI and
  `miunlock backup --dest <folder> --only photos,documents` copy photos, documents, chat media,
  audio or all shared storage from a running phone over adb, plus a list of installed
  apps. Read-only for the phone. The guide has a new "Back up your data" section.
- Waiting-period message now says when to try again; GUI shows a tip when no phone is found
  after 20 s, and has Rescan and Copy info buttons.
- Step-by-step guide inside the GUI (Help menu or F1), available offline.
- GUI: scrollable page with a scrollbar and mouse wheel, Copy and Clear for the details
  panel, step badges that show what to do next, Ctrl+Q to quit.

### Removed

- Android (Termux) support, including `.install` and the code that downloaded and ran the
  third-party `nohajc/termux-adb` install script. Run miunlock on a computer; on Android it
  now says so instead of failing.

### Changed

- Code structure: the Xiaomi request sequence lives once in `xiaomi.UnlockServer` (used by
  both the API and the interactive flow); fastboot has a `Backend` interface (implemented
  over USB); `adb.Phone` wraps a connected phone; GUI windows are classes in
  `miunlock.ui`; every expected error derives from `MiunlockError`; CLI commands share one
  JSON wrapper. Behaviour is unchanged.

- The Windows program is built without a console, so opening the GUI no longer flashes a
  command window. Command-line use still prints to the terminal that started it.
- Updated the unlock guide and usage docs for the GUI.

## [1.8.0] - 2026-11-15

First release of this fork. It starts from MiUnlockTool 1.7.5 and migate 1.1.11,
both by offici5l.

### Added

- One program: `miunlock` opens the GUI; `--cli` or any command runs the command line.
  `miunlock-gui` remains as an alias. Release builds are a single executable per system.
- adb support (`miunlock.adb`, `miunlock devices`, `miunlock reboot-fastboot`, and a
  "Reboot to fastboot" button in the GUI): sees the phone while Android is running, shows
  its model, MIUI version and lock state, and reboots it into fastboot.
- `miunlock --mcp`: an MCP server so AI agents can list phones, reboot to fastboot, check
  eligibility and read the log directly. Unlocking is deliberately not offered to agents.
- Project logo (`assets/`), shown in the README, the GUI window and the Windows executables.
- Python API, `miunlock.api`, with `login`, `get_account_zone`,
  `get_device_codename`, `check_unlock_eligibility` and `perform_unlock`.
- Command line subcommands that print JSON: `login`, `status`, `check`, `unlock`.
- `miunlock-gui`, a small Tkinter GUI.
- `--confirm-wipe` / `confirm_wipe=True` confirmation for the unlock step in the
  CLI and API, and a confirmation dialog in the GUI.
- `login_method` option on `get_passtoken` to choose browser or QR login without a
  prompt.
- `NOTICE` file with attribution and the MIT notice for migate-derived code.
- Documentation rewritten into `docs/` with an index.
- `miunlock --version`.
- Release builds: Windows, Linux and macOS executables (`miunlock` and
  `miunlock-gui`), a wheel and an sdist, with SHA-256 checksums, built by GitHub
  Actions from the tagged source.
- CI that installs on three operating systems and checks the confirmation gate.

### Changed

- migate is merged into the package as `miunlock.auth`; `import migate` no longer
  works. There is now a single package and no external git dependency.
- The saved session moved from `~/.migatesession` to `~/.miunlocksession`.
- The session file is restricted to the current user after it is written.
- Installation is from this repository, not PyPI.
- The version number lives in one place, `miunlock.__version__`, and starts at
  1.8.0 (upstream was at 1.7.5).
- Minimum Python raised to 3.9, which the build backend requires.
- Running `miunlock` with no arguments behaves as before.

### Removed

- Upstream's manual "Publish to PyPI" workflow; this fork is not published on PyPI.
- Password ("Terminal") login and its two-factor helpers (`login/terminal.py`,
  `verify.py`, `sendcode.py`, `verifycode.py`). Only browser and QR login remain.
  The old code sent an unsalted MD5 of the account password to Xiaomi's login
  endpoint.

### Security

- The saved session is stored in the OS credential store (with `miunlock[secure]`) or
  encrypted with Windows DPAPI, expires after 24 hours (`MIUNLOCK_SESSION_TTL_HOURS`), and
  sessions without a timestamp are discarded.
- A scrubbed `miunlock.log` is written next to the executable.
- Error messages no longer print login or config responses, which carry session
  tokens; only status fields and field names are shown.
- Failed requests no longer report the URL, which contains one-time login tokens, and no
  longer chain the original exception into tracebacks.
- The session file is created owner-only from the start (and its folder restricted) instead
  of being tightened afterwards, and the program no longer claims it is protected if the
  restriction could not be applied.
- The signed unlock token goes to a private, randomly named temporary file, not a
  predictable file in the home folder.
- URLs from Xiaomi's responses are opened without a shell (previously a quote in the URL
  could run a command on Linux and Termux) and only if they are https.
- The GUI masks the account ID.
- CI: actions pinned to commits, read-only default token permissions, checkout no longer
  persists the token, and a regression test suite runs on every push.
- See [docs/safety.md](docs/safety.md) for the full model and its limits.
