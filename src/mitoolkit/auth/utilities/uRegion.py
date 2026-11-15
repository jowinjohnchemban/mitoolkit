import json
from mitoolkit.auth.config import CONFIG_URL, console, RED
from mitoolkit.auth.requester import get
from mitoolkit.auth.redact import redact_response

def get_uRegion():

    try:
        params = {'key': 'uRegion'}
        response = get(CONFIG_URL, params=params)
        response_text = json.loads(response.text[11:])
    except Exception as e:
        console.print(f"\n[{RED}]{e}[/]\n")
        return None

    uRegion = response_text.get("uRegion")

    if not uRegion:
        console.print(f"\n[{RED}]Failed to get uRegion | Response: {redact_response(response_text)}[/]\n")
        return None

    return uRegion
