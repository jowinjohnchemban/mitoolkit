# Safety model

This page explains what `miunlock` protects, what it deliberately does not do, and
what you are still responsible for. It also lists how this fork differs from the
original projects on security.

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
| Interactive (`miunlock`) | Shows Xiaomi's data-erase notice, then waits for Enter |
| Command line | `miunlock unlock` refuses without `--confirm-wipe` |
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

### Password login was removed

The original `migate` library also offered a "Terminal" login that read your
password in the console, computed an unsalted MD5 hash of it, and sent that to
Xiaomi's login endpoint. That mirrors Xiaomi's own legacy login protocol, but an
unsalted MD5 is equivalent to the password if it is ever intercepted or logged.
This fork deletes that code (`login/terminal.py` and its 2FA helpers) rather than
disabling it, so it cannot run.

### Saved session

After login the session (a long-lived `passToken`) is stored in the strongest place
available, and the program tells you which one it used:

| Where | When |
|---|---|
| OS credential store (Windows Credential Manager, macOS Keychain, Linux Secret Service) | `keyring` is installed: `pip install "miunlock[secure]"` |
| `~/.miunlocksession/<name>/session.dpapi`, encrypted with Windows DPAPI | Windows, no extra package |
| `~/.miunlocksession/<name>/session.json`, readable only by your user | everywhere else (not encrypted) |

**Expiry.** Every saved session carries a timestamp and is trusted for 24 hours. After
that it is deleted and you log in again. Set `MIUNLOCK_SESSION_TTL_HOURS` to change it
(`0` means never reuse a session). A session saved by an older version has no timestamp and
is treated as expired.

Deleting the session does not end it on Xiaomi's side. When you are finished:

1. Sign out (`miunlock` then choose log out, or **File > Sign out** in the GUI).
2. Check the signed-in devices for your account at `account.xiaomi.com`.
3. Consider changing the Mi Account password.

### Log file

`miunlock.log` is written in the same folder as the executable (the current folder when
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

In the code reviewed when this fork was made, requests go only to:

| Destination | Purpose |
|---|---|
| `account.xiaomi.com`, `api.account.xiaomi.com` | Login and account lookups |
| `unlock.update.miui.com`, `unlock.update.intl.miui.com`, `in-/ru-/eu-unlock.update.intl.miui.com` | Unlock service, chosen by account region |
| `dl.google.com` | Download of Google's platform-tools (`fastboot`), only if not installed |

No analytics or telemetry calls were found. On Android (Termux) only, the original
code additionally downloads a GPG key and an install script from the third-party
`nohajc/termux-adb` project and runs it; this path is not used on other systems.

## What was reviewed, and its limits

Every Python file in the original MiUnlockTool and migate was read when this fork
was created, looking for network destinations, credential handling and unsafe
subprocess use. The `fastboot` calls use fixed argument lists, not a shell, so
there is no shell-injection path.

This was a source review by the fork's maintainers, not an independent security
audit, and it covered the code as it was at that time. Review changes before you
trust new versions.

## Things to know

- **Request signing.** Requests to Xiaomi are signed with a key embedded in the
  code. It is Xiaomi's client signing scheme, not a secret that protects you, and
  the original project uses the same one.
- **Client version string.** `unlock.py` and `api.py` send `clientVersion`
  `7.6.727.43`. It is an identity string Xiaomi's server expects, not this tool's
  version.
- **Upstream report.** The original project's issue tracker has an unverified
  report of a password leak during Xiaomi's own two-factor step. Login happens on
  Xiaomi's page, which this project cannot change, so verify the page URL and
  consider changing your password afterwards.
- **Not on PyPI.** Install from this repository so the code you run is the code
  you can read. The unpatched upstream package on PyPI still contains the
  password-login path.

## Reporting a problem

See [SECURITY.md](../SECURITY.md).
