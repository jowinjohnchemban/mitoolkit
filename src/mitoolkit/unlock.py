"""
The interactive command-line unlock (``mitoolkit --cli``): the same steps as api.py, with
prompts in between. The requests to Xiaomi are shared through xiaomi.UnlockServer.
"""
from __future__ import annotations

from typing import Optional

from mitoolkit import fastboot
from mitoolkit.auth import get_dataCenterZone, get_passtoken, get_region, get_service
from mitoolkit.auth.redact import redact_response
from mitoolkit.auth.config import GREEN, ORANGE, RED, WHITE, console
from mitoolkit.xiaomi import ServerError, UnlockServer, zone_for_region


class InteractiveUnlock:
    """Sign in, choose the data center, check the phone, confirm, unlock."""

    PARAM = {"sid": "unlockApi", "checkSafeAddress": True}

    def say(self, text: str, colour: str = WHITE) -> None:
        console.print(f"\n[{colour}]{text}[/]\n")

    def ask(self, prompt: str) -> str:
        return console.input(f"\n[{WHITE}]{prompt}[/]").strip().lower()

    # -------------------------------------------------------------- steps
    def sign_in(self) -> Optional[tuple]:
        """(passToken, service) or None."""
        pass_token = get_passtoken(dict(self.PARAM))
        if pass_token is None:
            return None
        service = get_service(pass_token, dict(self.PARAM))
        if service is None:
            return None
        return pass_token, service

    def choose_zone(self, pass_token: dict) -> str:
        region = get_region(pass_token)
        if region is None:
            zone = get_dataCenterZone(pass_token["userId"])
        else:
            console.print(f"\n[{GREEN}]Account Region: {region}[/]")
            zone = zone_for_region(region)
        if zone is None:
            return get_dataCenterZone()
        console.print(f"\n[{GREEN}]dataCenterZone: {zone}[/]")
        if self.ask(f"(Enter to continue, [{ORANGE}]m[/] to change dataCenterZone) > ") == "m":
            zone = get_dataCenterZone()
        return zone

    def unlock(self, server: UnlockServer) -> bool:
        self.say(f"[{GREEN}][[/] [{ORANGE}]Ensure your Xiaomi device is in fastboot mode[/] [{GREEN}]] <[/]", GREEN)
        try:
            product = fastboot.get_product()
            self.say(f"Device Codename: {product}", GREEN)
            clear = server.device_clear(product)
        except (fastboot.FastbootError, ServerError) as err:
            self.say(str(err), RED)
            return False
        if "error" in clear:
            self.say(clear["error"], RED)
            return False
        if clear.get("code") != 0:
            self.say(f"code: {clear.get('code')}\ndescription: {clear.get('descEN') or redact_response(clear)}", ORANGE)
            return False

        self.say(f"notice: {clear.get('notice')}", ORANGE)
        if clear.get("cleanOrNot") == 1:
            self.say("The device will clear user data when unlocked", RED)
        else:
            self.say("Unlocking this device will not erase user data", GREEN)
        self.ask("Press 'Enter' to continue — unlock(encryptData)")

        try:
            data = server.unlock_data(product, fastboot.get_token())
            fastboot.stage_and_unlock(data)
        except ServerError as err:
            text = f"code: {err.code}\ndescription: {err.description}" if err.code is not None else str(err)
            self.say(text, ORANGE)
            return False
        except fastboot.FastbootError as err:
            self.say(str(err), RED)
            return False
        self.say("Unlock successful", GREEN)
        return True

    # ---------------------------------------------------------------- run
    def run(self) -> None:
        try:
            fastboot.ready()
        except fastboot.FastbootError as err:
            self.say(str(err), RED)
            raise SystemExit(1)
        signed_in = self.sign_in()
        if signed_in is None:
            raise SystemExit(1)
        pass_token, service = signed_in
        zone = self.choose_zone(pass_token)
        self.unlock(UnlockServer(service, zone))
