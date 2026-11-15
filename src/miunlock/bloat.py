"""
Known preinstalled apps on Xiaomi, Redmi and POCO phones, for the app manager.

Each entry is package -> (name, rating, note). Ratings:

- recommended: ads, tracking, promotional or duplicate apps; safe to remove for most people
- optional:    ordinary apps you may or may not use (removing them breaks nothing else)
- advanced:    can affect other features; remove only if you know you do not need them
- avoid:       needed by the system or by the unlock itself; the manager warns before removing

Removing uses ``pm uninstall --user 0``: the app is hidden for your user and can be
restored from the manager. A factory reset (and the unlock, which resets the phone)
brings every preinstalled app back. Names differ between MIUI, HyperOS and regions; a
package that is not on the phone is simply not shown.
"""
from __future__ import annotations

from typing import Dict, Tuple

RATINGS = ("recommended", "optional", "advanced", "avoid", "unknown")

# What each rating means, in the words the app manager shows.
LABELS = {
    "recommended": ("Safe to remove", "Ads, tracking or promotion. Removing it does not break anything else."),
    "optional": ("Optional", "An ordinary app. Remove it if you do not use it."),
    "advanced": ("Caution", "Other features may depend on it. Remove it only if you know you do not need them."),
    "avoid": ("Keep", "Needed by the system or for unlocking. Do not remove it."),
    "unknown": ("Unknown", "Not in miunlock's list. Look it up before removing it."),
}

KNOWN: Dict[str, Tuple[str, str, str]] = {
    # --- ads, analytics, promotions ------------------------------------------------
    "com.miui.msa.global": ("MIUI System Ads (MSA)", "recommended", "Shows ads in system apps."),
    "com.miui.analytics": ("Analytics", "recommended", "Usage statistics sent to Xiaomi."),
    "com.miui.daemon": ("MIUI Daemon", "recommended", "Collects usage and performance data."),
    "com.miui.hybrid": ("Quick Apps", "recommended", "Instant-app platform, used for promotions."),
    "com.miui.hybrid.accessory": ("Quick Apps accessory", "recommended", "Part of Quick Apps."),
    "com.miui.android.fashiongallery": ("Wallpaper Carousel", "recommended", "Lock-screen wallpapers with ads."),
    "com.mi.android.globalminusscreen": ("App Vault", "recommended", "Left-of-home-screen cards."),
    "com.xiaomi.mipicks": ("GetApps", "recommended", "Xiaomi's app store; some system app updates come from it."),
    "com.xiaomi.discover": ("System apps updater", "recommended", "Promotes and updates Xiaomi apps."),
    "com.xiaomi.glgm": ("Games", "recommended", "Xiaomi game centre."),
    "com.miui.bugreport": ("Feedback", "recommended", "Sends bug reports to Xiaomi."),
    "com.miui.miservice": ("Services & feedback", "recommended", "Support app."),
    "com.miui.yellowpage": ("Yellow Pages", "recommended", "Business caller ID; sends numbers to Xiaomi."),
    "com.facebook.appmanager": ("Facebook App Manager", "recommended", "Updates preinstalled Facebook apps."),
    "com.facebook.services": ("Facebook Services", "recommended", "Background service for Facebook."),
    "com.facebook.system": ("Facebook App Installer", "recommended", "Installs Facebook apps."),
    "com.facebook.katana": ("Facebook", "optional", "Preinstalled Facebook app."),
    "com.netflix.partner.activation": ("Netflix activation", "recommended", "Partner activation service."),
    "com.netflix.mediaclient": ("Netflix", "optional", "Preinstalled Netflix app."),
    "com.amazon.appmanager": ("Amazon App Manager", "recommended", "Installs Amazon apps."),
    "com.amazon.mShop.android.shopping": ("Amazon Shopping", "optional", "Preinstalled shopping app."),
    "com.linkedin.android": ("LinkedIn", "optional", "Preinstalled partner app."),
    "com.booking": ("Booking.com", "optional", "Preinstalled partner app."),
    "com.spotify.music": ("Spotify", "optional", "Preinstalled partner app."),
    "com.zhiliaoapp.musically": ("TikTok", "optional", "Preinstalled partner app."),
    "com.ebay.mobile": ("eBay", "optional", "Preinstalled partner app."),
    "com.ebay.carrier": ("eBay carrier", "recommended", "Partner installer."),
    "cn.wps.moffice_eng": ("WPS Office", "optional", "Preinstalled office app."),
    "com.opera.browser": ("Opera", "optional", "Preinstalled browser."),
    "com.opera.preinstall": ("Opera preinstall", "recommended", "Partner installer."),
    "com.block.juggle": ("Block Juggle", "optional", "Preinstalled game."),
    "com.logame.eliminateintruder3d": ("Game", "optional", "Preinstalled game."),
    # --- Xiaomi apps you may not use --------------------------------------------------
    "com.mi.globalbrowser": ("Mi Browser", "optional", "Keep if it is your only browser."),
    "com.android.browser": ("Mi Browser (China ROM)", "optional", "Keep if it is your only browser."),
    "com.miui.videoplayer": ("Mi Video", "optional", "Video player."),
    "com.miui.player": ("Mi Music", "optional", "Music player."),
    "com.miui.fm": ("FM Radio", "optional", "Radio."),
    "com.miui.compass": ("Compass", "optional", ""),
    "com.miui.weather2": ("Weather", "optional", "Also feeds the weather widget."),
    "com.miui.calculator": ("Calculator", "optional", ""),
    "com.miui.notes": ("Notes", "optional", "Back up your notes first."),
    "com.miui.screenrecorder": ("Screen recorder", "optional", ""),
    "com.mi.health": ("Mi Health", "optional", ""),
    "com.xiaomi.midrop": ("ShareMe", "optional", "File sharing."),
    "com.xiaomi.scanner": ("Scanner", "optional", "QR and document scanner."),
    "com.miui.virtualsim": ("Mi Mobile / virtual SIM", "optional", ""),
    "com.xiaomi.payment": ("Mi Pay", "optional", ""),
    "com.mipay.wallet.in": ("Mi Pay (India)", "optional", ""),
    "com.mipay.wallet.id": ("Mi Pay (Indonesia)", "optional", ""),
    "com.xiaomi.mi_connect_service": ("Mi Connect", "advanced", "Used by Mi Share and device continuity."),
    "com.miui.cleaner": ("Cleaner", "advanced", "Part of Security; removal may affect storage cleanup."),
    "com.xiaomi.joyose": ("Joyose", "advanced", "Performance profiles; removal can change battery or game performance."),
    "com.miui.cloudbackup": ("Cloud backup", "advanced", "Needed for Xiaomi Cloud backup."),
    "com.miui.micloudsync": ("Xiaomi Cloud sync", "advanced", "Needed for Xiaomi Cloud sync."),
    # --- Google apps ------------------------------------------------------------------
    "com.google.android.youtube": ("YouTube", "optional", ""),
    "com.google.android.apps.youtube.music": ("YouTube Music", "optional", ""),
    "com.google.android.videos": ("Google TV", "optional", ""),
    "com.google.android.apps.tachyon": ("Google Meet (Duo)", "optional", ""),
    "com.google.android.apps.docs": ("Google Drive", "optional", ""),
    "com.google.android.apps.maps": ("Google Maps", "optional", "Other apps may use it for maps."),
    "com.google.android.apps.photos": ("Google Photos", "optional", "Check your photos are backed up."),
    "com.google.android.apps.subscriptions.red": ("Google One", "optional", ""),
    "com.google.android.apps.wellbeing": ("Digital Wellbeing", "optional", ""),
    "com.google.android.feedback": ("Google Feedback", "recommended", ""),
    "com.google.android.gm": ("Gmail", "optional", ""),
    "com.google.android.googlequicksearchbox": ("Google app", "advanced", "Assistant and search; widgets depend on it."),
    "com.google.android.apps.googleassistant": ("Assistant", "optional", ""),
    "com.google.ar.lens": ("Google Lens", "optional", ""),
    "com.google.android.apps.nbu.files": ("Files by Google", "optional", ""),
    # --- keep ------------------------------------------------------------------------
    "com.xiaomi.account": ("Mi Account", "avoid", "Needed to sign in and to unlock the bootloader."),
    "com.miui.cloudservice": ("Xiaomi Cloud / Find device", "avoid", "Mi Unlock status and Find device depend on it."),
    "com.xiaomi.finddevice": ("Find device", "avoid", "Linked to the unlock; removing it can cause errors."),
    "com.miui.securitycenter": ("Security", "avoid", "Permissions and Mi Unlock status live here."),
    "com.miui.securitycore": ("Security core", "avoid", "Second space and app lock."),
    "com.miui.home": ("System launcher", "avoid", "Removing it can leave you without a home screen."),
    "com.android.settings": ("Settings", "avoid", ""),
    "com.android.systemui": ("System UI", "avoid", ""),
    "com.android.phone": ("Phone services", "avoid", ""),
    "com.android.vending": ("Google Play Store", "avoid", "Needed to install and update apps."),
    "com.google.android.gms": ("Google Play services", "avoid", "Most apps depend on it."),
    "com.google.android.gsf": ("Google Services Framework", "avoid", ""),
    "com.miui.gallery": ("Gallery", "advanced", "Some MIUI features open photos with it."),
    "com.android.camera": ("Camera", "avoid", ""),
    "com.android.contacts": ("Contacts and dialer", "avoid", ""),
    "com.android.mms": ("Messages", "advanced", "Keep unless you use another SMS app."),
    "com.android.providers.downloads": ("Download manager", "avoid", ""),
    "com.android.updater": ("System updates", "advanced", "Removing it stops OTA updates."),
}


def describe(package: str, system: bool) -> Tuple[str, str, str]:
    """(name, rating, note). Unknown preinstalled apps are 'unknown'; apps you installed
    yourself are 'optional' (removing them uninstalls them)."""
    if package in KNOWN:
        return KNOWN[package]
    if not system:
        return ("", "optional", "Installed by you. Removing it uninstalls it; reinstall from the store.")
    return ("", "unknown", "Not in miunlock's list. Look it up before removing.")
