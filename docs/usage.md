# Usage

`mitoolkit` is one program with three ways to drive it:

| Run | You get |
|---|---|
| `mitoolkit` | The GUI |
| `mitoolkit --cli` | The interactive prompt |
| `mitoolkit <command>` (optionally `--cli <command>`) | Scriptable commands that print JSON |
| `mitoolkit --mcp` | An interface for AI agents, see [agents](agents.md) |

The Windows program has no console window when it opens the GUI; for `--cli`, commands and `--mcp` it
uses the terminal that started it. All three talk to the same code and the same Xiaomi
servers.

Before you start, follow the [unlock guide](unlock-guide.md) to add your account
and device in *Mi Unlock status*, and read the [safety model](safety.md).

## Interactive mode

```sh
mitoolkit --cli
```

It walks through the whole process:

1. Checks it can use USB (adb and fastboot are built in).
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
| `mitoolkit login [--method 1\|3] [--force]` | Log in, or reuse a saved session | No |
| `mitoolkit devices` | Phones seen by adb (model, MIUI, lock state) and fastboot | No |
| `mitoolkit reboot-fastboot [--serial S]` | adb: reboot a running phone into fastboot | Restarts only |
| `mitoolkit status` | Account, region and device codename | No |
| `mitoolkit check` | Ask Xiaomi if the device is eligible right now | No |
| `mitoolkit unlock --confirm-wipe` | Unlock the bootloader | **Yes, erases data** |

`--method 1` is browser login (default) and `--method 3` is QR code. `--force`
ignores a saved session and logs in again. First-time login still needs a person
to finish logging in on Xiaomi's page; there is no unattended login.

`unlock` refuses to run without `--confirm-wipe`:

```text
$ mitoolkit unlock
{
  "success": false,
  "error": "Refusing to unlock: --confirm-wipe was not passed. ..."
}
```

### Example output

```sh
$ mitoolkit status
{
  "logged_in": true,
  "userId": "1234567890",
  "zone": "India",
  "device_codename": "example"
}
```

```sh
$ mitoolkit check
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
mitoolkit backup --dest D:\\phone-backup --only photos,documents
```

Copies folders from a phone running Android to your computer over adb, and writes
`installed-apps.txt`. Choices for `--only`: `photos`, `documents`, `chats`, `audio`,
`everything`. Read-only for the phone; progress goes to stderr and the result is JSON.

### apps

```sh
mitoolkit apps list --known                       # known bloat on the phone, with ratings
mitoolkit apps list                               # every app
mitoolkit apps remove com.miui.msa.global         # remove for your user (restorable)
mitoolkit apps restore com.miui.msa.global        # bring it back
```

Removing uses `pm uninstall -k --user 0`: a preinstalled app is hidden for your user and
can be restored; an app you installed yourself is uninstalled. Unlocking resets the phone,
which brings removed apps back. Ratings: `recommended`, `optional`, `advanced`, `avoid`,
`unknown` (see `src/mitoolkit/bloat.py`).

### security-check

```sh
mitoolkit security-check
```

Read-only check of a phone running Android, printed as JSON:

- **Phone software**: the security patch level compared with the Android Security Bulletin
  entries in [OSV](https://osv.dev) for your Android version (AOSP data). Reports missing
  fixes by severity and whether the Android version still receives fixes. Xiaomi and
  chip-maker fixes are not in OSV.
- **Google Play**: Play Protect on or off, the Google Play system update date, apps not
  installed from a store, apps allowed to install other apps.
- **Apps**: apps with accessibility, notification or device-admin access, and a comparison
  with [known stalkerware](https://github.com/AssoEchap/stalkerware-indicators) (package name,
  confirmed by signing certificate where the app has a v1 signature).

It is not an antivirus; keep Google Play Protect on. The GUI has the same check under
**Security check...** in step 2.

### details

```sh
mitoolkit details [--serial S]
```

Everything a phone running Android reports over USB (what **Show more** shows), as JSON: identity
(serial number, IMEI, Android ID, addresses), software, hardware and board, boot, modem and telecom,
the SIM card, connectivity and state, servicing and debugging, partitions, sensors, battery. Read-only.
Only what the phone reports is included.

### connections

```sh
mitoolkit connections [--serial S] [--network-test]
```

Wi-Fi, mobile network (modem), SIM, Bluetooth, USB and power readings with plain-language `findings`
(worst first, each with what to try), as JSON: the same as the **Connections** window. Read-only.
`--network-test` also has the phone ping its router and `8.8.8.8` and look up a name; without it no
traffic is sent.

### doctor

```sh
mitoolkit doctor                # what is wrong, as JSON; exit code 1 if something is broken
mitoolkit doctor --fix          # also repair what is safe to repair
mitoolkit doctor --fix --all    # and what needs a decision
mitoolkit doctor --no-phone     # leave the USB bus alone
```

Checks Python and the window toolkit, USB access (libusb), the adb key, the saved Mi Account session's
permissions, the settings file, files left by an update, the log file, Google's adb, and any connected phone
(waiting for you to allow it, not answering, held by another program, missing driver). Each problem says what
is wrong in plain words. In the window it is **Help > Check and fix problems...**.

**Safe fixes** run by themselves at start-up (listed in the Activity log) and with `--fix`: making the adb key
and the saved session private to you, resetting a damaged settings file (the old one is kept as `.damaged`),
removing files an update left behind, and dropping a stuck phone connection. **Fixes that need a decision**
(stopping Google's adb, making a new adb key because the old one is damaged: each phone then asks to allow it
once) run only when you press their button or pass `--all`. It never touches the phone's data, Xiaomi's
servers or the contents of the session, and makes no network request. AI agents get the diagnosis only.

### driver-help

```sh
mitoolkit driver-help          # Windows: how to install Google's USB driver
mitoolkit driver-help --open   # ... and open Google's download page
```

mitoolkit does not download or install drivers; you install Google's driver with Device
Manager. The same help is in the GUI under *Help > USB driver help*.

## GUI

```sh
mitoolkit          # or: mitoolkit --gui
```

Three steps run in order: **Sign in**, **Check** and **Unlock**. The GUI detects a
phone in fastboot mode by itself and explains Xiaomi's error codes in plain words. The
unlock button stays disabled until the check says the device is eligible, you tick the
confirmation box and you type the phone's name exactly. There is no "don't ask again" option.

The GUI uses Tkinter, which ships with Python on Windows and macOS. On some Linux
distributions install it separately, for example `sudo apt install python3-tk`.

One plain window with the system's own look and the usual menus: **File**, **Unlock** (sign in, check eligibility), **Phone** (rescan, reboot, back up, apps,
security check, copy details), **View** (text size) and **Help**. Entries that can't work yet (no phone,
not signed in) are greyed out. The unlock itself is deliberately not in a menu: it erases the phone, so it
is only reachable through the guarded button. Dialogs open in the centre of the screen.
Four sections run top to bottom: **Mi Account**, **Phone**, **Eligibility**, **Unlock**. A line
at the top (**Step 2: ...**, with the number of the step to do now) says what to do next. The status line at the bottom shows the latest
activity; **File > Activity log** opens the full log.

Keyboard: **Alt** + the underlined letter opens a menu, **F1** guide, **F5** rescan, **Ctrl L** activity log,
**Ctrl +** / **Ctrl -** / **Ctrl 0** text size (up to 200%), **Ctrl Q** quit (**Command** instead of Ctrl on macOS), **Esc** closes a dialog, **Tab** moves between controls, **Space** ticks an
app in the app manager.

Accessibility: the interface follows WCAG 2.2 AA where Tk allows: text contrast of at least
4.5:1 (checked by `tests/test_accessibility.py`), visible keyboard focus, every action
reachable by keyboard, colour never the only signal, and text that scales to 200%.

Handy features:

- **Guide** (top right) (F1) opens the unlock guide inside the program, offline.
- The page scrolls, with a scrollbar and mouse wheel, so nothing is cut off on small or
  scaled screens.
- **File > Activity log** opens the log of what the program is doing, with **Copy** and **Clear**.
- The numbered badges are grey (not yet), orange (do this next) and green (done).
- Connected phones show their details (model, versions, bootloader state, battery). **Copy
  info** copies them, **Rescan** looks again, and a tip appears if no phone shows up for 20 s.
- **Back up files...** copies photos, documents, chat media and more from a phone that is on.
- **Manage apps...**: tabs for Suggested, All preinstalled, Installed by you and Removed;
  ratings in plain words (Safe to remove, Optional, Caution, Keep, Unknown); a panel that
  explains the selected app; one button that says what it will do ("Remove 3 apps").
- **Security check...**: the read-only check described under `security-check`.
- **Connections...** (step 2, or Phone > Connections and signal) is for debugging Wi-Fi, mobile data and
  calls. It reads (nothing is changed) and shows, in tabs: a **Summary** of what looks wrong and what to
  try (airplane mode, weak or crowded Wi-Fi, Wi-Fi with no internet or no DNS, no SIM or a locked SIM,
  no mobile service, poor or noisy mobile signal, roaming, mobile data with no internet), with graphs of
  Wi-Fi and mobile signal that update every 5 seconds if you tick **Update every 5 s**; **Wi-Fi** (the
  network you are on: signal in dBm, band and channel, link speeds, standard, security, router, DNS, and
  nearby networks); **Mobile network** (registration for calls and data, operator, 4G or 5G, signal as
  RSRP, RSRQ and SINR, the cell and band, the modem version, and whether Android confirmed internet);
  and **Bluetooth, USB, power** (paired devices, charger type and limit, USB mode, the networks Android is
  using). **Network test** sends a few small pings from the phone (router, 8.8.8.8, a name lookup): the
  one thing here that sends traffic, and only when pressed. Android's dump formats differ between
  phones, so a value the phone does not report is simply left out.
- **Phone > Log viewer...** shows the phone's recent system log (logcat), colouring errors and
  warnings, with a level filter, a search box, Refresh, Copy and Save. Read-only. Logs can contain
  personal details, so check them before sharing.
- **Show more** (under the device details) reads everything the phone gives over USB, in sections:
  identity (serial number, IMEI, Android ID, Wi-Fi and Bluetooth address), software, hardware and
  board (chip maker and model, board ID, SKU), boot (last boot reason, boot mode, kernel line),
  **modem and telecom** (baseband, radio firmware, RIL, network operator and codes, roaming, preferred
  network mode, VoLTE and Wi-Fi calling), the **SIM card** (state, operator, codes), connectivity and
  state (airplane mode, Wi-Fi, Bluetooth, mobile data link and signal bars, location, developer
  options and USB debugging, uptime), **servicing and debugging** (debuggable and secure build, build
  tags, OEM-unlock flags, wireless debugging port, encryption type, vendor patch level, full kernel
  string), partition sizes (`/data`, `/system`, `/vendor`, ...), battery (with charge cycles, health
  and heat throttling where the phone reports them), plus a
  Xiaomi / HyperOS section and hardware features (NFC, IR blaster, refresh rates, ...), the GPU, and the
  sensors on the phone (accelerometer, light, proximity, ... with chip and maker) when the phone has
  them: only what the phone really reports is shown. In fastboot mode it lists every bootloader variable (`getvar all`).
  The IMEI comes from the phone's own properties or its telephony service; if Android blocks it over
  USB the row says so (dial *#06# on the phone). The serial number is shown in full. These values
  stay on screen: nothing is sent anywhere, and **Copy details** copies them only if you press it.
- **Live status...** (Phone menu) is a dashboard in the style of Grafana and Apache ECharts: one
  reading a second, in four tabs (Ctrl+1 to Ctrl+4):
  - **Overview**: ring gauges (processor, GPU where the phone reports it, memory, battery, storage)
    coloured by threshold, with the state in words (Normal, High, Critical), then a card for each graph
    with a legend table of last, min, average and max. Dashed lines mark thresholds (for example 80%
    load, 45 and 60 °C). Point at a graph for a tooltip with the exact value. The time range (1 min up
    to 1 hr) is at the top right, on this tab only.
  - **Processor**: every core with its own trend, usage and speed, labelled Performance or Efficiency
    where the phone has both.
  - **Sensors**: every thermal sensor the phone lets us read, hottest first, with Normal, Warm or Hot.
  - **Processes**: a task-manager style list (name, PID, CPU %, memory, state): sort by any column,
    search, and filter to apps, apps and system, or everything. Read-only: nothing can be stopped here.
  Each list has a page to itself, so the window never holds two scrollbars. A **Live** marker shows
  whether readings are arriving; **Pause** freezes them and **Copy snapshot** copies the latest numbers.
- **Copy details** and **Export...** (top of the Phone section) copy or save the device details, plus the
  extra details once they are read, as text, CSV (for a spreadsheet) or Markdown (for a bug report). The files
  contain the serial number and, in the extra details, the IMEI: you choose where they go.
- **Restart or power off...** (Phone menu, and **Restart phone...** in fastboot mode) is one place to pick
  Android, recovery mode, fastboot mode or power off. In fastboot mode it offers **Cancel and start Android**
  and recovery mode, so you can leave without unlocking. Nothing is erased by any of them.
- **Security check...** takes a colour as soon as a phone is connected, from a quick check that stays on the
  phone and the computer (patch age, verified boot, encryption, Play Protect). The full check, which asks OSV
  and looks at apps, replaces it and goes deeper. Green means nothing found, amber review, red needs attention.
- **Back up files...** can be run again on the same folder: files already there (same size and time) are
  skipped, every copy is written under a temporary name and checked against the size the phone reported, a
  failed file is retried, and anything that still fails is listed in `backup-problems.txt` in the backup folder.
- **Sign out** (Mi Account section, or File menu) deletes the saved session on this computer.
- **Help > Check for updates...** shows what is new in the latest release. For the single-file program from
  the Releases page, **Install and restart** downloads the update, checks it against the release's
  `SHA256SUMS.txt`, swaps it in and starts it again; a pip or source install is pointed to the release page
  instead. Once a day the app also looks quietly and says in the status line when there is a newer version;
  turn that off with **Help > Check for updates automatically**. Versions read `v1.0.0 (build: DDMMYYYY-commit)`:
  the release number, then the date and short id of the commit it was built from (shown in the title bar,
  About and `mitoolkit --version`).
- **Debug logging** (Help menu, `--debug`, or `MITOOLKIT_DEBUG=1`) adds step-by-step lines to `mitoolkit.log`:
  each adb and fastboot request with its timing, scans, connections. Tokens stay hidden. Off by default.
- **Wireless adb...** (Phone menu) uses the phone over Wi-Fi instead of a cable. With the phone plugged
  in once, **Turn on Wi-Fi debugging** switches its adb to the network and connects; after that you can
  unplug it. A phone already set up for wireless debugging can be connected by its address (for example
  `192.168.1.5`). It needs Google's `adb` (platform-tools) on this computer, because mitoolkit's own adb
  speaks USB only, and the phone returns to USB-only when it restarts. **Fastboot and unlocking work over
  a USB cable only**: the bootloader has no Wi-Fi, so mitoolkit asks you to plug the phone in before it
  reboots into fastboot. When a phone is both plugged in and on Wi-Fi, it is listed once, by USB.
  **Pairing (Android 11 or newer, no cable at all):** on the phone open Settings > Developer options >
  Wireless debugging > *Pair device with pairing code* and leave that screen open. Press **Find phones on
  Wi-Fi** (or type the address with its port and the 6-digit code it shows) and **Pair**. Pairing makes the
  phone trust this computer's adb key, so it does not ask to allow debugging again; the app then connects
  using the address the phone announces, or you enter the *IP address & port* from the Wireless debugging
  screen and press **Connect**. The code works once and is never logged or kept. If the phone shows an
  "Allow debugging?" prompt instead (a cable or address connection), tap Allow and tick *Always allow from
  this computer*; until you do, the phone is listed as waiting for authorisation. Finding phones needs
  mDNS on the network (some routers and guest networks block it: then type the address).
- The window looks for the phone every second, and Live status and Connections show at once when it is
  unplugged and carry on when it is back. Automatic updates change only the readings, not the text bar.
- When Xiaomi says to wait, the message includes the date and time to try again.

## Saved session and log

The session is stored encrypted where the system allows it (credential store or Windows
DPAPI), expires after 24 hours, and is removed by logging out. Details, including how to
change the expiry, are in the [safety model](safety.md#saved-session).

Everything the program does is also recorded in `mitoolkit.log`, next to the executable.
It contains no tokens. In the GUI, **File > Show log file** opens its folder.
