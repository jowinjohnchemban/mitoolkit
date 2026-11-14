"""
Programmatic API for scripts, CI pipelines, and AI agents.

Every function here returns plain dicts or raises UnlockError, instead of
printing to a console or blocking on input() -- with one unavoidable
exception: logging in for the first time still requires a human to
complete Xiaomi's own browser or QR login page. That is not a limitation
to work around; it is the entire reason this fork exists (see CHANGES.md)
-- the account password should never pass through code that isn't
Xiaomi's own login page, automated or not.

The one genuinely destructive action, perform_unlock(), refuses to run
unless called with confirm_wipe=True. Unlocking wipes the device's user
data with no undo. That decision must be made by a human, every time --
never hardcoded, never defaulted, never inferred by an agent from
context. If you are wiring this up for automation, confirm_wipe=True
should be the one line a human reviews and sets on purpose.

This module intentionally re-implements (rather than calls into) the
request sequence in miunlock.unlock.unlock_device(), because that
function is interactive by design (console.input() prompts baked into
the flow) and this module must not block. If Xiaomi's unlock protocol
changes, both this file and unlock.py need updating -- see CHANGES.md.
"""
from __future__ import annotations

import hashlib
import os
import random
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from miunlock.auth import get_passtoken, get_service, get_region, get_dataCenterZone
from miunlock.fastboot import get_fastboot
from miunlock.commands import get_product, get_device_token
from miunlock.system import NO_WINDOW
from miunlock.utils import _send

DOMAIN_BY_ZONE = {
    "Singapore": "https://unlock.update.intl.miui.com",
    "China": "https://unlock.update.miui.com",
    "India": "https://in-unlock.update.intl.miui.com",
    "Russia": "https://ru-unlock.update.intl.miui.com",
    "Europe": "https://eu-unlock.update.intl.miui.com",
}

_EUROPE_CODES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "EL",
    "HU", "IS", "IE", "IT", "LV", "LI", "LT", "LU", "MT", "NL", "NO", "PL",
    "PT", "RO", "SK", "SI", "ES", "SE", "UK",
}
REGION_TO_ZONE = {"CN": "China", "IN": "India", "RU": "Russia",
                   **{c: "Europe" for c in _EUROPE_CODES}}


class UnlockError(Exception):
    """Raised for any rejected or failed step. str(e) is human-readable."""


def login(login_method: str = "1", silent_if_cached: bool = True) -> dict:
    """
    Returns the session dict {deviceId, passToken, userId} on success.

    login_method: "1" for browser (default) or "3" for QR code. Ignored
    if a cached session is reused.

    If a saved session already exists (~/.miunlocksession/unlockApi/),
    it's reused with no prompt when silent_if_cached is True (default).
    Otherwise this opens a real browser / prints a QR code and WAITS for
    a human to finish logging in on Xiaomi's own page. There is no way
    around that step, and there will not be one added.
    """
    param = {"sid": "unlockApi", "checkSafeAddress": True}
    token = get_passtoken(param, silent=silent_if_cached, login_method=login_method)
    if token is None:
        raise UnlockError("Login failed or was cancelled.")
    return token


def get_account_zone(passtoken: dict) -> str:
    """Returns one of DOMAIN_BY_ZONE's keys for this account."""
    region = get_region(passtoken)
    if region:
        return REGION_TO_ZONE.get(region, "Singapore")
    zone = get_dataCenterZone(passtoken["userId"])
    if not zone:
        raise UnlockError("Could not determine the account's dataCenterZone.")
    return zone


def get_device_codename(fastboot_cmd: Optional[str] = None) -> str:
    """Phone must already be in fastboot mode and connected over USB."""
    fastboot_cmd = fastboot_cmd or get_fastboot()
    product = get_product(fastboot_cmd)
    if isinstance(product, dict) and "error" in product:
        raise UnlockError(product["error"])
    return product


def check_unlock_eligibility(passtoken: dict, zone: Optional[str] = None) -> dict:
    """
    Safe and non-destructive: asks Xiaomi's server whether this
    account/device can currently be unlocked. Reads the device codename
    over fastboot but does not fetch a token and does not touch
    `fastboot oem unlock`.

    Returns a dict with at least {"eligible": bool}. On rejection,
    includes "code" and "description" straight from Xiaomi -- e.g. the
    20031 ("add your account in Mi Unlock status") or 20036 ("wait 168
    hours") responses documented in CHANGES.md.
    """
    service = get_service(passtoken, {"sid": "unlockApi"})
    if service is None:
        raise UnlockError("Could not establish a service session.")
    zone = zone or get_account_zone(passtoken)
    domain = DOMAIN_BY_ZONE[zone]

    fastboot_cmd = get_fastboot()
    product = get_device_codename(fastboot_cmd)

    ssecurity = service["servicedata"]["ssecurity"]
    cookies = service["cookies"]

    r = "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=16))
    nonce_resp = _send("/api/v2/nonce", {"r": r}, domain, ssecurity, cookies)
    if "error" in nonce_resp or nonce_resp.get("code") != 0:
        raise UnlockError(str(nonce_resp.get("error", nonce_resp)))

    clear = _send(
        "/api/v2/unlock/device/clear",
        {"appId": "1", "data": {"product": product}, "nonce": nonce_resp["nonce"]},
        domain, ssecurity, cookies,
    )
    if "error" in clear:
        return {"eligible": False, "product": product, "zone": zone, "error": clear["error"]}
    if clear.get("code") != 0:
        return {
            "eligible": False, "product": product, "zone": zone,
            "code": clear.get("code"), "description": clear.get("descEN", clear),
        }

    return {
        "eligible": True,
        "product": product,
        "zone": zone,
        "will_wipe_data": bool(clear.get("cleanOrNot")),
        "notice": clear.get("notice"),
        "_service": service,  # reused by perform_unlock to avoid a second login round trip
    }


def perform_unlock(passtoken: dict, eligibility: dict, *, confirm_wipe: bool) -> dict:
    """
    THE destructive step. Fetches the real unlock token and runs
    `fastboot oem unlock`, which wipes the device's user data with no
    undo, immediately, no further confirmation after this call starts.

    confirm_wipe must be explicitly True -- there is no default that
    makes this run. If you're wiring this into an agent, a script, or a
    CI job: this flag is the one line that must be a human's deliberate
    choice, every time, not inferred and not hardcoded "for convenience"
    anywhere in your own wrapper.
    """
    if not confirm_wipe:
        raise UnlockError(
            "Refusing to unlock: confirm_wipe=True was not passed. This "
            "action wipes all data on the device with no undo. Set "
            "confirm_wipe=True only after a human has explicitly decided "
            "to proceed, having been told exactly what this does."
        )
    if not eligibility.get("eligible"):
        raise UnlockError(
            "eligibility dict is not marked eligible -- call "
            "check_unlock_eligibility() first and check its result."
        )

    service = eligibility.get("_service")
    if service is None:
        raise UnlockError(
            "eligibility dict is missing its service session; this "
            "function only accepts a dict returned by "
            "check_unlock_eligibility(), not a hand-built one."
        )

    zone = eligibility["zone"]
    domain = DOMAIN_BY_ZONE[zone]
    product = eligibility["product"]
    ssecurity = service["servicedata"]["ssecurity"]
    cookies = service["cookies"]
    device_id = service["servicedata"]["deviceId"]

    fastboot_cmd = get_fastboot()
    device_token = get_device_token(fastboot_cmd)
    if isinstance(device_token, dict) and "error" in device_token:
        raise UnlockError(device_token["error"])

    data = {
        "clientId": "2",
        "clientVersion": "7.6.727.43",
        "deviceInfo": {"boardVersion": "", "deviceName": "", "product": product, "socId": ""},
        "deviceToken": device_token,
        "language": "en",
        "operate": "unlock",
        "pcId": hashlib.md5(device_id.encode()).hexdigest(),
        "region": "",
        "uid": cookies.get("userId"),
    }

    r = "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=16))
    nonce_resp = _send("/api/v2/nonce", {"r": r}, domain, ssecurity, cookies)
    if "error" in nonce_resp or nonce_resp.get("code") != 0:
        raise UnlockError(str(nonce_resp.get("error", nonce_resp)))

    unlock_result = _send(
        "/api/v3/ahaUnlock", {"appId": "1", "data": data, "nonce": nonce_resp["nonce"]},
        domain, ssecurity, cookies,
    )
    if "error" in unlock_result:
        raise UnlockError(str(unlock_result["error"]))
    if unlock_result.get("code") != 0:
        raise UnlockError(str(unlock_result.get("descEN", unlock_result)))

    encrypt_data = unlock_result["encryptData"]
    # A private (owner-only), unpredictably named file, deleted as soon as fastboot is done.
    fd, name = tempfile.mkstemp(prefix="miunlock-", suffix=".encryptData")
    filename = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(bytes.fromhex(encrypt_data))

        subprocess.run([fastboot_cmd, "stage", str(filename)], check=True, capture_output=True, text=True, creationflags=NO_WINDOW)
        subprocess.run([fastboot_cmd, "oem", "unlock"], check=True, capture_output=True, text=True, creationflags=NO_WINDOW)
    except subprocess.CalledProcessError as e:
        raise UnlockError(e.stderr) from e
    finally:
        if filename.exists():
            filename.unlink()

    return {"success": True, "product": product}
