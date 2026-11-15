"""
The step-by-step guide shown inside the GUI (Help > Step-by-step guide, or F1), so it
works offline and matches the screen. docs/unlock-guide.md is the longer written version;
keep the two in step when either changes.

Content is plain data: a list of (title, blocks). A block is ("p", text) for a paragraph,
("b", text) for a bullet or ("w", text) for a warning.
"""
from __future__ import annotations

TOPICS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Before you start", [
        ("w", "Unlocking erases the phone's data, voids the warranty and lowers its security. "
              "It cannot be undone once started."),
        ("b", "Back up photos, files and chat history, and copy the backup to a computer. "
              "A backup left on the phone is erased too."),
        ("b", "Export two-factor codes from authenticator apps that do not sync, or you may be "
              "locked out of accounts afterwards."),
        ("b", "Use a good USB data cable and charge the phone above 50%."),
    ]),
    ("Back up your data", [
        ("p", "The unlock erases the phone, so copy what matters first. Use several of these:"),
        ("b", "Back up files... (step 2, while the phone is on and USB debugging is allowed): copies "
              "photos, videos, documents, downloads and chat-app media to this computer. It only "
              "reads from the phone. It also saves a list of your installed apps."),
        ("b", "Mi Cloud: Settings > Mi Account > Xiaomi Cloud. Syncs contacts, notes, SMS, gallery "
              "and call history."),
        ("b", "Google: Settings > Google > Backup, and Google Photos for pictures."),
        ("b", "Chat apps: use each app's own backup (WhatsApp: Settings > Chats > Chat backup), "
              "and copy the backup file off the phone."),
        ("b", "Authenticator apps and passwords: export or note them down so you are not locked out."),
        ("b", "Check the backup opens on the computer before you go on."),
        ("w", "App data, SMS, contacts and settings are not copied by the file backup."),
    ]),
    ("1. Add your account to the phone", [
        ("p", "Do this on the phone, before using MiToolkit."),
        ("b", "Settings > About phone: tap Build number (or MIUI/OS version) seven times to "
              "turn on Developer options."),
        ("b", "Sign in to the Mi Account you want to use under Settings > Mi Account."),
        ("b", "Open Settings > Additional settings > Developer options > Mi Unlock status, "
              "agree to the terms and tap Add account and device. Use mobile data if Wi-Fi fails."),
        ("w", "Adding the account starts Xiaomi's waiting period. Do not add it again while "
              "waiting: that restarts the wait."),
        ("p", "Being signed in is not enough. Skipping this gives error 20031."),
    ]),
    ("2. Wait out the waiting period", [
        ("p", "Xiaomi makes you wait before it issues an unlock token. 168 hours (7 days) is "
              "common. While it runs, the check reports error 20036 \"Please unlock N hours "
              "later\". That is normal, and MiToolkit cannot shorten it."),
        ("p", "Some HyperOS devices also need permission through the Xiaomi Community app, "
              "which is not offered in every region."),
    ]),
    ("3. Sign in (step 1 in the app)", [
        ("p", "Click Sign in with browser. Xiaomi's own login page opens in your browser. "
              "Sign in there with the same Mi Account you added on the phone."),
        ("b", "Your password is never typed into MiToolkit."),
        ("b", "The session is saved encrypted and expires after 24 hours. "
              "File > Sign out and delete saved session removes it."),
    ]),
    ("4. Connect the phone (step 2)", [
        ("p", "The app watches for the phone by itself and shows a coloured dot:"),
        ("b", "Green: phone found in fastboot mode. You can go on."),
        ("b", "Orange: phone is on and seen by adb. Click Reboot to fastboot. Nothing is erased."),
        ("b", "Grey: nothing found yet."),
        ("p", "To enter fastboot by hand: power the phone off, then hold Volume Down + Power "
              "until the fastboot screen appears, and connect it by USB."),
        ("p", "If the phone is connected but USB debugging is not allowed yet, accept the "
              "prompt on the phone's screen."),
        ("p", "The phone must be in fastboot mode, not fastbootd."),
    ]),
    ("5. Check eligibility (step 2)", [
        ("p", "Click Check eligibility. This asks Xiaomi and changes nothing on the phone."),
        ("b", "Ready to unlock: Xiaomi will issue a token. It also says whether data is erased."),
        ("b", "Anything else: the app explains the error in plain words and gives the raw code. "
              "Help > Online documentation > Error codes lists them all."),
    ]),
    ("6. Unlock (step 3)", [
        ("p", "Only available once the check passes. Three deliberate acts are needed:"),
        ("b", "Tick the box saying your data is backed up."),
        ("b", "Type the phone's name exactly as shown."),
        ("b", "Click Unlock bootloader and keep the phone connected until it finishes."),
        ("w", "Do not unplug the phone while unlocking."),
        ("p", "When it finishes the phone resets. The first start can take several minutes. "
              "If it stays on the fastboot screen, click Reboot phone."),
    ]),
    ("Manage apps (debloat)", [
        ("p", "Manage apps... (step 2, while the phone is on with USB debugging allowed) lists every "
              "app on the phone. Tick the ones to remove and click Remove ticked."),
        ("b", "Known bloat shows Xiaomi ads, tracking and promotional apps from mitoolkit's list. "
              "Tick recommended ticks the ones rated safe to remove."),
        ("b", "Ratings: Recommended (safe for most people), Optional (ordinary apps), Advanced (can "
              "affect other features), Avoid (needed by the system or the unlock), Unknown (look it up first)."),
        ("b", "Preinstalled apps are removed for your user only. Show > Removed lists them, and "
              "Restore ticked brings them back. Apps you installed yourself are uninstalled."),
        ("w", "Unlocking the bootloader resets the phone, which brings every removed app back. "
              "Debloat after unlocking, or if you are not unlocking."),
    ]),
    ("Live status and details", [
        ("p", "Show more (the bar under the device details) lists everything the phone gives over USB: serial "
              "number, IMEI, software, hardware, modem, SIM, boot, servicing and debugging, partitions, sensors "
              "and battery. It stays on your screen. Copy details (top of step 2) copies what is shown."),
        ("p", "Live status... (step 2) draws live graphs of processor, memory, battery, temperature and network, "
              "shows each processor core, the GPU and every temperature sensor, and lists processes like a "
              "task manager. It only reads; close the window to stop. Use Ctrl+1 to Ctrl+4 for its tabs."),
        ("p", "Log viewer... (Phone menu) shows the phone's recent system log with a level filter and search. "
              "Logs can contain personal details: check them before sharing."),
    ]),
    ("Debug Wi-Fi and mobile data", [
        ("p", "Connections... (step 2) reads Wi-Fi, the modem and mobile network, the SIM, Bluetooth, USB and power, "
              "and tells you in plain words what looks wrong and what to try."),
        ("b", "Summary: the findings, worst first, and two graphs of Wi-Fi and mobile signal. Tick Update every "
              "5 s to watch them live while you move around."),
        ("b", "Wi-Fi: the network you are on (signal in dBm, band and channel, speeds, router, DNS) and nearby "
              "networks, to spot a crowded channel."),
        ("b", "Mobile network: registration, operator, network type (4G or 5G), signal (RSRP, RSRQ, SINR), "
              "the cell you are on, and whether Android confirmed internet through it."),
        ("p", "Network test sends a few small pings from the phone (to the router, to 8.8.8.8, and a name lookup) "
              "to tell a dead router from a DNS problem. It is the only button here that sends traffic."),
        ("p", "Android's dump formats differ between phones. If a value is missing, the phone did not report it."),
    ]),
    ("Security check", [
        ("p", "Security check... (step 2, while the phone is on) looks at the phone and changes nothing:"),
        ("b", "Phone software: compares your security patch with Android's security bulletins (from OSV, "
              "AOSP data) and says how many fixes are missing and whether your Android version still gets fixes."),
        ("b", "Google Play: whether Play Protect is on, how old the Google Play system update is, and which "
              "apps were not installed from a store or may install other apps."),
        ("b", "Apps: apps with accessibility, notification or device-admin access, and known stalkerware."),
        ("w", "It is not an antivirus. Keep Google Play Protect on."),
    ]),
    ("Afterwards", [
        ("b", "Set the phone up again and restore your data."),
        ("b", "Use File > Sign out and delete saved session, then check the signed-in devices "
              "on your Mi Account, because signing out here does not end the session on Xiaomi's side."),
        ("b", "Restoring a chat app's local backup usually means putting the file back in the "
              "app's folder before first opening the app."),
    ]),
    ("Troubleshooting", [
        ("b", "Phone not detected: use a data cable (not charge-only) and another USB port, and "
              "check the phone shows the fastboot screen."),
        ("b", "Windows: if Device Manager shows the phone with a yellow mark, install Google's USB "
              "driver. Help > USB driver help lists the steps and opens Google's download page; you "
              "install it with Windows' Device Manager (Have Disk > android_winusb.inf)."),
        ("b", "Linux: if the phone is found but cannot be opened, add a udev rule for Android phones "
              "(for example the android-sdk-platform-tools-common package) and reconnect."),
        ("b", "\"Another program is using the phone\": close Google's adb (adb kill-server), Android "
              "Studio, Mi Unlock or Mi Flash. Only one program can use the phone at a time."),
        ("b", "Details button (bottom right): shows what the program is doing. Copy it when "
              "asking for help. It contains no tokens."),
        ("b", "File > Show log file opens the saved log. File > Activity log shows what the program is doing."),
        ("b", "Error 20031: account not added in Mi Unlock status (section 1)."),
        ("b", "Error 20036: still in the waiting period (section 2)."),
        ("p", "More: Help > Online documentation (FAQ, Error codes, Safety model)."),
    ]),
]
