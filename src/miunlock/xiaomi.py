"""
Xiaomi's unlock server: the request sequence shared by the interactive flow (unlock.py)
and the API (api.py), so it lives in one place.

    server = UnlockServer(service, zone)
    reply = server.device_clear(product)                 # eligibility; read-only
    data = server.unlock_data(product, device_token)     # signed encryptData for the phone

Each request takes a fresh nonce, because Xiaomi's nonces are single use (reusing one gives
10005 "Invalid nonce param").
"""
from __future__ import annotations

import hashlib
import random
import string
from typing import Optional

from miunlock.auth.redact import redact_response
from miunlock.errors import UnlockError
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
REGION_TO_ZONE = {"CN": "China", "IN": "India", "RU": "Russia", **{c: "Europe" for c in _EUROPE_CODES}}
DEFAULT_ZONE = "Singapore"


def zone_for_region(region: Optional[str]) -> str:
    """Data center zone for an account region code (e.g. "IN" -> "India")."""
    return REGION_TO_ZONE.get(region or "", DEFAULT_ZONE)


class ServerError(UnlockError):
    """Xiaomi refused a request. code/description are Xiaomi's, when it gave them."""

    def __init__(self, message: str, code: Optional[int] = None, description: Optional[str] = None):
        super().__init__(message)
        self.code, self.description = code, description


class UnlockServer:
    """One signed-in session with the unlock server of one data center zone."""

    CLIENT_ID = "2"
    CLIENT_VERSION = "7.6.727.43"

    def __init__(self, service: dict, zone: str):
        if zone not in DOMAIN_BY_ZONE:
            raise UnlockError(f"Unknown data center zone: {zone}")
        self.zone = zone
        self.domain = DOMAIN_BY_ZONE[zone]
        self.ssecurity = service["servicedata"]["ssecurity"]
        self.device_id = service["servicedata"]["deviceId"]
        self.cookies = service["cookies"]

    def _post(self, path: str, params: dict) -> dict:
        return _send(path, params, self.domain, self.ssecurity, self.cookies)

    def nonce(self) -> str:
        r = "".join(random.choices(string.ascii_lowercase, k=16))
        reply = self._post("/api/v2/nonce", {"r": r})
        if "error" in reply or reply.get("code") != 0:
            raise ServerError(str(reply.get("error") or redact_response(reply)))
        return reply["nonce"]

    def device_clear(self, product: str) -> dict:
        """Ask whether this phone can be unlocked now. Read-only. Returns Xiaomi's reply as
        is: code 0 means eligible (with cleanOrNot and notice); an "error" key means the
        request itself failed."""
        return self._post("/api/v2/unlock/device/clear",
                          {"appId": "1", "data": {"product": product}, "nonce": self.nonce()})

    def unlock_data(self, product: str, device_token: str) -> bytes:
        """Xiaomi's signed unlock data (encryptData) for this phone's token."""
        data = {
            "clientId": self.CLIENT_ID,
            "clientVersion": self.CLIENT_VERSION,
            "deviceInfo": {"boardVersion": "", "deviceName": "", "product": product, "socId": ""},
            "deviceToken": device_token,
            "language": "en",
            "operate": "unlock",
            "pcId": hashlib.md5(self.device_id.encode()).hexdigest(),
            "region": "",
            "uid": self.cookies.get("userId"),
        }
        reply = self._post("/api/v3/ahaUnlock", {"appId": "1", "data": data, "nonce": self.nonce()})
        if "error" in reply:
            raise ServerError(str(reply["error"]))
        if reply.get("code") != 0:
            desc = reply.get("descEN")
            raise ServerError(str(desc or redact_response(reply)), reply.get("code"), desc)
        return bytes.fromhex(reply["encryptData"])
