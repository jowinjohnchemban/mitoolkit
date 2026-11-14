from miunlock.utils import _send
from miunlock.commands import get_device_token, get_product
from miunlock.system import console, GREEN, ORANGE, RED, WHITE, NO_WINDOW
import random
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

def unlock_device(domain, service, fastboot_cmd):

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

    product = get_product(fastboot_cmd)
    if isinstance(product, dict) and "error" in product:
        console.print(f"\n[{RED}]{product['error']}[/]\n")
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

    device_token = get_device_token(fastboot_cmd)
    if isinstance(device_token, dict) and "error" in device_token:
        console.print(f"\n[{RED}]{device_token['error']}[/]\n")
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

    encryptData = unlock_result["encryptData"]
    # A private (owner-only), unpredictably named file, deleted as soon as fastboot is done.
    fd, name = tempfile.mkstemp(prefix="miunlock-", suffix=".encryptData")
    filename = Path(name)
    with os.fdopen(fd, "wb") as edfile:
        edfile.write(bytes.fromhex(encryptData))

    try:
        subprocess.run([fastboot_cmd, "stage", str(filename)], check=True, capture_output=True, text=True, creationflags=NO_WINDOW)
        subprocess.run([fastboot_cmd, "oem", "unlock"], check=True, capture_output=True, text=True, creationflags=NO_WINDOW)
        console.print(f"\n[{GREEN}]Unlock successful[/]\n")
    except subprocess.CalledProcessError as e:
        console.print(f"\n[{RED}]{e.stderr}[/]\n")
    finally:
        if filename.exists():
            filename.unlink()