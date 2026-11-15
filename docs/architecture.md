# Architecture

`mitoolkit` is one Python package with a `src/` layout. The Xiaomi login code lives in
`mitoolkit.auth`.

## Layout

```text
src/mitoolkit/
├── __main__.py        python -m mitoolkit
├── cli.py             entry point: GUI by default, --cli, JSON subcommands (@json_command), --mcp
├── gui.py             main window (App)
├── ui/                the other windows, one class each, built from the components
│   ├── base.py            Dialog base class
│   ├── theme.py           colours, links, Fonts
│   ├── menu.py            the menu bar
│   ├── placement.py       keeps windows inside the free part of the screen
│   ├── guide_window.py    GuideWindow
│   ├── backup_dialog.py   BackupDialog
│   ├── apps_dialog.py     AppManagerDialog, AppRow
│   ├── security_dialog.py SecurityDialog
│   ├── driver_dialog.py   DriverHelpDialog
│   ├── live_dialog.py     LiveStatusDialog (gauges, graphs, cores, sensors, processes)
│   ├── log_dialog.py      LogDialog (logcat viewer)
│   ├── connect_dialog.py  ConnectionsDialog (Wi-Fi, modem, SIM, Bluetooth, USB; findings; network test)
│   ├── activity_window.py ActivityLog, ActivityWindow
│   └── components/        reusable widgets, independent of any one window
│       ├── buttons.py         Button / ModernButton (icons, state colours), segmented()
│       ├── button_row.py      a row of equal-width buttons that wraps
│       ├── selector.py        SelectorBar (Windows 11 style tabs / range)
│       ├── charts.py          LineChart, Gauge, Sparkline
│       ├── skeleton.py        shimmering loading placeholders and their shared clock
│       ├── scroll_page.py     a page that scrolls and keeps a readable width
│       ├── shapes.py          rounded cards, colour mixing
│       └── render.py          anti-aliased images with Pillow (rendered on worker threads)
├── details.py         "Show more": every detail a phone reports, in sections (parsers + collection)
├── monitor.py         live readings for Live status (CPU, cores, GPU, memory, battery, sensors, network, processes)
├── diagnostics.py     Wi-Fi, modem, SIM, Bluetooth, USB readings, parsers, plain-language findings, network test
├── workers.py         BackgroundPool: daemon worker threads, results delivered on the window's thread
├── watchdog.py        call_with_timeout, UiWatchdog (records freezes), crash logging
├── memory.py          Housekeeper: garbage collection, memory limit, closing frees windows
├── mcp.py             MCP server for AI agents (no unlock tool)
├── api.py             programmatic API used by the subcommands, GUI and MCP
├── xiaomi.py          UnlockServer: the requests to Xiaomi's unlock server, shared
├── errors.py          MitoolkitError, the base of every expected error
├── adb.py             Phone: details, reboot, backup, app manager (+ short functions)
├── adb_usb.py         built-in adb client (USB protocol, auth, shell, sync)
├── adb_server.py      adb through Google's adb server, when one is running
├── platform_tools.py  finds Google's adb/fastboot if already installed (never downloads)
├── adbkey.py          adb RSA key (~/.android/adbkey), pure Python
├── fastboot.py        Backend interface; UsbBackend, ExeBackend, AutoBackend
├── fastboot_usb.py    built-in fastboot client (USB protocol)
├── usbio.py           USB access through pyusb + libusb
├── drivers.py         USB driver help for Windows (steps + Google's download page)
├── bloat.py           known Xiaomi bloat, with ratings, for the app manager
├── security.py        read-only security check (OSV bulletins, Play Protect, app access, stalkerware)
├── guide.py           the in-app step-by-step guide
├── log.py             scrubbed mitoolkit.log next to the executable
├── hints.py           plain-English explanations of Xiaomi error codes
├── assets/logo.png    window icon
├── unlock.py          InteractiveUnlock: the prompting command-line flow
├── utils.py           request signing, encryption and the HTTP call to Xiaomi
├── system.py          platform detection helpers
└── auth/              Xiaomi account login
    ├── config.py          endpoint URLs and console styling
    ├── requester.py       shared HTTP session
    ├── passtoken.py       login flow
    ├── store.py           saved session: credential store, DPAPI or private file, 24 h expiry
    ├── service.py         service tokens for the unlock API
    ├── login/
    │   ├── browser_qr.py  browser and QR-code login
    │   ├── captcha.py     local captcha page (127.0.0.1)
    │   └── captcha.html
    └── utilities/         region, data center, locale and area lookups
```

## Design

- **One implementation per job.** The requests to Xiaomi live only in
  `xiaomi.UnlockServer`; `api.py` (non-interactive) and `unlock.InteractiveUnlock` (prompts)
  both use it. Region-to-zone mapping is `xiaomi.zone_for_region`.
- **Interfaces over branches.** `fastboot.Backend` is what the program needs from
  fastboot; `UsbBackend` implements it with the built-in USB client. The rest of the
  program calls `fastboot.get_product()`, `get_token()`, `stage_and_unlock()` without
  knowing the transport, so another one (such as an Android app's USB host API) can be
  added as a new subclass.
- **Objects for things with state.** `adb.Phone` wraps one connected phone;
  `adb_usb.AdbDevice` and `fastboot_usb.FastbootDevice` wrap the USB sessions;
  `adbkey.Key` is the RSA key. Module-level functions in `adb.py` are one-line short forms
  kept for the CLI, API and MCP.
- **One error base.** Every expected failure derives from `errors.MitoolkitError` and has a
  readable message. Each layer has one type (`AdbError`, `FastbootError`, `UsbError`,
  `UnlockError`); `api.py` turns lower-layer errors into `UnlockError`.
- **Windows as classes.** Each secondary window is a `ui.base.Dialog` subclass. They only
  use the App's small public interface: `root`, `fonts`, `run()`, `log()`, `call_soon()`.
- **CLI commands are plain functions** wrapped by `@json_command`, which prints the result
  as JSON and turns any `MitoolkitError` into `{"error": ...}` with exit status 1.

## Request flow

```text
login (browser or QR)  ──►  passToken saved to ~/.mitoolkitsession
        │
        ▼
service token  ──►  account region  ──►  data center  ──►  unlock server
        │
        ▼
fastboot getvar product  ──►  codename
        │
        ▼
POST /api/v2/nonce
POST /api/v2/unlock/device/clear      eligibility, wipe notice
        │
        ▼   ── confirmation: Enter / --confirm-wipe / confirm_wipe=True / dialog ──
        │
fastboot oem get_token   ──►  deviceToken
POST /api/v2/nonce                    nonces are single use
POST /api/v3/ahaUnlock                returns encryptData
        │
        ▼
download (stage) encryptData  ──►  oem unlock
```

The fastboot steps are mitoolkit's own USB client (`fastboot_usb.py`); `encryptData` goes
from memory straight to the phone and is never written to disk.

## Choosing how to reach the phone

Only one program can open a phone's USB interface, so mitoolkit picks the way that works:

- **adb**: if Google's adb server is running (it owns every phone in adb mode), mitoolkit
  asks it, over `127.0.0.1:5037`, exactly like the `adb` command does. Otherwise it uses its
  own USB connection and keeps it open between scans (it never re-probes a phone it already
  holds, which Windows would answer with "access denied").
- **fastboot**: the built-in USB client first. If it finds a phone it cannot open and
  Google's `fastboot` is already installed, that program is used for that phone.
- A phone that still cannot be opened is reported with the reason: another program has it
  (named, with **Stop Google's adb** when that is the one), no driver (Windows; driver help),
  or no permission (Linux; udev rule).

## Built-in adb and fastboot

Both clients follow AOSP's implementation (adb.cpp, client/auth.cpp,
daemon/file_sync_service.cpp, fastboot/README.md, fastboot_driver.cpp). Details that matter:

- adb: CNXN payload `host::features=` with no NUL; version `0x01000001`; the phone's token
  is signed with PKCS#1 v1.5 as a SHA-1 digest; if refused, the public key is sent in adb's
  own format with a trailing NUL. Writes whose length is a multiple of the USB packet size
  end with a zero-length packet. Each WRTE is acknowledged with OKAY.
- sync: `LIST` returns full-size `DENT` entries ending with a zeroed `DONE`; the phone ends
  the sync session after a `FAIL`, so the client reopens it.
- fastboot: responses are at most 256 bytes; `INFO`/`TEXT` repeat until `OKAY`, `FAIL` or
  `DATA`; downloads send no zero-length packet.

Everything above the confirmation line is read-only. See
[how it works](how-it-works.md) for what `deviceToken` and `encryptData` are.

## Data centers

The account region selects the unlock server:

| Zone | Server |
|---|---|
| China | `https://unlock.update.miui.com` |
| Singapore (default) | `https://unlock.update.intl.miui.com` |
| India | `https://in-unlock.update.intl.miui.com` |
| Russia | `https://ru-unlock.update.intl.miui.com` |
| Europe | `https://eu-unlock.update.intl.miui.com` |

## Entry points

Defined in `pyproject.toml`:

- `mitoolkit` → `mitoolkit.cli:main`
- `mitoolkit-gui` → `mitoolkit.gui:main` (alias; `mitoolkit` alone opens the GUI too)

With no arguments `mitoolkit` opens the GUI; `--cli` alone runs the interactive flow;
a subcommand uses `mitoolkit.api`; `--mcp` starts the agent interface.
