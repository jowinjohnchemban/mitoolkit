# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Updates over the air: Help > Check for updates downloads the latest release of the single-file program,
  checks it against `SHA256SUMS.txt`, swaps it in and restarts; a daily quiet check (can be turned off) tells
  you in the status line. Releases are automatic: changing `__version__` on main builds and publishes the
  release (programs, packages, checksums, notes from this file).
- The version reads `v1.8.0 (build: DDMMYYYY-commit)` in the title bar, About, `--version` and the log.
- Export device details as text, CSV or Markdown (button and Phone menu), a Sign out button in the Mi
  Account section, and a Restart or power off dialog (Android, recovery, fastboot, off). In fastboot mode the
  dialog offers Cancel and start Android, or recovery.
- A quick, local security look colours the Security check button as soon as a phone connects; the full
  check takes over once run.
- Debug logging: `--debug`, `MIUNLOCK_DEBUG=1`, or Help > Debug logging.
- An About window with version information to copy, and `CREDITS.md`.
- Backup is resumable and verified: unchanged files are skipped, copies are size-checked and retried, failures
  are listed in `backup-problems.txt`, and a phone that stops answering ends the run instead of failing every file.
- Wireless adb (Phone > Wireless adb): switch a plugged-in phone to Wi-Fi debugging and connect, or
  connect by address, through Google's adb server. Fastboot and unlocking stay USB-only; a phone
  connected over Wi-Fi is asked to be plugged in before it reboots into fastboot.
- Unplugging the phone is noticed within a second, and Live status and Connections say so at once. Their
  top bars no longer rewrite themselves on every automatic update.
- `miunlock details` and `miunlock connections [--network-test]` commands, and MCP tools
  `device_details` and `connections`, so scripts and agents can use the same readings. Agents are not
  shown what identifies the phone or its owner (serial number, IMEI, addresses, network and device
  names).
- Connections and signal (step 2, or Phone menu): Wi-Fi (signal, band and channel, speeds, router, DNS,
  nearby networks), mobile network and modem (registration, operator, 4G/5G, RSRP, RSRQ, SINR, cell and
  band, whether Android confirmed internet), SIM, Bluetooth, USB and power, with plain-language
  findings, live signal graphs and an optional network test. Read-only apart from the pings you ask for.
- A smoke test opens every window, builds every menu and enlarges the text to 200% with everything open,
  failing on any error Tk would otherwise swallow. It found (and fixed) a crash in the USB driver help
  window. Text in every state of the new buttons, selector and charts is now checked for contrast.
- Built to stay up: a watchdog records what froze if the window ever stops answering for 4 seconds
  (every thread's stack goes to the log file), phone calls that never return are given up on after
  15 to 40 seconds and retried, crashes and background-thread errors are logged, and the program
  says what happened instead of vanishing. Fixed the Live status freeze: the loading placeholders'
  shared timer doubled itself every frame.
- Worker threads for drawing: chart images are rendered by a small pool of daemon threads (they never
  keep the program from closing) and shown when ready, so the window never waits for Pillow.
- Memory hygiene: a garbage collection after start-up (then `gc.freeze()`), a light one every 30 s and a
  full one every 5 min, a full one whenever a window closes, a least-recently-used image cache, and a
  500 MB limit that releases rebuildable caches. Closing a window now really frees it: variable
  callbacks that kept it alive in Tk's command table, a worker thread's leftover job and the loading
  clock's references were found and removed, with tests that check it.
- Reusable widgets now live in `miunlock/ui/components/` (buttons, charts, selector, skeleton, ...).
- More to service and debug a phone: Show more now has modem and telecom, SIM card, board and chip,
  connectivity and state, servicing and debugging, and partition sections (only what the phone
  reports); Phone > Log viewer (logcat with filters, copy, save); and Phone > Reboot to recovery mode,
  Restart Android and Power off (each asks first; nothing is erased).
- High resolution, anti-aliased graphs (Pillow): curves, gradients, gauge rings and card shadows are
  drawn at 2 to 3 times the size and scaled down, so nothing looks pixelated. Chart.js / ECharts style:
  smooth curves that don't overshoot, a gradient under the line, a time axis with quarter ticks, tick
  marks on the gauges. Falls back to plain canvas drawing if Pillow is missing.
- Skeleton loading placeholders (shimmering grey shapes, like React skeleton libraries and Tailwind's
  animate-pulse) while the first readings, details or Xiaomi's answer arrive. They hold still when
  MIUNLOCK_REDUCED_MOTION=1.
- Windows 11 style controls: flat rounded buttons with icons (Segoe icons) and a selector bar with a
  sliding accent indicator for the tabs and time range (the system's toggle buttons on macOS).
- Smoother and safer live data: readings that arrive together are all graphed but drawn once; hidden
  tabs and windows aren't redrawn; lists rebuild only while visible; a failing phone is retried with
  back-off; one odd reading loses only that value; errors in a handler are logged, never fatal.
- Windows open inside the free part of the screen: the taskbar, menu bar, Dock or panels are never
  covered. The work area comes from the system (Windows, Linux window managers) or a safe margin, and
  after opening the window's real frame is measured and pulled inside if needed.
- Show more: every detail the phone gives over USB (serial number, IMEI where Android allows it,
  Android ID, Wi-Fi/Bluetooth address, fingerprint, hardware, boot, SIM, battery), or every
  bootloader variable in fastboot mode. The serial number is no longer masked.
- Live status window (Phone > Live status) laid out like a Grafana dashboard: four tabs (Overview,
  Processor, Sensors, Processes) so each list has its own page and one scrollbar, panels as cards with
  a last/min/avg/max legend, threshold lines and green/yellow/red gauges with the state in words, a
  Live/Paused marker and a time range from 1 minute to 1 hour. Ring gauges and ECharts-styled graphs (smooth lines, soft
  fill, tooltip, peak marker) of processor, memory, battery, power, temperature and network, one reading
  a second with 1, 5 and 15 minute views. Adds per-core trends, GPU load and speed where the phone
  reports them, every thermal sensor, and a sortable, searchable task-manager style process list
  (read-only).
- Modern buttons: rounded, Windows 11 style buttons with a 3:1 border, hover and pressed states, a
  strong keyboard focus ring and an accent-filled main action (the system's own buttons on macOS);
  segmented buttons for choices such as the graph time range.
- Show more adds what is specific to the phone when it reports it: Xiaomi / HyperOS details, hardware
  features, display refresh rates, storage type, OpenGL ES, battery cycles and health, apps installed.
- The tool buttons in step 2 line up in one equal-width row that wraps evenly.
- GUI shows device details when a phone is connected: model, codename, Android and HyperOS/MIUI
  version, security patch, bootloader state, battery and a masked serial (fastboot mode shows
  codename, bootloader state and version, and active slot).
- Built-in adb and fastboot: miunlock speaks both USB protocols itself (pyusb + libusb),
  checked against AOSP's sources. Google's platform-tools are no longer downloaded. adb uses
  the same `~/.android/adbkey` as Google's adb.
- App manager (debloat): **Manage apps...** in the GUI and `miunlock apps list|remove|restore`
  list every app with a rating from a curated Xiaomi bloat list, remove ticked apps for your
  user (`pm uninstall --user 0`) and restore them.
- Windows USB driver help: *File > USB driver help* and `miunlock driver-help --open` list the
  steps and open Google's download page. miunlock does not download or install drivers.
- New look: each system uses its own native theme (Windows native on Windows, Aqua on macOS), and
  a light flat style on Linux (Tk's "clam"). An image-based Windows 11 theme was tried and dropped:
  it repainted 3x slower, so parts of the window painted late. One font family and type scale,
  a single plain window of four sections with a "Next:" line and the standard menus (File, Unlock,
  Phone, View, Help: Alt mnemonics, shortcuts, greyed-out entries, Command key on macOS), dialogs
  centred on the screen,
  the Activity log in its own window with the latest line in the status bar, device details in
  two columns.
- Accessibility (WCAG 2.2 AA): contrast checked by tests, visible focus on every control,
  keyboard access to everything, text size up to 200% (Ctrl + / Ctrl - / Ctrl 0).
- More device details: build, region, chipset, memory, storage, screen, kernel, verified boot,
  encryption, battery temperature; in fastboot: secure boot, variant, hardware revision,
  anti-rollback index, fastbootd vs bootloader.
- Security check (GUI **Security check...**, `miunlock security-check`, MCP `security_check`),
  read-only: missing Android security fixes and end of support from OSV's Android Security
  Bulletin data; Google Play Protect and Play system update; apps not from a store, apps that
  may install apps, apps with accessibility / notification / device-admin access; known
  stalkerware from AssoEchap's indicators, confirmed by signing certificate when possible.
- App manager redesigned: tabs with counts, plain-word ratings with a legend, a details panel
  for the selected app, and one action button that says what it does.
- Picks the best way to reach the phone: through Google's adb server when it is running
  (no conflict, nothing to stop), else the built-in USB adb; built-in fastboot, with an
  installed Google `fastboot` as a fallback for a phone the built-in client cannot open.
  When a phone still cannot be opened, the GUI says why (another program, which is
  named; missing driver; or permissions) and offers the fitting action.
- Step 2 of the GUI shows the phone's state as a headline, an explanation and the buttons
  that fit; windows size themselves to the screen; the guide's buttons and the app
  manager's columns always fit.
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

First release. See [CREDITS](CREDITS.md) for where it started.

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
- `NOTICE` file with the third-party license notice.
- Documentation rewritten into `docs/` with an index.
- `miunlock --version`.
- Release builds: Windows, Linux and macOS executables (`miunlock` and
  `miunlock-gui`), a wheel and an sdist, with SHA-256 checksums, built by GitHub
  Actions from the tagged source.
- CI that installs on three operating systems and checks the confirmation gate.

### Changed

- The Xiaomi login code is part of the package as `miunlock.auth`: a single package and no
  external git dependency.
- The saved session is `~/.miunlocksession`.
- The session file is restricted to the current user after it is written.
- Installation is from this repository, not PyPI.
- The version number lives in one place, `miunlock.__version__`.
- Minimum Python raised to 3.9, which the build backend requires.
- Running `miunlock` with no arguments behaves as before.

### Removed

- Password ("Terminal") login and its two-factor helpers. Only browser and QR login remain:
  a password login would send an unsalted MD5 of the account password to Xiaomi's login endpoint.

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
