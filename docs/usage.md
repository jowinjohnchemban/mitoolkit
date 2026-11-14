# Usage

`miunlock` can be used three ways: an interactive prompt, a scriptable command
line, and a small GUI. All three talk to the same code and the same Xiaomi
servers.

Before you start, follow the [unlock guide](unlock-guide.md) to add your account
and device in *Mi Unlock status*, and read the [safety model](safety.md).

## Interactive mode

```sh
miunlock
```

Run with no arguments, it walks through the whole process:

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

## GUI

```sh
miunlock-gui
```

Three buttons run the same steps in order: **Log in**, **Check eligibility** and
**Unlock device**. The unlock button stays disabled until the check says the
device is eligible. Clicking it opens a confirmation dialog that shows the
server's data-erase notice; nothing happens unless you answer **Yes**. There is
no "don't ask again" option.

The GUI uses Tkinter, which ships with Python on Windows and macOS. On some Linux
distributions install it separately, for example `sudo apt install python3-tk`.

## Saved session

After a successful login the session is saved to:

```text
~/.miunlocksession/unlockApi/session.json
```

It contains a long-lived `passToken`, which acts like a password for your Mi
Account until it expires. The file is restricted to your user account, but you
should still delete it when you are done:

```sh
# Windows (PowerShell)
Remove-Item -Recurse $HOME\.miunlocksession
# macOS / Linux / Termux
rm -rf ~/.miunlocksession
```

Then review the account's signed-in devices at `account.xiaomi.com`. Deleting the
file does not end the session on Xiaomi's side.
