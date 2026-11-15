"""
Security check for a phone running Android (read-only; nothing on the phone is changed).

What it looks at, and where the facts come from:

- Phone software: the security patch level (ro.build.version.security_patch) compared with
  Android Security Bulletin entries in OSV (osv.dev, ecosystem "Android", the AOSP bulletin
  data, CC-BY 4.0). Only the Android version and AOSP project names are sent to OSV.
  OSV covers AOSP; chip-maker and Xiaomi fixes are not in it.
- Google Play: Play Protect setting, Google Play system update date, which store installed
  each app, and which apps may install other apps ("Install unknown apps").
- Apps with powerful access: accessibility services, device admin, notification access.
- Known stalkerware: package names and signing certificates from AssoEchap's
  stalkerware-indicators (CC-BY 4.0; also used by Amnesty's MVT). A name match is confirmed
  against the app's certificate when the APK carries a v1 signature.
- Malware scan (malware.py): apps not installed from a store that hold the access spyware and banking trojans rely
  on, apps that hide their icon or pretend to be system apps, programs left in /data/local/tmp, and signs of root
  or a debug build. Heuristics read through adb; nothing is uploaded.

This is not an antivirus. Google Play Protect stays the main protection on the phone.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import tempfile
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from mitoolkit import adb, malware
from mitoolkit.adbkey import _der_read

OSV_QUERY = "https://api.osv.dev/v1/query"
BULLETINS = "https://source.android.com/docs/security/bulletin"
STALKERWARE_IOC = "https://raw.githubusercontent.com/AssoEchap/stalkerware-indicators/master/ioc.yaml"
CACHE = Path.home() / ".mitoolkit" / "cache"

# Core AOSP projects whose bulletin entries are counted (OSV package names).
AOSP_PROJECTS = [
    "platform/frameworks/base", "platform/frameworks/native", "platform/frameworks/av",
    "platform/system/core", "platform/packages/modules/Bluetooth", "platform/packages/apps/Settings",
    "platform/packages/providers/MediaProvider", "platform/packages/services/Telephony",
]

# Stores whose apps are reviewed before they are offered.
TRUSTED_STORES = {
    "com.android.vending": "Google Play Store",
    "com.xiaomi.mipicks": "Xiaomi GetApps", "com.xiaomi.market": "Xiaomi GetApps",
    "com.sec.android.app.samsungapps": "Galaxy Store", "com.huawei.appmarket": "Huawei AppGallery",
    "com.amazon.venezia": "Amazon Appstore", "org.fdroid.fdroid": "F-Droid",
}

HIGH, MEDIUM, INFO, OK = "high", "medium", "info", "ok"
LEVELS = (HIGH, MEDIUM, INFO, OK)


@dataclass
class Finding:
    level: str              # high, medium, info, ok
    area: str               # "Phone software", "Google Play", "Apps"
    title: str
    detail: str = ""
    package: Optional[str] = None
    link: Optional[str] = None


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    checked: Dict[str, object] = field(default_factory=dict)

    def add(self, *args, **kw) -> None:
        self.findings.append(Finding(*args, **kw))

    @property
    def verdict(self) -> str:
        levels = {f.level for f in self.findings}
        if HIGH in levels:
            return "Needs attention"
        if MEDIUM in levels:
            return "Some things to review"
        return "Nothing found"

    def to_dict(self) -> dict:
        order = {lv: i for i, lv in enumerate(LEVELS)}
        return {"verdict": self.verdict, "checked": self.checked,
                "findings": [asdict(f) for f in sorted(self.findings, key=lambda f: order[f.level])]}


# ------------------------------------------------------------------ helpers
def _get(url: str, data: Optional[dict] = None, timeout: int = 30) -> bytes:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                           "User-Agent": "mitoolkit-security-check"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # https only, fixed hosts
        return resp.read()


def _cached(name: str, url: str, max_age_days: int = 7) -> str:
    """Download once a week; use the last copy if offline."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    fresh = path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400
    if not fresh:
        try:
            path.write_bytes(_get(url, timeout=60))
        except OSError:
            if not path.exists():
                raise
    return path.read_text(encoding="utf-8", errors="replace")


def _months_between(a: datetime.date, b: datetime.date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _parse_date(text: Optional[str]) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat((text or "")[:10])
    except ValueError:
        return None


def _packages_in_setting(value: str) -> Set[str]:
    """'pkg/.Svc:pkg2/x.Svc' -> {'pkg', 'pkg2'}"""
    return {part.split("/", 1)[0] for part in (value or "").split(":") if "/" in part}


# ------------------------------------------------------- phone software (OSV)
def osv_android(version: str, projects: List[str] = AOSP_PROJECTS) -> Dict[str, dict]:
    """Bulletin entries affecting this Android version: {id: {"spl", "severity", "project"}}."""
    def one(project: str) -> Dict[str, dict]:
        found: Dict[str, dict] = {}
        token = None
        while True:
            query = {"package": {"name": project, "ecosystem": "Android"}, "version": version}
            if token:
                query["page_token"] = token
            reply = json.loads(_get(OSV_QUERY, query))
            for vuln in reply.get("vulns", []):
                for aff in vuln.get("affected", []):
                    if version in (aff.get("versions") or []):
                        eco = aff.get("ecosystem_specific") or {}
                        if eco.get("spl"):
                            found[vuln["id"]] = {"spl": eco["spl"], "severity": eco.get("severity", ""),
                                                 "project": project}
            token = reply.get("next_page_token")
            if not token:
                return found

    merged: Dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for part in pool.map(one, projects):
            merged.update(part)
    return merged


def check_patch_level(report: Report, android: str, patch: Optional[str], today: datetime.date) -> None:
    area = "Phone software"
    spl = _parse_date(patch)
    report.checked["android"], report.checked["security_patch"] = android, patch
    if spl is None:
        report.add(MEDIUM, area, "Security patch level unknown", "The phone did not report it.")
        return
    age = _months_between(spl, today)
    try:
        vulns = osv_android(android.split(".")[0])
    except (OSError, ValueError) as err:
        report.add(INFO, area, f"Security patch {patch} ({age} months old)",
                   f"Could not reach OSV to compare it with Android's security bulletins ({err}).", link=BULLETINS)
        return
    missing = {vid: v for vid, v in vulns.items() if _parse_date(v["spl"]) and _parse_date(v["spl"]) > spl}
    latest = max((_parse_date(v["spl"]) for v in vulns.values() if _parse_date(v["spl"])), default=None)
    critical = sum(1 for v in missing.values() if v["severity"].lower() == "critical")
    high = sum(1 for v in missing.values() if v["severity"].lower() == "high")
    report.checked["osv_entries"], report.checked["missing_fixes"] = len(vulns), len(missing)

    if latest is not None and _months_between(latest, today) >= 6:
        report.add(HIGH, area, f"Android {android} no longer gets security fixes",
                   f"The last fix Android published for this version is from {latest:%B %Y}. Newer security "
                   "problems are not fixed for it. Update to a newer Android or HyperOS version if your phone "
                   "offers one.", link=BULLETINS)
    if missing:
        sev = ", ".join(s for s in (f"{critical} critical" if critical else "", f"{high} high" if high else "") if s)
        report.add(HIGH if critical or high else MEDIUM, area,
                   f"{len(missing)} known Android security fixes missing" + (f" ({sev})" if sev else ""),
                   f"Your security patch is {patch} ({age} months old). Android's security bulletins list "
                   f"{len(missing)} fixes for Android {android} after that date in the core parts checked. Install "
                   "system updates (Settings > About phone > System update). Source: OSV / Android Security "
                   "Bulletins. Xiaomi and chip-maker fixes are not included.", link=BULLETINS)
    elif age > 3:
        report.add(MEDIUM, area, f"Security patch is {age} months old ({patch})",
                   "Check for system updates in Settings > About phone.", link=BULLETINS)
    else:
        report.add(OK, area, f"Security patch {patch} is recent", "No newer Android security fixes found in OSV "
                   "for the core parts checked.", link=BULLETINS)


# ----------------------------------------------------------- Google Play
def check_play(report: Report, phone: adb.Phone, today: datetime.date) -> None:
    area = "Google Play"
    setting = phone.shell("settings get global package_verifier_enable").strip()
    report.checked["play_protect_setting"] = setting
    if setting == "0":
        report.add(HIGH, area, "Google Play Protect is off",
                   "Turn it on: Play Store > your profile picture > Play Protect > settings > Scan apps with "
                   "Play Protect.")
    else:
        report.add(OK, area, "Google Play Protect is on", "It scans apps on the phone. Open Play Store > your "
                   "profile > Play Protect to run a scan.")

    out = phone.shell("dumpsys package com.google.android.modulemetadata | grep versionName")
    m = re.search(r"versionName=(\S+)", out)
    if m and _parse_date(m.group(1)):
        when = _parse_date(m.group(1))
        report.checked["play_system_update"] = m.group(1)
        age = _months_between(when, today)
        level = MEDIUM if age >= 6 else OK
        report.add(level, area, f"Google Play system update: {when:%B %Y}",
                   "Settings > About phone > Android version > Google Play system update."
                   + (" It is more than six months old; check for an update there." if level == MEDIUM else ""))


def check_apps(report: Report, phone: adb.Phone, log: Callable[[str], None]) -> None:
    area = "Apps"
    installers: Dict[str, Optional[str]] = {}
    for line in phone.shell("pm list packages -i -3").splitlines():
        m = re.match(r"package:(\S+)\s+installer=(\S+)", line.strip())
        if m:
            installers[m.group(1)] = None if m.group(2) == "null" else m.group(2)
    report.checked["user_apps"] = len(installers)
    sideloaded = {p for p, inst in installers.items() if inst not in TRUSTED_STORES}

    access: Dict[str, List[str]] = {}
    for pkg in _packages_in_setting(phone.shell("settings get secure enabled_accessibility_services").strip()):
        access.setdefault(pkg, []).append("accessibility (can read the screen and act for you)")
    for pkg in _packages_in_setting(phone.shell("settings get secure enabled_notification_listeners").strip()):
        access.setdefault(pkg, []).append("notification access (reads your notifications and messages)")
    for pkg in set(re.findall(r"ComponentInfo\{([^/}]+)/", phone.shell("dumpsys device_policy"))):
        access.setdefault(pkg, []).append("device admin (can lock or wipe the phone, hard to uninstall)")
    try:
        allowed = phone.shell("cmd appops query-op --user 0 REQUEST_INSTALL_PACKAGES allow")
        installers_allowed = {ln.strip() for ln in allowed.splitlines() if re.match(r"^[\w.]+$", ln.strip())}
    except adb.AdbError:
        installers_allowed = set()

    for pkg, what in sorted(access.items()):
        if pkg not in installers:  # system apps with these rights are normal
            continue
        from_file = pkg in sideloaded
        report.add(HIGH if from_file else MEDIUM, area,
                   f"{pkg} has {', '.join(w.split(' (')[0] for w in what)}",
                   "It " + "; ".join(w.split(" (")[1].rstrip(")") for w in what) + ". "
                   + ("It was not installed from a store. " if from_file else "")
                   + "If you do not know why it needs this, remove the access in Settings, or remove the app.",
                   package=pkg)
    for pkg in sorted(installers_allowed & set(installers)):
        report.add(MEDIUM, area, f"{pkg} may install other apps",
                   "It has \"Install unknown apps\" permission. Turn it off unless you need it: Settings > "
                   "Apps > Special app access > Install unknown apps.", package=pkg)
    others = sorted(sideloaded - set(access) - installers_allowed)
    if others:
        report.add(INFO, area, f"{len(others)} app(s) not installed from a store",
                   "Installed from a file or another app: " + ", ".join(others[:15])
                   + (" and more" if len(others) > 15 else "") + ". Fine if you installed them on purpose.")
    check_stalkerware(report, phone, set(installers), log)
    malware.scan(report, phone, installers, set(TRUSTED_STORES), log)


# ------------------------------------------------------------- stalkerware
def parse_ioc(text: str) -> Dict[str, dict]:
    """Minimal reader for stalkerware-indicators ioc.yaml: package -> {"name", "certs"}."""
    out: Dict[str, dict] = {}
    name, key, packages, certs = None, None, [], []

    def flush():
        for pkg in packages:
            out[pkg] = {"name": name, "certs": {c.upper() for c in certs}}

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("- name:"):
            flush()
            name, key, packages, certs = line.split(":", 1)[1].strip().strip("'\""), None, [], []
        elif re.match(r"^\s{2}\w[\w_]*:", line):
            key = line.strip().split(":", 1)[0]
        elif re.match(r"^\s{2,}- ", line) and key in ("packages", "certificates"):
            value = line.strip()[2:].strip().strip("'\"")
            (packages if key == "packages" else certs).append(value)
    flush()
    return out


def apk_cert_sha1(apk: Path) -> Optional[str]:
    """SHA-1 of the first signing certificate in a v1 (JAR) signature, or None."""
    with zipfile.ZipFile(apk) as z:
        sig = next((n for n in z.namelist() if re.match(r"META-INF/[^/]+\.(RSA|DSA|EC)$", n, re.I)), None)
        if sig is None:
            return None
        der = z.read(sig)
    try:
        _t, content_info, _ = _der_read(der, 0)                  # ContentInfo
        _t, explicit, _ = _der_read(content_info, _der_read(content_info, 0)[2])  # [0] EXPLICIT
        _t, signed_data, _ = _der_read(explicit, 0)              # SignedData
        pos = 0
        while pos < len(signed_data):
            tag, value, end = _der_read(signed_data, pos)
            if tag == 0xA0:                                      # [0] certificates
                _ctag, _cval, cend = _der_read(value, 0)
                return hashlib.sha1(value[:cend]).hexdigest().upper()
            pos = end
    except (IndexError, ValueError):
        return None
    return None


def check_stalkerware(report: Report, phone: adb.Phone, packages: Set[str], log: Callable[[str], None]) -> None:
    area = "Apps"
    try:
        ioc = parse_ioc(_cached("stalkerware-ioc.yaml", STALKERWARE_IOC))
    except OSError as err:
        report.add(INFO, area, "Stalkerware list not available", f"Could not download it ({err}).")
        return
    report.checked["stalkerware_packages_known"] = len(ioc)
    hits = sorted(packages & set(ioc))
    if not hits:
        report.add(OK, area, "No known stalkerware found",
                   f"Your apps were compared with {len(ioc)} package names of known stalkerware "
                   "(AssoEchap stalkerware-indicators). Such lists are never complete.")
        return
    for pkg in hits:
        family = ioc[pkg]["name"]
        confirmed = None
        try:
            path = phone.shell(f"pm path {adb.valid_package(pkg)}").strip().splitlines()[0].replace("package:", "")
            log(f"Checking the certificate of {pkg}")
            with tempfile.TemporaryDirectory() as tmp:
                local = Path(tmp) / "base.apk"
                sync = phone.sync()
                sync.recv(path, local)
                sync.close()
                cert = apk_cert_sha1(local)
            if cert is not None and ioc[pkg]["certs"]:
                confirmed = cert in ioc[pkg]["certs"]
        except (adb.AdbError, OSError, IndexError, zipfile.BadZipFile):
            confirmed = None
        if confirmed is False:
            report.add(INFO, area, f"{pkg} shares a name with {family}",
                       "Its signing certificate does not match the known stalkerware, so it is probably a "
                       "different app with the same name.", package=pkg)
        else:
            report.add(HIGH, area, f"Possible stalkerware: {family} ({pkg})",
                       ("Its signing certificate matches the known stalkerware. " if confirmed else
                        "Its package name matches known stalkerware (the certificate could not be checked). ")
                       + "Stalkerware secretly reports your messages and location to someone else. If you did "
                       "not install it, get advice before removing it (removing it can alert whoever installed "
                       "it): https://stopstalkerware.org", package=pkg)


# ------------------------------------------------------------------ quick check
def passive(info: Dict[str, object], play_protect: Optional[str] = None,
            today: Optional[datetime.date] = None) -> Report:
    """A quick, local look at what the phone already told us: no network, no app scan, nothing changed.
    It colours the Security check button as soon as a phone is connected; the full check goes deeper.
    ``info`` is adb.Phone.info(); ``play_protect`` is the value of the package_verifier_enable setting."""
    today = today or datetime.date.today()
    area, report = "Quick check", Report()
    spl = _parse_date(info.get("security_patch"))  # type: ignore[arg-type]
    if spl is not None:
        age = _months_between(spl, today)
        report.checked["security_patch_months"] = age
        if age >= 12:
            report.add(HIGH, area, f"Security patch is {age} months old")
        elif age > 3:
            report.add(MEDIUM, area, f"Security patch is {age} months old")
    boot = str(info.get("verified_boot") or "").lower()
    if boot == "red":
        report.add(HIGH, area, "Verified boot reports the system was changed")
    elif boot in ("yellow", "orange"):
        report.add(MEDIUM, area, "Verified boot is not green (the bootloader is unlocked or a custom system is installed)")
    elif info.get("bootloader_locked") is False:
        report.add(MEDIUM, area, "The bootloader is unlocked")
    if str(info.get("encryption") or "").lower() == "unencrypted":
        report.add(HIGH, area, "Storage is not encrypted")
    if play_protect is not None and play_protect.strip() == "0":
        report.add(HIGH, area, "Google Play Protect is off")
    return report


# ---------------------------------------------------------------------- run
def run(serial: Optional[str] = None, log: Callable[[str], None] = lambda _t: None,
        today: Optional[datetime.date] = None) -> Report:
    """Run every check and return a Report. Read-only for the phone."""
    today = today or datetime.date.today()
    phone = adb.Phone(serial)
    report = Report()
    info = phone.info()
    log("Checking the security patch against Android's security bulletins (OSV)")
    check_patch_level(report, str(info.get("android") or ""), info.get("security_patch"), today)
    log("Checking Google Play Protect and the Google Play system update")
    check_play(report, phone, today)
    log("Checking apps: where they came from, what access they have, known stalkerware")
    check_apps(report, phone, log)
    return report
