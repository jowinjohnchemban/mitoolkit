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
    ("1. Add your account to the phone", [
        ("p", "Do this on the phone, before using miunlock."),
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
              "later\". That is normal, and miunlock cannot shorten it."),
        ("p", "Some HyperOS devices also need permission through the Xiaomi Community app, "
              "which is not offered in every region."),
    ]),
    ("3. Sign in (step 1 in the app)", [
        ("p", "Click Sign in with browser. Xiaomi's own login page opens in your browser. "
              "Sign in there with the same Mi Account you added on the phone."),
        ("b", "Your password is never typed into miunlock."),
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
              "Help > Error codes lists them all."),
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
    ("Afterwards", [
        ("b", "Set the phone up again and restore your data."),
        ("b", "Use File > Sign out and delete saved session, then check the signed-in devices "
              "on your Mi Account, because signing out here does not end the session on Xiaomi's side."),
        ("b", "Restoring a chat app's local backup usually means putting the file back in the "
              "app's folder before first opening the app."),
    ]),
    ("Troubleshooting", [
        ("b", "Phone not detected: use a data cable (not charge-only) and another USB port, and "
              "check the phone shows the fastboot screen. On Windows, install Xiaomi or Google "
              "USB drivers if it still does not appear."),
        ("b", "Details button (bottom right): shows what the program is doing. Copy it when "
              "asking for help. It contains no tokens."),
        ("b", "File > Show log file opens the saved log."),
        ("b", "Error 20031: account not added in Mi Unlock status (section 1)."),
        ("b", "Error 20036: still in the waiting period (section 2)."),
        ("p", "More: Help > FAQ and Help > Error codes."),
    ]),
]
