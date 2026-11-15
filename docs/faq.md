# FAQ

## Process

### How do I unlock my bootloader?

Follow the [unlock guide](unlock-guide.md).

### Does this tool skip the waiting period?

No. `miunlock` follows the same official process as Xiaomi's own tool, so it is
only an alternative client. Xiaomi's server decides when you are eligible.

### Do I need to add my account in Developer options?

Yes. Open *Settings → Additional settings → Developer options → Mi Unlock status*
and tap **Add account and device**. Signing in to a Mi Account is not enough; the
server answers error `20031` until this is done. Adding the account starts the
waiting period, and adding it again restarts the wait.

### Do I need permission from the Xiaomi Community?

Devices running **HyperOS** may. The Community app is not available in every
region, which can block this step.

### Will my data be erased?

Almost always. `miunlock` tells you before it proceeds, using Xiaomi's own answer
for your device.

> [!WARNING]
> As a general rule, unlocking erases all user data. Back up first.

**Legacy devices.** These codenames are unlocked without clearing user data:

`gemini`, `ido`, `kate`, `kenzo`, `land`, `markw`, `meri`, `mido`, `nikel`,
`omega`, `prada`, `rolex`, `santoni`, `venus`, `wt88047`

Codenames can be looked up for [Xiaomi](https://en.wikipedia.org/wiki/List_of_Xiaomi_products#Current),
[Redmi](https://en.wikipedia.org/wiki/List_of_Redmi_products#Phones) and
[POCO](https://en.wikipedia.org/wiki/Poco_(smartphone)#Smartphones) devices.

### I get an error code

See the [error codes](error-codes.md).

### What is `encryptData`, and how does the tool work?

See [How it works](how-it-works.md).

## Safety

### Is it safe to log in?

Login happens on Xiaomi's own page in your browser, or by QR code. Your password is
never typed into this program. Check the address bar says `account.xiaomi.com`.
See the [safety model](safety.md).

### How do I log out?

Delete `~/.miunlocksession/` and review the signed-in devices on your Mi Account.
Deleting the file does not end the session on Xiaomi's side.

### Can I script it or use it from an automation tool?

Yes: use the [JSON subcommands](usage.md#command-line) or the
[Python API](api.md). The unlock itself always needs an explicit
`--confirm-wipe` / `confirm_wipe=True` set by a person.

### Why isn't it on PyPI?

The package on PyPI named `miunlock` is the original project and still contains the
password-login code this fork removed. Install this fork from the repository so the
code you run is the code you can read. See [installation](installation.md).

## Installation and devices

### Which Python version do I need?

Python 3.9 or newer.

### Why is my device not detected?

- On Android (Termux), make sure the phone supports OTG and that it is enabled.
- On Windows, the device should appear in Device Manager without a warning icon.
  Install the drivers if it does not:
  - Easiest: in the GUI choose *File > Install Google USB driver*, or run
    `miunlock install-driver`. It downloads Google's official driver and installs it after
    a Windows administrator prompt. Google's driver does not list Xiaomi's USB IDs, so if
    the warning stays, right-click the phone in Device Manager > *Update driver > Browse my
    computer > Let me pick > Android Device > Android Bootloader Interface*.
  - [Xiaomi USB driver](http://bigota.d.miui.com/tools/xiaomi_usb_driver.rar)
    ([guide](https://web.vip.miui.com/page/info/mio/mio/detail?postId=18464849&app_version=dev.20051))
  - [Google ADB driver](https://dl.google.com/android/repository/latest_usb_driver_windows.zip)
    ([guide](https://developer.android.com/studio/run/oem-usb#InstallingDriver))
- Make sure the device is in **fastboot** mode, not *fastbootd*.
- On Linux, add a udev rule for Android phones (for example the
  `android-sdk-platform-tools-common` package) and reconnect.
- Close other programs that use the phone: Google's adb (`adb kill-server`), Android
  Studio, Mi Unlock, Mi Flash. Only one program can use it at a time.
- Try a different USB data cable. A bad or charge-only cable is the most common
  cause; prefer the original.
- Unplug and replug the cable and check it is seated properly.
- Remove any other installed ADB/Fastboot and let `miunlock` use its own.

### `status` or `check` seems to hang

They read the device over `fastboot` and wait for one to appear. Put the phone in
fastboot mode and connect it, or press Ctrl+C.

### The GUI does not start

Tkinter is missing. On Debian or Ubuntu run `sudo apt install python3-tk`.

---

Still stuck? Look through the
[closed issues](https://github.com/jowinjohnchemban/miunlock/issues?q=is%3Aissue+is%3Aclosed)
or [open a new one](https://github.com/jowinjohnchemban/miunlock/issues/new).
