from miunlock import fastboot
from miunlock.utils import _send
from miunlock.system import console, GREEN, ORANGE, RED, WHITE
import random
import hashlib


def unlock_device(domain, service):

    cookies = service["cookies"]
    ssecurity = service['servicedata']["ssecurity"]
    deviceId = service['servicedata']["deviceId"]

    r = "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=16))
    nonce_resp = _send("/api/v2/nonce", {"r": r}, domain, ssecurity, cookies)
    if "error" in nonce_resp:
        console.print(f"\n[{RED}]{nonce_resp['error']}[/]\n")
        return
    if nonce_resp["code"] != 0:
        console.print(f"\n[{RED}]{nonce_resp}[/]\n")
        return
    nonce = nonce_resp["nonce"]

    console.print(f"\n[{GREEN}][[/] [{ORANGE}]Ensure your Xiaomi device is in fastboot mode[/] [{GREEN}]] < [/]\n")

    try:
        product = fastboot.get_product()
    except fastboot.FastbootError as err:
        console.print(f"\n[{RED}]{err}[/]\n")
        return

    console.print(f"\n[{GREEN}]Device Codename: {product}[/]\n")

    clear = _send("/api/v2/unlock/device/clear", {"appId": "1", "data": {"product": product}, "nonce": nonce}, domain, ssecurity, cookies)
    if "error" in clear:
        console.print(f"\n[{RED}]{clear['error']}[/]\n")
        return
    if clear["code"] != 0:
        console.print(f"\n[{RED}]{clear}[/]\n")
        return

    console.print(f"\n[{ORANGE}]notice: {clear['notice']}[/]\n")
    if clear["cleanOrNot"] == 1:
        console.print(f"\n[{RED}]The device will clear user data when unlocked[/]\n")
    else:
        console.print(f"\n[{GREEN}]Unlocking this device will not erase user data[/]\n")

    console.input(f"\n[{WHITE}]Press 'Enter' to continue — unlock(encryptData)[/]")

    try:
        device_token = fastboot.get_token()
    except fastboot.FastbootError as err:
        console.print(f"\n[{RED}]{err}[/]\n")
        return

    data = {
        "clientId": "2",
        "clientVersion": "7.6.727.43",
        "deviceInfo": {"boardVersion": "", "deviceName": "", "product": product, "socId": ""},
        "deviceToken": device_token,
        "language": "en",
        "operate": "unlock",
        "pcId": hashlib.md5(deviceId.encode()).hexdigest(),
        "region": "",
        "uid": cookies.get("userId"),
    }

    # /api/v2/nonce is single-use: the `clear` call above already consumed the
    # nonce we fetched, so reusing it here makes the server answer
    # 10005 "Invalid nonce param". Request a fresh one before unlocking.
    r = "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=16))
    nonce_resp = _send("/api/v2/nonce", {"r": r}, domain, ssecurity, cookies)
    if "error" in nonce_resp:
        console.print(f"\n[{RED}]{nonce_resp['error']}[/]\n")
        return
    if nonce_resp["code"] != 0:
        console.print(f"\n[{RED}]{nonce_resp}[/]\n")
        return
    nonce = nonce_resp["nonce"]

    unlock_result = _send("/api/v3/ahaUnlock", {"appId": "1", "data": data, "nonce": nonce}, domain, ssecurity, cookies)
    if "error" in unlock_result:
        console.print(f"\n[{RED}]{unlock_result['error']}[/]\n")
        return
    if unlock_result["code"] != 0:
        if "descEN" in unlock_result:
            console.print(f"\n[{ORANGE}]code: {unlock_result['code']}\ndescription: {unlock_result['descEN']}[/]\n")
        else:
            console.print(f"\n[{ORANGE}]{unlock_result}[/]\n")
        return

    try:
        fastboot.stage_and_unlock(bytes.fromhex(unlock_result["encryptData"]))
        console.print(f"\n[{GREEN}]Unlock successful[/]\n")
    except fastboot.FastbootError as err:
        console.print(f"\n[{RED}]{err}[/]\n")