# Unlock guide

How to prepare a Xiaomi, Redmi or POCO device and unlock its bootloader with
`mitoolkit`.

> [!WARNING]
> Unlocking erases all user data on most devices, voids the warranty and removes
> a layer of the device's security. Unlocked devices are easier targets for
> malware. Banking and payment apps may refuse to run on an unlocked device.
> Continue only if you accept this.

> [!TIP]
> The GUI contains this guide: **Guide** (top right) (or press **F1**). It works
> offline and follows the same steps.

## 1. Before you start

- **Back up everything you care about.** Photos and files, app data you cannot
  re-download, and chat history. For chats, use the app's own backup: a local
  backup file on the device is erased by the unlock too, so copy it to a computer.
- **Copy your files with mitoolkit.** While the phone is on with USB debugging allowed, the
  GUI's **Back up files...** button (step 2) (or `mitoolkit backup --dest <folder>`) copies photos,
  videos, documents, downloads, chat-app media or all shared storage to your computer. It
  only reads from the phone, and it also saves a list of installed apps. It does **not**
  cover app data, contacts or SMS.
- **Sync the rest.** Use Mi Cloud (*Settings > Mi Account > Xiaomi Cloud*) for contacts,
  notes, SMS and call history, and Google backup and Google Photos where you use them.
- **Check the backup.** Open a few files on the computer before you continue.
- **Export two-factor codes** from authenticator apps that do not sync, or you may
  be locked out of accounts after the wipe.
- Use a good USB data cable and charge the phone above 50%.
- Install [`mitoolkit`](installation.md).

## 2. Add your account in Mi Unlock status

1. Open *Settings → About phone* and tap **Build number** (or *MIUI/OS version*)
   seven times to enable Developer options.
2. Sign in to the Mi Account you want to use under *Settings → Mi Account*.
3. Open *Settings → Additional settings → Developer options → Mi Unlock status*.
4. Agree to the terms and tap **Add account and device**. Use mobile data if Wi-Fi
   fails.

Being signed in to a Mi Account is not enough. If you skip this step Xiaomi
returns error `20031` ("Please add your account in Settings > Developer options >
Mi Unlock status").

> [!IMPORTANT]
> Adding the account **starts Xiaomi's waiting period**. Do not add it again
> while waiting: Xiaomi warns that this restarts the wait from the beginning.

## 3. Wait out the waiting period

Xiaomi makes you wait before it will issue an unlock token. The length depends on
the device and account; 168 hours (7 days) is common. While it runs, `mitoolkit
check` reports error `20036` ("Please unlock *N* hours later"). This is normal.
`mitoolkit` does not shorten the wait.

Some devices running **HyperOS** also need permission through the Xiaomi
Community app. That app is not offered in every region.

If the wait seems to reset or never decreases, see the notes under `20036` in the
[error codes](error-codes.md).

## 4. Put the device in fastboot mode

The GUI shows a dot next to the phone: green when it is in fastboot mode, orange when it is
running Android and seen by adb (click **Reboot to fastboot**, nothing is erased), grey when
nothing is found.

Either:

- Power the phone off, then hold **Volume Down + Power** until the fastboot screen
  appears, or
- With USB debugging enabled, run `adb reboot bootloader`.

Connect it by USB. It must be in **fastboot** mode, not *fastbootd*. If it is not
detected, see the [FAQ](faq.md#why-is-my-device-not-detected).

## 5. Check eligibility (read-only)

In the GUI, click **Check eligibility** (step 2). On the command line:

```sh
mitoolkit check
```

A response with `"eligible": true` means Xiaomi will issue a token. It also tells
you whether data will be erased (`will_wipe_data`). A non-eligible response
includes the server's reason; see [error codes](error-codes.md). This step does
not change the device.

## 6. Unlock

Make sure your backup is complete and copied off the device.

In the GUI, step 3 stays disabled until the check passes. Tick the backup box, type the
phone's name exactly and click **Unlock bootloader**. Or run either of:

```sh
mitoolkit                           # interactive: press Enter when prompted
mitoolkit unlock --confirm-wipe     # non-interactive
```

Log in with the **same** Mi Account you added in step 2. When the unlock
command finishes the device resets. The first boot can take several minutes.

## 7. Afterwards

- Set the phone up again and restore your data.
- Delete the saved session: remove `~/.mitoolkitsession/`, then check the signed-in
  devices on your Mi Account.
- Restoring a chat app's local backup usually requires placing the backup file back
  in the app's folder **before** you open the app for the first time.

## Alternatives

If you only need to remove bloatware or free space, you usually do not need to
unlock. `adb shell pm uninstall -k --user 0 <package>` disables most preinstalled
apps for the current user without touching the bootloader.
