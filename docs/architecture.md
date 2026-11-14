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
├── adb.py             adb: list phones, device info, reboot to fastboot
├── log.py             scrubbed miunlock.log next to the executable
├── hints.py           plain-English explanations of Xiaomi error codes
├── assets/logo.png    window icon
├── unlock.py          the original interactive unlock sequence
├── commands.py        fastboot queries: product, device token
├── fastboot.py        locate or download fastboot
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
fastboot stage <file>  ──►  fastboot oem unlock
```

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
