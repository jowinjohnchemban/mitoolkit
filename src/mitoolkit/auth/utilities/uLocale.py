import json
from mitoolkit.auth.config import CONFIG_URL, console, RED
from mitoolkit.auth.requester import session, get
from mitoolkit.auth.redact import redact_response

def get_uLocale():

    try:
        params = {'key': 'uLocale'}
        response = get(CONFIG_URL, params=params)
        response_text = json.loads(response.text[11:])
    except Exception as e:
        console.print(f"\n[{RED}]{e}[/]\n")
        return None
    finally:
        session.cookies.clear()

    uLocale = response_text.get("uLocale")

    if not uLocale:
        console.print(f"\n[{RED}]Failed to get uLocale | Response: {redact_response(response_text)}[/]\n")
        return None

    return uLocale
