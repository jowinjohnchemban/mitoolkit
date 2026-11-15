# Usage

`miunlock` is one program with three ways to drive it:

| Run | You get |
|---|---|
| `miunlock` | The GUI |
| `miunlock --cli` | The interactive prompt |
| `miunlock <command>` (optionally `--cli <command>`) | Scriptable commands that print JSON |
| `miunlock --mcp` | An interface for AI agents, see [agents](agents.md) |

The Windows program has no console window when it opens the GUI; for `--cli`, commands and `--mcp` it
uses the terminal that started it. All three talk to the same code and the same Xiaomi
servers.

Before you start, follow the [unlock guide](unlock-guide.md) to add your account
and device in *Mi Unlock status*, and read the [safety model](safety.md).

## Interactive mode

```sh
miunlock --cli
```

It walks through the whole process:

1. Finds `fastboot`, or downloads Google's platform-tools if it is missing.
2. Logs in. If a saved session exists it offers to reuse it; otherwise it asks for
   **Browser** or **QR code** login. Log in on the Xiaomi page that opens (check
   the address bar says `account.xiaomi.com`).
3. Detects your account region and the matching Xiaomi unlock server, and lets
   you change the data center if it guessed wrong.
4. Reads the device codename from the phone (it must be in fastboot mode) and asks
   Xiaomi whether the device can be unlocked.
5. Tells you whether user data will be erased, then waits for you to press Enter.
   **Pressing Enter at this point starts the unlock.**

## Command line

The subcommands are meant for scripts and automation. Each prints JSON on stdout
and exits with status `0` on success and `1` on failure.

| Command | What it does | Changes the device? |
|---|---|---|
| `miunlock login [--method 1\|3] [--force]` | Log in, or reuse a saved session | No |
| `miunlock devices` | Phones seen by adb (model, MIUI, lock state) and fastboot | No |
| `miunlock reboot-fastboot [--serial S]` | adb: reboot a running phone into fastboot | Restarts only |
| `miunlock status` | Account, region and device codename | No |
| `miunlock check` | Ask Xiaomi if the device is eligible right now | No |
| `miunlock unlock --confirm-wipe` | Unlock the bootloader | **Yes, erases data** |

`--method 1` is browser login (default) and `--method 3` is QR code. `--force`
ignores a saved session and logs in again. First-time login still needs a person
to finish logging in on Xiaomi's page; there is no unattended login.

`unlock` refuses to run without `--confirm-wipe`:

```text
$ miunlock unlock
{
  "success": false,
  "error": "Refusing to unlock: --confirm-wipe was not passed. ..."
}
```

### Example output

```sh
$ miunlock status
{
  "logged_in": true,
  "userId": "1234567890",
  "zone": "India",
  "device_codename": "example"
}
```

```sh
$ miunlock check
{
  "eligible": false,
  "product": "example",
  "zone": "India",
  "code": 20036,
  "description": "Please unlock 168 hours later. ..."
}
```

When eligible, `check` returns `"eligible": true` together with
`will_wipe_data` and the server's `notice`.

> **Note:** `status`, `check` and `unlock` read the device over `fastboot`. If no
> device is in fastboot mode they wait for one, so press Ctrl+C to stop. Put the
> phone in fastboot mode and connect it first.

### backup

```sh
miunlock backup --dest D:\\phone-backup --only photos,documents
```

Copies folders from a phone running Android to your computer with `adb pull`, and writes
`installed-apps.txt`. Choices for `--only`: `photos`, `documents`, `chats`, `audio`,
`everything`. Read-only for the phone; progress goes to stderr and the result is JSON.

### install-tools and install-driver

```sh
miunlock install-tools     # latest adb and fastboot (Android platform-tools) from dl.google.com
miunlock install-driver    # Windows: Google's official USB driver, via pnputil (UAC prompt)
```

`install-tools` replaces the copy in `~/platform-tools`; a system-wide adb/fastboot is left
alone. `install-driver` logs the download's SHA-256 and installs with Windows' own
`pnputil`. Google's driver does not list Xiaomi's USB IDs, so if Windows does not use it by
itself, pick it in Device Manager: *Update driver > Browse my computer > Let me pick >
Android Device > Android Bootloader Interface*. Both are also in the GUI's **File** menu.

## GUI

```sh
miunlock          # or: miunlock --gui
```

Three steps run in order: **Sign in**, **Check** and **Unlock**. The GUI detects a
phone in fastboot mode by itself and explains Xiaomi's error codes in plain words. The
unlock button stays disabled until the check says the device is eligible, you tick the
confirmation box and you type the phone's name exactly. There is no "don't ask again" option.

The GUI uses Tkinter, which ships with Python on Windows and macOS. On some Linux
distributions install it separately, for example `sudo apt install python3-tk`.

Handy features:

- **Help > Step-by-step guide** (F1) opens the unlock guide inside the program, offline.
- The page scrolls, with a scrollbar and mouse wheel, so nothing is cut off on small or
  scaled screens.
- **Show details** reveals what the program is doing, with **Copy** and **Clear** buttons.
- The numbered badges are grey (not yet), orange (do this next) and green (done).
- Ctrl+Q quits.
- Connected phones show their details (model, versions, bootloader state, battery). **Copy
  info** copies them, **Rescan** looks again, and a tip appears if no phone shows up for 20 s.
- **Back up files...** copies photos, documents, chat media and more from a phone that is on.
- When Xiaomi says to wait, the message includes the date and time to try again.

## Saved session and log

The session is stored encrypted where the system allows it (credential store or Windows
DPAPI), expires after 24 hours, and is removed by logging out. Details, including how to
change the expiry, are in the [safety model](safety.md#saved-session).

Everything the program does is also recorded in `miunlock.log`, next to the executable.
It contains no tokens. In the GUI, **File > Show log file** opens its folder.
