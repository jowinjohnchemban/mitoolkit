# Safety model

This page explains what `mitoolkit` protects, what it deliberately does not do, and
what you are still responsible for.

## What can go wrong

Two things in this process are sensitive:

- **Your Mi Account.** Logging in produces a session token that can act as your
  account until it expires.
- **Your device's data.** Unlocking the bootloader erases user data on most models
  and cannot be reversed.

## The destructive step is gated

Only one operation touches the device's lock state: `fastboot oem unlock`. Every
interface puts a deliberate human action in front of it.

| Interface | Gate |
|---|---|
| Interactive (`mitoolkit`) | Shows Xiaomi's data-erase notice, then waits for Enter |
| Command line | `mitoolkit unlock` refuses without `--confirm-wipe` |
| Python API | `perform_unlock(..., confirm_wipe=True)` is required; there is no default |
| AI agent (`--mcp`) | Unlocking is not offered at all; agents can only read and check |
| GUI | A tick box plus typing the phone's name exactly; the button stays disabled until both are done |

Nothing in the project sets these for you, and there is no environment variable or
config option that does. Reading and checking (`login`, `status`, `check`) can be
automated freely because none of it can erase anything.

If you wire this into automation, a person should decide to set the confirmation
every time. Do not hard-code it, and do not let an unattended job or an AI agent
decide it.

A rejected request does not touch the device. Errors such as 20031 or 20036 are
returned by Xiaomi's server before any token is issued, so `fastboot oem unlock`
never runs.

## Authentication

### Browser or QR login only

Login opens Xiaomi's real login page in your browser, or prints a QR code to scan.
The password is typed into Xiaomi's page and never passes through this program.
Always check the address bar says `account.xiaomi.com` before entering anything.

### No password login

There is no login that reads your password in the console: such a login would send an
unsalted MD5 of it, which is as good as the password if it is ever intercepted or logged.
That code is not part of this program, so it cannot run.

### Saved session

After login the session (a long-lived `passToken`) is stored in the strongest place
available, and the program tells you which one it used:

| Where | When |
|---|---|
| OS credential store (Windows Credential Manager, macOS Keychain, Linux Secret Service) | `keyring` is installed: `pip install "mitoolkit[secure]"` |
| `~/.mitoolkitsession/<name>/session.dpapi`, encrypted with Windows DPAPI | Windows, no extra package |
| `~/.mitoolkitsession/<name>/session.json`, readable only by your user | everywhere else (not encrypted) |

**Expiry.** Every saved session carries a timestamp and is trusted for 24 hours. After
that it is deleted and you log in again. Set `MITOOLKIT_SESSION_TTL_HOURS` to change it
(`0` means never reuse a session). A session saved by an older version has no timestamp and
is treated as expired.

Deleting the session does not end it on Xiaomi's side. When you are finished:

1. Sign out (`mitoolkit` then choose log out, or **File > Sign out** in the GUI).
2. Check the signed-in devices for your account at `account.xiaomi.com`.
3. Consider changing the Mi Account password.

### Log file

`mitoolkit.log` is written in the same folder as the executable (the current folder when
run from source), is limited to your user, and rotates at 512 KB with three old copies. It
records steps, result codes and error types. A scrubber hides token-like values and
account IDs even if one reaches a message. Even so, glance through it before posting it in
a bug report. If the folder is not writable the program runs without a log file.

### What is kept out of messages and logs

A login response from Xiaomi contains session tokens, so the program never prints one.
Error messages show only the status fields Xiaomi returns (such as the code and
description) and the *names* of the other fields. A failed network request reports the
kind of failure, not the request URL, because that URL carries one-time login tokens.
The GUI shows your account ID with the middle hidden, for example `123***890`, so a
screenshot does not expose it. Details you copy from the GUI or terminal are safe to
paste into an issue, but still glance at them first.

The signed unlock token is written to an owner-only temporary file with an unpredictable
name and deleted as soon as `fastboot` has used it.

Links are opened in your browser as a single argument and never through a shell, and
only `https` links (or the local captcha page) are opened.

## Network activity

In the code as reviewed, requests go only to:

| Destination | Purpose |
|---|---|
| `account.xiaomi.com`, `api.account.xiaomi.com` | Login and account lookups |
| `unlock.update.miui.com`, `unlock.update.intl.miui.com`, `in-/ru-/eu-unlock.update.intl.miui.com` | Unlock service, chosen by account region |
| `api.osv.dev` | Security check only: Android security bulletin entries. Sends the Android version and AOSP project names, nothing about your apps or account |
| `raw.githubusercontent.com` | Security check only: the stalkerware indicator list (AssoEchap/stalkerware-indicators), downloaded at most weekly and cached in `~/.mitoolkit/cache` |
| `api.github.com`, `github.com` | Updates: once a day (Help > Check for updates automatically can be turned off) the app asks for the latest release of this project. Sends nothing about you or the phone. Downloading an update happens only when you press the button, only from this project's releases, and is checked against the release's `SHA256SUMS.txt` before it is installed. The programs are not code-signed, so that check catches damaged downloads, not a compromised release |
| `127.0.0.1:5037` | Google's adb server on this computer, when it is running (never leaves the computer) |

Two more things send traffic, and neither goes through this program:

- **Connections > Network test** makes the *phone* ping its router, `8.8.8.8` and look up `google.com`
  (a few small packets). It runs only when you press the button.
- **Everything else is local.** Live status, Connections, Show more and the Log viewer only read from
  the phone and show it on screen. Connections and the log can contain your Wi-Fi name, router address,
  paired Bluetooth device names and app names, so check what you copy, save or share.

Commands run on the phone are fixed strings, plus a few values that are validated first (a restart mode
from a short list, a line count as a number, a router address as an IP). Nothing a phone reports is ever
put into a shell command unchecked.

No analytics or telemetry calls were found. The original code's Android (Termux) path,
which downloaded and ran an install script from the third-party `nohajc/termux-adb`
project, has been removed.

## What was reviewed, and its limits

The source was read for network destinations, credential handling and unsafe
subprocess use. Subprocess calls use fixed argument lists, not a shell, so there is no
shell-injection path.

This was a source review by the maintainers, not an independent security audit, and it
covered the code as it was at that time. Review changes before you trust new versions.

## Things to know

- **Request signing.** Requests to Xiaomi are signed with a key embedded in the
  code. It is Xiaomi's client signing scheme, not a secret that protects you.
- **Client version string.** `unlock.py` and `api.py` send `clientVersion`
  `7.6.727.43`. It is an identity string Xiaomi's server expects, not this tool's
  version.
- **Login happens on Xiaomi's page**, which this project cannot change: verify the page
  URL, and consider changing your password if you doubt it.
- **Not on PyPI.** Install from this repository so the code you run is the code
  you can read.

## Reporting a problem

See [SECURITY.md](../SECURITY.md).
