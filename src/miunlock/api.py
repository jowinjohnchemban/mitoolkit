"""
Programmatic API for scripts, CI pipelines, and AI agents.

Every function here returns plain dicts or raises UnlockError, instead of
printing to a console or blocking on input() -- with one unavoidable
exception: logging in for the first time still requires a human to
complete Xiaomi's own browser or QR login page. That is not a limitation
to work around; it is deliberate: the account password should never pass through code that isn't
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

from contextlib import contextmanager
from typing import Iterator, Optional

from miunlock import adb, fastboot, log
from miunlock.auth import get_passtoken, get_service, get_region, get_dataCenterZone
from miunlock.auth.redact import redact_response
from miunlock.errors import MiunlockError, UnlockError
from miunlock.xiaomi import DOMAIN_BY_ZONE, REGION_TO_ZONE, UnlockServer, zone_for_region  # noqa: F401 re-exported

_log = log.get("api")


@contextmanager
def _as_unlock_error() -> Iterator[None]:
    """Every failure leaves this module as an UnlockError with a readable message."""
    try:
        yield
    except UnlockError:
        raise
    except MiunlockError as err:
        raise UnlockError(str(err)) from None


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
    _log.info("login: start (method=%s, reuse saved=%s)", login_method, silent_if_cached)
    token = get_passtoken(param, silent=silent_if_cached, login_method=login_method)
    if token is None:
        _log.warning("login: failed or cancelled")
        raise UnlockError("Login failed or was cancelled.")
    _log.info("login: ok")
    return token


def get_account_zone(passtoken: dict) -> str:
    """Returns one of DOMAIN_BY_ZONE's keys for this account."""
    region = get_region(passtoken)
    if region:
        return zone_for_region(region)
    zone = get_dataCenterZone(passtoken["userId"])
    if not zone:
        raise UnlockError("Could not determine the account's dataCenterZone.")
    return zone


def get_device_codename(wait: bool = True) -> str:
    """The codename of the phone in fastboot mode. With wait=True (default) it waits for
    one to be connected; with wait=False it fails at once if there is none."""
    with _as_unlock_error():
        if not wait and not any(d["accessible"] for d in fastboot.devices()):
            raise UnlockError("No phone in fastboot mode is connected.")
        return fastboot.get_product(wait=wait)


def _service(passtoken: dict) -> dict:
    service = get_service(passtoken, {"sid": "unlockApi"})
    if service is None:
        raise UnlockError("Could not establish a service session.")
    return service


def check_unlock_eligibility(passtoken: dict, zone: Optional[str] = None) -> dict:
    """
    Safe and non-destructive: asks Xiaomi's server whether this
    account/device can currently be unlocked. Reads the device codename
    over fastboot but does not fetch a token and does not touch
    `fastboot oem unlock`.

    Returns a dict with at least {"eligible": bool}. On rejection,
    includes "code" and "description" straight from Xiaomi -- e.g. the
    20031 ("add your account in Mi Unlock status") or 20036 ("wait 168
    hours") responses documented in docs/error-codes.md.
    """
    service = _service(passtoken)
    zone = zone or get_account_zone(passtoken)
    product = get_device_codename()
    with _as_unlock_error():
        clear = UnlockServer(service, zone).device_clear(product)

    if "error" in clear:
        _log.warning("check: transport error for product=%s zone=%s", product, zone)
        return {"eligible": False, "product": product, "zone": zone, "error": clear["error"]}
    if clear.get("code") != 0:
        _log.info("check: not eligible, code=%s product=%s zone=%s", clear.get("code"), product, zone)
        return {
            "eligible": False, "product": product, "zone": zone,
            "code": clear.get("code"), "description": clear.get("descEN") or redact_response(clear),
        }
    _log.info("check: eligible product=%s zone=%s wipes_data=%s", product, zone, bool(clear.get("cleanOrNot")))
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

    zone, product = eligibility["zone"], eligibility["product"]
    _log.warning("unlock: confirmed by caller, starting for product=%s zone=%s", product, zone)
    with _as_unlock_error():
        server = UnlockServer(service, zone)
        data = server.unlock_data(product, fastboot.get_token())
        try:
            # Sent straight from memory over USB; it is never written to disk.
            fastboot.stage_and_unlock(data)
        except fastboot.FastbootError as err:
            _log.error("unlock: fastboot failed: %s", str(err)[:300])
            raise
    _log.warning("unlock: fastboot reported success for product=%s", product)
    return {"success": True, "product": product}


def list_devices() -> dict:
    """Phones currently connected, found with adb (running Android) and fastboot (bootloader).

    Returns {"android": [{"serial", "state", plus model/codename/android/miui/
    bootloader_locked/battery when the state is "device"}], "fastboot": [serials],
    "fastboot_no_access": [serials found but without driver or permission]}.
    Read-only; it never changes anything on the phone.
    """
    android = []
    with _as_unlock_error():
        for dev in adb.devices():
            if dev["state"] == "device":
                try:
                    dev.update(adb.device_info(dev["serial"]))
                except adb.AdbError as err:
                    dev["error"] = str(err)
            android.append(dev)
        found = fastboot.devices()
    return {"android": android,
            "fastboot": [d["serial"] for d in found if d["accessible"]],
            "fastboot_no_access": [d["serial"] for d in found if not d["accessible"]]}


def reboot_to_fastboot(serial: Optional[str] = None) -> dict:
    """Reboot a phone that is running Android into fastboot mode using adb.

    Needs USB debugging on and the computer authorised on the phone. This only
    restarts the phone; it does not erase anything and does not unlock it.
    """
    with _as_unlock_error():
        adb.reboot_to_bootloader(serial)
    _log.info("rebooted a phone to fastboot through adb")
    return {"success": True}
