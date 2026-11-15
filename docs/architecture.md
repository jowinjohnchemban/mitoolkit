# Architecture

`miunlock` is one Python package with a `src/` layout. The Xiaomi login code that
used to be the separate `migate` library lives inside it as `miunlock.auth`.

## Layout

```text
src/miunlock/
├── __main__.py        python -m miunlock
├── cli.py             entry point: GUI by default, --cli, JSON subcommands, --mcp
├── gui.py             Tkinter GUI
├── mcp.py             MCP server for AI agents (no unlock tool)
├── api.py             programmatic API used by the subcommands, GUI and MCP
├── adb.py             adb features: phones, details, reboot, backup, app manager
├── adb_usb.py         built-in adb client (USB protocol, auth, shell, sync)
├── adbkey.py          adb RSA key (~/.android/adbkey), pure Python
├── fastboot.py        fastboot features: devices, getvar, token, stage + oem unlock
├── fastboot_usb.py    built-in fastboot client (USB protocol)
├── usbio.py           USB access through pyusb + libusb
├── drivers.py         Google USB driver installer (Windows)
├── bloat.py           known Xiaomi bloat, with ratings, for the app manager
├── guide.py           the in-app step-by-step guide
├── log.py             scrubbed miunlock.log next to the executable
├── hints.py           plain-English explanations of Xiaomi error codes
├── assets/logo.png    window icon
├── unlock.py          the original interactive unlock sequence
├── commands.py        Termux only: fastboot queries through the fastboot command
├── utils.py           request signing, encryption and the HTTP call to Xiaomi
├── system.py          platform detection helpers
├── termux.py          Android (Termux) fastboot setup
└── auth/              Xiaomi account login (formerly migate)
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

`unlock.py` (interactive) and `api.py` (non-interactive) both implement the same
request sequence. They are kept separate because the interactive flow prompts the
user in the middle. If Xiaomi changes the protocol, update both.

## Request flow

```text
login (browser or QR)  ──►  passToken saved to ~/.miunlocksession
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

The fastboot steps are miunlock's own USB client (`fastboot_usb.py`); `encryptData` goes
from memory straight to the phone and is never written to disk. On Termux the termux
`fastboot` command is used instead, because Android apps cannot open USB devices directly.

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

- `miunlock` → `miunlock.cli:main`
- `miunlock-gui` → `miunlock.gui:main` (alias; `miunlock` alone opens the GUI too)

With no arguments `miunlock` opens the GUI; `--cli` alone runs the interactive flow;
a subcommand uses `miunlock.api`; `--mcp` starts the agent interface.
