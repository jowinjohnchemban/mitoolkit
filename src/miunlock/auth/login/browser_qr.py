import json
import qrcode
from miunlock.auth.config import LONGPOLLING_URL, console, RED, WHITE
from miunlock.auth.browser import open_url
from miunlock.auth.requester import get

def handle_browser_qr(auth_data: dict, choice: str) -> dict:

    auth_data["_json"] = False

    while True:
        try:
            response = get(LONGPOLLING_URL, params=auth_data)
            response_text = json.loads(response.text[11:])
        except Exception as e:
            console.print(f"\n[{RED}]{e}[/]\n")
            return None

        timeout = response_text["timeout"]
        url = response_text["loginUrl"]
        lp = response_text["lp"]

        if choice == "1":
            try:
                open_url(url)
            except ValueError as e:
                console.print(f"\n[{RED}]{e}[/]\n")
                return None
        elif choice == "3":
            qrTips = response_text["qrTips"]
            console.print(f"\n[{WHITE}]{qrTips}[/]\n")
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
            qr.add_data(url)
            qr.print_ascii()

        try:
            response = get(lp, timeout=timeout)
        except ConnectionError as e:
            error = str(e)
            if "timed out" in error:
                console.print(f"\n[{RED}]Request timed out. Please try again.[/]\n")
            elif "Access denied" in error:
                console.print(f"\n[{RED}]Access denied. Please try again.[/]\n")
            else:
                console.print(f"\n[{RED}]{e}[/]\n")
                return None
            continue

        break

    response_text = json.loads(response.text[11:])

    return response_text
