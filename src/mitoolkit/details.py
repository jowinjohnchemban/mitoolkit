"""Everything the phone will tell us over USB, for the "Show more" button.

Read-only. It runs a few harmless shell reads (getprop, settings get, dumpsys battery, a
cat of the Wi-Fi address) in one round trip, or asks the bootloader for `getvar all`. Nothing
is written to the phone and nothing leaves this computer: the values are shown on screen
and only copied if you press Copy.

IMEI: Android restricts it. Xiaomi phones usually expose it as a system property
(ro.ril.miui.imei0); otherwise we try the telephony service and keep only a result that
passes the IMEI check digit. If neither works the phone is not giving it out over USB, and
dialling *#06# on the phone always shows it.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from mitoolkit import fastboot
from mitoolkit.adb_core import is_wireless

Section = Tuple[str, List[Tuple[str, str]]]

_MARK = "@@mitoolkit@@"
_JUNK = {"", "null", "unknown", "0", "none"}

# (label, [property names to try]) per section. First property with a value wins.
_PROP_SECTIONS: List[Tuple[str, List[Tuple[str, List[str]]]]] = [
    ("Identity", [
        ("Serial number", ["ro.serialno", "ro.boot.serialno"]),
        ("Marketing name", ["ro.product.marketname", "ro.product.vendor.marketname", "ro.product.odm.marketname"]),
        ("Product name", ["ro.product.name"]),
        ("Hardware revision", ["ro.boot.hwversion"]),
        ("Hardware region code", ["ro.boot.hwc"]),
    ]),
    ("Software", [
        ("Fingerprint", ["ro.build.fingerprint"]),
        ("Build type", ["ro.build.type"]),
        ("Build date", ["ro.build.date"]),
        ("Build number (incremental)", ["ro.build.version.incremental"]),
        ("MIUI version code", ["ro.miui.ui.version.code"]),
        ("Baseband", ["gsm.version.baseband"]),
        ("First Android version shipped (API)", ["ro.product.first_api_level"]),
        ("Treble", ["ro.treble.enabled"]),
        ("A/B updates", ["ro.build.ab_update"]),
        ("Dynamic partitions", ["ro.boot.dynamic_partitions"]),
    ]),
    ("Hardware", [
        ("Board", ["ro.product.board", "ro.board.platform"]),
        ("Platform", ["ro.board.platform"]),
        ("Hardware", ["ro.hardware"]),
        ("Chip maker", ["ro.soc.manufacturer"]),
        ("Chip model", ["ro.soc.model"]),
        ("Hardware SKU", ["ro.boot.hardware.sku"]),
        ("Board ID", ["ro.boot.board_id"]),
        ("CPU ABI", ["ro.product.cpu.abi"]),
        ("All ABIs", ["ro.product.cpu.abilist"]),
        ("Screen density (dpi)", ["ro.sf.lcd_density"]),
    ]),
    ("Boot", [
        ("Bootloader version", ["ro.bootloader", "ro.boot.bootloader"]),
        ("Verified boot state", ["ro.boot.verifiedbootstate"]),
        ("Verified boot lock", ["ro.boot.vbmeta.device_state"]),
        ("dm-verity mode", ["ro.boot.veritymode"]),
        ("Active slot", ["ro.boot.slot_suffix"]),
        ("USB configuration", ["sys.usb.config", "persist.sys.usb.config"]),
        ("Last boot reason", ["sys.boot.reason", "ro.boot.bootreason"]),
        ("Boot mode", ["ro.bootmode", "ro.boot.mode"]),
        ("Boot finished", ["sys.boot_completed"]),
    ]),
    ("Modem and telecom", [
        ("Modem (baseband) version", ["gsm.version.baseband", "ro.baseband"]),
        ("Radio firmware", ["ro.boot.radio", "ro.build.expect.baseband"]),
        ("Radio interface (RIL)", ["gsm.version.ril-impl"]),
        ("Phone type", ["gsm.current.phone-type"]),
        ("Network operator", ["gsm.operator.alpha"]),
        ("Network code (MCC and MNC)", ["gsm.operator.numeric"]),
        ("Network country", ["gsm.operator.iso-country"]),
        ("Network type", ["gsm.network.type"]),
        ("Roaming", ["gsm.operator.isroaming"]),
        ("Preferred network mode", ["ro.telephony.default_network"]),
        ("SIM slots", ["persist.radio.multisim.config", "ro.telephony.sim.count"]),
        ("VoLTE available", ["persist.dbg.volte_avail_ovr"]),
        ("Wi-Fi calling available", ["persist.dbg.wfc_avail_ovr"]),
        ("Video calling available", ["persist.dbg.vt_avail_ovr"]),
    ]),
    ("SIM card", [
        ("SIM state", ["gsm.sim.state"]),
        ("SIM operator", ["gsm.sim.operator.alpha"]),
        ("SIM code (MCC and MNC)", ["gsm.sim.operator.numeric"]),
        ("SIM country", ["gsm.sim.operator.iso-country"]),
    ]),
    ("Region and time", [
        ("Time zone", ["persist.sys.timezone"]),
        ("Language", ["persist.sys.locale", "ro.product.locale"]),
    ]),
    ("Servicing and debugging", [
        ("Debuggable build", ["ro.debuggable"]),
        ("Secure build (adb root blocked)", ["ro.secure"]),
        ("Build tags", ["ro.build.tags"]),
        ("Built by", ["ro.build.user"]),
        ("Built on", ["ro.build.host"]),
        ("OEM unlock allowed in settings", ["sys.oem_unlock_allowed"]),
        ("OEM unlock supported", ["ro.oem_unlock_supported"]),
        ("Wireless debugging port", ["service.adb.tcp.port"]),
        ("Encryption type", ["ro.crypto.type"]),
        ("Vendor security patch", ["ro.vendor.build.security_patch"]),
        ("Vendor build", ["ro.vendor.build.fingerprint"]),
        ("Vendor API level", ["ro.vndk.version"]),
    ]),
]

# Readable values for properties that hold codes.
_VALUE_NAMES = {
    "Phone type": {"0": "None", "1": "GSM (2G, 3G, 4G)", "2": "CDMA", "3": "SIP"},
    "Roaming": {"true": "Yes", "false": "No"},
    "VoLTE available": {"1": "Yes", "0": "No"},
    "Wi-Fi calling available": {"1": "Yes", "0": "No"},
    "Video calling available": {"1": "Yes", "0": "No"},
    "Debuggable build": {"1": "Yes", "0": "No"},
    "Secure build (adb root blocked)": {"1": "Yes", "0": "No (adb can run as root)"},
    "OEM unlock allowed in settings": {"1": "Yes", "0": "No"},
    "OEM unlock supported": {"1": "Yes", "0": "No"},
    "Boot finished": {"1": "Yes", "0": "Not yet"},
    "Preferred network mode": {"9": "4G/3G/2G auto", "10": "4G/3G/2G auto (CDMA too)", "22": "5G/4G/3G/2G auto",
                               "26": "5G/4G/3G/2G auto (all)", "33": "5G/4G/3G/2G auto (all)", "0": "3G/2G auto"},
}

# `settings get` readings for the Connectivity section: (label, command, {value: words})
_ON_OFF = {"1": "On", "0": "Off"}
_SETTINGS = [
    ("Airplane mode", "settings get global airplane_mode_on", _ON_OFF),
    ("Wi-Fi", "settings get global wifi_on", {"1": "On", "2": "On", "0": "Off"}),
    ("Bluetooth", "settings get global bluetooth_on", _ON_OFF),
    ("Mobile data", "settings get global mobile_data", _ON_OFF),
    ("Data roaming", "settings get global data_roaming", _ON_OFF),
    ("Location", "settings get secure location_mode", {"0": "Off", "1": "Sensors only", "2": "Battery saving",
                                                       "3": "High accuracy"}),
    ("Developer options", "settings get global development_settings_enabled", _ON_OFF),
    ("USB debugging", "settings get global adb_enabled", _ON_OFF),
]

_THERMAL = {"0": "None", "1": "Light", "2": "Moderate", "3": "Severe", "4": "Critical", "5": "Emergency",
            "6": "Shutdown"}
_PARTITIONS = ("/data", "/system", "/vendor", "/product", "/system_ext", "/odm", "/cache", "/metadata",
               "/mnt/vendor/persist")

# Xiaomi / HyperOS / MIUI specifics. Shown only when the phone has them.
_XIAOMI = [
    ("System", ["ro.mi.os.version.name", "ro.miui.ui.version.name"]),
    ("System version code", ["ro.mi.os.version.code", "ro.miui.ui.version.code"]),
    ("System build", ["ro.mi.os.version.incremental", "ro.build.version.incremental"]),
    ("Region", ["ro.miui.region", "ro.miui.build.region"]),
    ("Customisation", ["ro.miui.cust_variant"]),
    ("Model code", ["ro.product.mod_device"]),
    ("Carrier lock", ["ro.carrier"]),
]

_FEATURES = {
    "android.hardware.nfc": "NFC", "android.hardware.nfc.hce": "NFC payments",
    "android.hardware.fingerprint": "Fingerprint reader", "android.hardware.consumerir": "IR blaster",
    "android.hardware.camera.front": "Front camera", "android.hardware.camera.flash": "Camera flash",
    "android.hardware.bluetooth_le": "Bluetooth LE", "android.hardware.wifi.direct": "Wi-Fi Direct",
    "android.hardware.usb.host": "USB OTG", "android.hardware.sensor.gyroscope": "Gyroscope",
    "android.hardware.sensor.barometer": "Barometer", "android.hardware.sensor.compass": "Compass",
    "android.hardware.sensor.proximity": "Proximity sensor", "android.hardware.sensor.light": "Light sensor",
    "android.hardware.telephony": "Calls and SMS", "android.hardware.fingerprint.face": "Face unlock",
}

_IMEI_PROPS = [("IMEI 1", ["ro.ril.miui.imei0", "ro.ril.oem.imei", "ro.ril.oem.imei1"]),
               ("IMEI 2", ["ro.ril.miui.imei1", "ro.ril.oem.imei2"]),
               ("MEID", ["ro.ril.oem.meid", "ro.ril.miui.meid"])]

# Telephony service calls, tried in turn: (label, command). Output is a Parcel dump.
_IMEI_CALLS = [
    ("IMEI 1", "service call iphonesubinfo 3 i32 0 s16 com.android.shell"),
    ("IMEI 2", "service call iphonesubinfo 3 i32 1 s16 com.android.shell"),
    ("IMEI 1", "service call iphonesubinfo 1 s16 com.android.shell"),
    ("IMEI 1", "service call iphonesubinfo 1"),
]


# ------------------------------------------------------------------ parsing
def luhn_ok(digits: str) -> bool:
    """IMEIs end in a Luhn check digit; it separates a real IMEI from noise."""
    if not (digits.isdigit() and len(digits) == 15):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n *= 2
            n = n - 9 if n > 9 else n
        total += n
    return total % 10 == 0


def parse_parcel_string(dump: str) -> Optional[str]:
    """The string inside `service call` output ("Result: Parcel(0x00: 00000000 0000000f ...)")."""
    words = re.findall(r"\b[0-9a-fA-F]{8}\b", re.sub(r"0x[0-9a-fA-F]+:|'[^']*'", "", dump))
    if len(words) < 3 or int(words[0], 16) != 0:  # first word is the status; 0 = success
        return None
    length = int(words[1], 16)
    chars = []
    for word in words[2:]:
        value = int(word, 16)
        for shift in (0, 16):  # two UTF-16 characters per word, low half first
            unit = (value >> shift) & 0xFFFF
            if unit:
                chars.append(chr(unit))
    text = "".join(chars)[:length]
    return text or None


def parse_getprop(text: str) -> Dict[str, str]:
    props: Dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"\[(.+?)\]: \[(.*)\]", line.strip())
        if m:
            props[m.group(1)] = m.group(2)
    return props


def _clean(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return None if value.lower() in _JUNK else value


def _pick(props: Dict[str, str], names: List[str], keep_zero: bool = False) -> Optional[str]:
    """The first property with a real value. A "0" counts as a value only for yes/no and code
    properties (keep_zero), where it means "No" rather than "nothing"."""
    for name in names:
        raw = (props.get(name) or "").strip()
        value = raw if keep_zero and raw == "0" else _clean(raw)
        if value:
            return value
    return None


def parse_features(text: str) -> List[str]:
    """Readable names of the hardware features `pm list features` reports."""
    have = {line.split(":", 1)[1].split("=")[0].strip() for line in text.splitlines() if line.startswith("feature:")}
    return [name for key, name in _FEATURES.items() if key in have]


def parse_cmdline(text: str) -> Dict[str, str]:
    """The key=value words of the kernel command line (androidboot.hwc=..., androidboot.baseband=...)."""
    return {k: v for k, _eq, v in (word.partition("=") for word in text.split()) if k and v}


def parse_partitions(text: str) -> List[Tuple[str, str]]:
    """Size and use of the main partitions from `df -h`: ("/data", "42G of 110G used (39%)")."""
    out: List[Tuple[str, str]] = []
    seen = set()
    for line in text.splitlines():
        cols = line.split()
        if len(cols) >= 6 and cols[-1] in _PARTITIONS and cols[-1] not in seen and cols[-2].endswith("%"):
            seen.add(cols[-1])
            out.append((cols[-1], f"{cols[2]} of {cols[1]} used ({cols[4]})"))
    order = {p: i for i, p in enumerate(_PARTITIONS)}
    return sorted(out, key=lambda r: order[r[0]])


def parse_gpu_renderer(text: str) -> List[Tuple[str, str]]:
    """From SurfaceFlinger's "GLES: Qualcomm, Adreno (TM) 618, OpenGL ES 3.2 V@..." line."""
    m = re.search(r"GLES:\s*([^,]+),\s*([^,]+),\s*(.+)", text)
    if not m:
        return []
    return [("GPU", m.group(2).strip()), ("GPU maker", m.group(1).strip()),
            ("Graphics driver", m.group(3).strip()[:80])]


def parse_sensors(text: str) -> List[Tuple[str, str]]:
    """The phone's hardware sensors from `dumpsys sensorservice`: (what it measures, chip and maker).
    Lines look like "0x0000001) bmi160 Accelerometer | Bosch | ver: 1 | type: android.sensor.accelerometer(1)"."""
    out: List[Tuple[str, str]] = []
    seen = set()
    for line in text.splitlines():
        m = re.match(r"\s*0x[0-9a-fA-F]+\)\s*(.+?)\s*\|\s*(.+?)\s*\|.*?type:\s*android\.sensor\.([\w.]+)", line)
        if not m:
            continue
        chip, maker, kind = m.group(1), m.group(2), m.group(3)
        label = kind.replace("_", " ").replace(".", " ").strip().capitalize()
        if "wake" in chip.lower() or (label, chip) in seen:
            continue  # the wake-up twin of a sensor listed already
        seen.add((label, chip))
        out.append((label, f"{chip} ({maker})"))
    return out[:40]


def opengl_version(value: Optional[str]) -> Optional[str]:
    """ro.opengles.version packs major and minor into one number (196610 = 3.2)."""
    if value and value.isdigit():
        number = int(value)
        return f"{number >> 16}.{number & 0xFFFF}"
    return None


def storage_type(bootdevice: Optional[str]) -> Optional[str]:
    name = (bootdevice or "").lower()
    return "UFS" if "ufs" in name else ("eMMC" if "sdhci" in name or "mmc" in name else None)


def battery_wear(full: str, design: str) -> Optional[Tuple[int, int, int]]:
    """(full-charge mAh, design mAh, health %) from the battery's own counters (µAh or mAh)."""
    if not (full.strip().isdigit() and design.strip().isdigit()) or int(design) <= 0:
        return None
    scale = 1000 if int(design) > 100000 else 1
    f, d = int(full) // scale, int(design) // scale
    return (f, d, round(100 * f / d)) if 0 < f <= d * 1.3 else None


def parse_battery(text: str) -> List[Tuple[str, str]]:
    kv = dict(re.findall(r"^\s*([A-Za-z ]+):\s*(\S.*)$", text, re.M))
    health = {"2": "Good", "3": "Overheat", "4": "Dead", "5": "Over voltage", "6": "Failure", "7": "Cold"}
    status = {"2": "Charging", "3": "Discharging", "4": "Not charging", "5": "Full"}
    out: List[Tuple[str, str]] = []
    if "level" in kv:
        out.append(("Charge", f"{kv['level']}%"))
    if "health" in kv:
        out.append(("Health", health.get(kv["health"].strip(), kv["health"])))
    if "status" in kv:
        out.append(("Status", status.get(kv["status"].strip(), kv["status"])))
    if "voltage" in kv:
        out.append(("Voltage", f"{kv['voltage']} mV"))
    if "temperature" in kv and kv["temperature"].strip().isdigit():
        out.append(("Temperature", f"{int(kv['temperature']) / 10:.1f} °C"))
    if "technology" in kv:
        out.append(("Technology", kv["technology"]))
    plugged = [name for name, key in (("AC", "AC powered"), ("USB", "USB powered"), ("wireless", "Wireless powered"))
               if kv.get(key, "").strip() == "true"]
    out.append(("Power source", ", ".join(plugged) if plugged else "Battery"))
    return out


def parse_fastboot_vars(lines: List[str]) -> List[Tuple[str, str]]:
    """`getvar all` replies as (name, value). Handles "(bootloader) key: value" and "key: value"."""
    out: List[Tuple[str, str]] = []
    for line in lines:
        line = line.replace("(bootloader)", "").strip()
        if ": " not in line or line.lower().startswith(("finished", "all:")):
            continue
        key, value = line.split(": ", 1)
        if key.strip() and value.strip():
            out.append((key.strip(), value.strip()))
    return out


# ------------------------------------------------------------------ the phone
def phone_details(phone) -> List[Section]:
    """All the extra details a running Android phone gives over adb, in sections."""
    cmds = ["getprop", "settings get global device_name", "settings get secure android_id",
            "settings get secure bluetooth_address", "cat /sys/class/net/wlan0/address",
            "ip -4 addr show wlan0", "cat /proc/uptime", "dumpsys battery", "wm density", "getenforce",
            "grep -m1 Hardware /proc/cpuinfo", "nproc", "pm list features",
            "dumpsys display | grep -o 'fps=[0-9.]*' | sort -u",
            "cat /sys/class/power_supply/battery/cycle_count",
            "cat /sys/class/power_supply/battery/charge_full",
            "cat /sys/class/power_supply/battery/charge_full_design",
            "pm list packages | wc -l", "pm list packages -3 | wc -l",
            "dumpsys package com.google.android.gms | grep -m1 versionName",
            "dumpsys SurfaceFlinger | grep -m1 GLES",
            "dumpsys sensorservice | grep -E '^ *0x[0-9a-fA-F]+\\)'",
            "uname -a", "cat /proc/cmdline", "df -h",
            "dumpsys thermalservice | grep -m1 -i 'Thermal Status'",
            "dumpsys telephony.registry | grep -m1 mDataConnectionState",
            "dumpsys telephony.registry | grep -m1 -o 'level=[0-9]'"]
    cmds += [cmd for _label, cmd, _names in _SETTINGS]
    cmds += [cmd for _label, cmd in _IMEI_CALLS]
    raw = phone.shell("; ".join(f"echo {_MARK}; {c} 2>/dev/null" for c in cmds), 60000)
    parts = [p.strip() for p in raw.split(_MARK)[1:]]
    parts += [""] * (len(cmds) - len(parts))
    out = dict(zip(cmds, parts))
    props = parse_getprop(out["getprop"])

    sections: List[Section] = []
    identity: List[Tuple[str, str]] = []
    for label, names in _PROP_SECTIONS[0][1]:
        value = _pick(props, names)
        if label == "Serial number" and (value == phone.serial or is_wireless(phone.serial)):
            continue  # already shown with the basic details (over Wi-Fi the phone's own serial is shown there too)
        if value:
            identity.append((label, value))
    imeis = _imeis(props, out)
    identity += imeis if imeis else [("IMEI", "Not given out over USB on this phone. Dial *#06# to see it.")]
    for label, value in (("Android ID", _clean(out["settings get secure android_id"])),
                         ("Device name", _clean(out["settings get global device_name"])),
                         ("Wi-Fi address", _mac(out["cat /sys/class/net/wlan0/address"])),
                         ("Bluetooth address", _mac(out["settings get secure bluetooth_address"]))):
        if value:
            identity.append((label, value))
    sections.append(("Identity", identity))

    for title, items in _PROP_SECTIONS[1:]:
        rows = [(label, v) for label, names in items if (v := _pick(props, names, keep_zero=label in _VALUE_NAMES))]
        if title == "Hardware":
            m = re.search(r"(?:Override|Physical) density:\s*(\d+)", out["wm density"])
            if m and not any(lbl.startswith("Screen density") for lbl, _ in rows):
                rows.append(("Screen density (dpi)", m.group(1)))
            cpu = re.search(r":\s*(.+)", out["grep -m1 Hardware /proc/cpuinfo"])
            extra = [("Processor", cpu.group(1).strip() if cpu else None),
                     ("CPU cores", out["nproc"] if out["nproc"].isdigit() else None),
                     ("Graphics (OpenGL ES)", opengl_version(props.get("ro.opengles.version"))),
                     ("Storage type", storage_type(props.get("ro.boot.bootdevice"))),
                     ("Screen refresh rates", ", ".join(sorted({f"{float(r):g} Hz" for r in re.findall(
                         r"fps=([0-9.]+)", out["dumpsys display | grep -o 'fps=[0-9.]*' | sort -u"])},
                         key=lambda x: float(x.split()[0]))) or None)]
            rows += [(k, v) for k, v in extra if v]
            rows += parse_gpu_renderer(out["dumpsys SurfaceFlinger | grep -m1 GLES"])
            features = parse_features(out["pm list features"])
            if features:
                rows.append(("Features", ", ".join(features)))
        if title == "Software":
            total, mine = out["pm list packages | wc -l"], out["pm list packages -3 | wc -l"]
            if total.isdigit() and mine.isdigit():
                rows.append(("Apps installed", f"{total} ({mine} by you)"))
            play = out["dumpsys package com.google.android.gms | grep -m1 versionName"].split("=")[-1].strip()
            if play and "=" in out["dumpsys package com.google.android.gms | grep -m1 versionName"]:
                rows.append(("Google Play services", play))
        if title == "Boot":
            mode = _clean(out["getenforce"])
            if mode:
                rows.append(("SELinux", mode))
            boot = parse_cmdline(out["cat /proc/cmdline"])
            rows += [(label, boot[key]) for label, key in (("Bootloader (kernel line)", "androidboot.bootloader"),
                                                           ("Baseband (kernel line)", "androidboot.baseband"))
                     if key in boot and not any(v == boot[key] for _l, v in rows)]
        if title == "Servicing and debugging":
            kernel = _clean(out["uname -a"])
            if kernel:
                rows.append(("Kernel", kernel))
        rows = [(label, _VALUE_NAMES.get(label, {}).get(value, value)) for label, value in rows]
        if rows:
            sections.append((title, rows))
    connectivity: List[Tuple[str, str]] = []
    for label, cmd, names in _SETTINGS:
        value = _clean(out[cmd]) or ("0" if out[cmd].strip() == "0" else None)
        if value is not None:
            connectivity.append((label, names.get(value, value)))
    data = re.search(r"mDataConnectionState=(\d)", out["dumpsys telephony.registry | grep -m1 mDataConnectionState"])
    if data:
        connectivity.append(("Mobile data link", {"0": "Disconnected", "1": "Connecting", "2": "Connected",
                                                 "3": "Suspended"}.get(data.group(1), data.group(1))))
    bars = re.search(r"level=(\d)", out["dumpsys telephony.registry | grep -m1 -o 'level=[0-9]'"])
    if bars:
        connectivity.append(("Signal strength", f"{bars.group(1)} of 4 bars"))
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out["ip -4 addr show wlan0"])
    if m:
        connectivity.append(("Wi-Fi IP address", m.group(1)))
    m = re.match(r"([\d.]+)", out["cat /proc/uptime"])
    if m:
        hours = float(m.group(1)) / 3600
        connectivity.append(("Up for", f"{hours:.1f} hours" if hours < 48 else f"{hours / 24:.1f} days"))
    if connectivity:
        sections.append(("Connectivity and state", connectivity))
    parts_rows = parse_partitions(out["df -h"])
    if parts_rows:
        sections.append(("Partitions", parts_rows))
    sensors = parse_sensors(out["dumpsys sensorservice | grep -E '^ *0x[0-9a-fA-F]+\\)'"])
    if sensors:
        sections.append(("Sensors on this phone", sensors))
    xiaomi = [(label, v) for label, names in _XIAOMI if (v := _pick(props, names))]
    if xiaomi and ("xiaomi" in (props.get("ro.product.manufacturer", "") + props.get("ro.product.brand", "")).lower()
                   or props.get("ro.miui.ui.version.name") or props.get("ro.mi.os.version.name")):
        sections.append(("Xiaomi / HyperOS", xiaomi))
    battery = parse_battery(out["dumpsys battery"])
    thermal = re.search(r"Thermal Status:\s*(\d)", out["dumpsys thermalservice | grep -m1 -i 'Thermal Status'"])
    if thermal:
        battery.append(("Heat throttling", _THERMAL.get(thermal.group(1), thermal.group(1))))
    cycles = out["cat /sys/class/power_supply/battery/cycle_count"].strip()
    if cycles.isdigit() and int(cycles) > 0:
        battery.append(("Charge cycles", cycles))
    wear = battery_wear(out["cat /sys/class/power_supply/battery/charge_full"],
                        out["cat /sys/class/power_supply/battery/charge_full_design"])
    if wear:
        battery += [("Full-charge capacity", f"{wear[0]} mAh"), ("Design capacity", f"{wear[1]} mAh"),
                    ("Battery health", f"{wear[2]}%")]
    if battery:
        sections.append(("Battery", battery))
    return sections


def _mac(text: str) -> Optional[str]:
    text = text.strip()
    return text if re.fullmatch(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", text) and text != "00:00:00:00:00:00" else None


def _imeis(props: Dict[str, str], shell_out: Dict[str, str]) -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []
    seen = set()

    def add(label: str, value: Optional[str]) -> None:
        if value and value not in seen and (label == "MEID" or luhn_ok(value)):
            seen.add(value)
            found.append((label, value))

    for label, names in _IMEI_PROPS:
        add(label, _pick(props, names))
    if not found:
        for label, cmd in _IMEI_CALLS:
            add(label, parse_parcel_string(shell_out.get(cmd, "")))
    # keep the first IMEI as 1 and the next as 2 whatever the source called them
    imei_rows = [v for lbl, v in found if lbl.startswith("IMEI")]
    others = [(lbl, v) for lbl, v in found if not lbl.startswith("IMEI")]
    return [(f"IMEI {i + 1}", v) for i, v in enumerate(imei_rows)] + others


# ---------------------------------------------------------------- fastboot
def fastboot_details(serial: Optional[str] = None) -> List[Section]:
    pairs = parse_fastboot_vars(fastboot.all_vars(serial))
    return [("Everything the bootloader reports", pairs)] if pairs else []


def as_text(sections: List[Section]) -> str:
    """The sections as plain text, for Copy."""
    lines: List[str] = []
    for title, rows in sections:
        lines += ["", f"[{title}]"] + [f"{k}: {v}" for k, v in rows]
    return "\n".join(lines).strip()
