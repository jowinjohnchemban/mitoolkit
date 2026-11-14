import json

# SANITIZED BUILD: the password-based terminal login path (miunlock.auth.login.terminal,
# plus its verify.py/sendcode.py/verifycode.py 2FA helpers) has been deleted
# from this fork entirely, not just unused. It computed an unsalted MD5 of the
# account password and posted it to Xiaomi's login API -- password-equivalent
# if ever leaked. This build only offers browser/QR login, where the password
# is entered on Xiaomi's own login page and never touches this code at all.
from miunlock.auth.login.browser_qr import handle_browser_qr
from miunlock.auth.config import SERVICELOGIN_URL, console, GREEN, WHITE, ORANGE, RED, DIM
from miunlock.auth.requester import session, get
from miunlock.auth import store
from miunlock.auth.redact import mask_id, redact_response


def get_passtoken(auth_data=None, silent=False, login_method=None):
    """
    login_method: None (default) keeps the original interactive prompt.
    Pass "1" (browser) or "3" (QR) to skip that prompt for programmatic/
    non-interactive use. Note this only skips *choosing* the method --
    the actual login still happens on Xiaomi's real page or via a scanned
    QR code, so it still requires a human to complete it there. There is
    and will not be a fully unattended login path; the password never
    passes through this code either way (see the sanitization note above).
    """
    if auth_data is None:
        auth_data = {"sid": "passport"}

    sid = auth_data["sid"]
    passToken = store.load(sid)

    if passToken is not None:
        if silent:
            return passToken

        choice = console.input(
            f"\n[{GREEN}]Already logged in[/][{WHITE}]\nAccount ID: [/][{ORANGE}]{mask_id(passToken['userId'])}[/]\n\n"
            f"[{WHITE}](Enter to continue, [{RED}]2[/] To log out) > [/]"
        ).strip().lower()

        if choice == "2":
            store.delete(sid)
            console.print("Logged out.", style=RED)
        else:
            return passToken

    auth_data["_json"] = True

    try:
        response = get(SERVICELOGIN_URL, params=auth_data)
        response_text = json.loads(response.text[11:])
    except Exception as e:
        console.print(f"\n[{RED}]{e}[/]\n")
        return None

    auth_data["serviceParam"] = response_text["serviceParam"]
    auth_data["qs"] = response_text["qs"]
    auth_data["callback"] = response_text["callback"]
    auth_data["_sign"] = response_text["_sign"]

    if login_method in ("1", "3"):
        choice = login_method
    else:
        console.print("\n[bold]How would you like to log in?[/]")
        console.print(f"\n  [{ORANGE}]1[/] - Browser [{DIM}](default)[/]")
        console.print(f"  [{ORANGE}]3[/] - QR code\n")
        console.print(f"  [{DIM}](Terminal/password login is disabled in this sanitized build.)[/]\n")

        choice = console.input(f"[{WHITE}]Choose > [/]").strip()
        if choice not in ("1", "3"):
            choice = "1"

    response_text = handle_browser_qr(auth_data, choice)

    cookies  = session.cookies.get_dict()
    required = {"deviceId", "passToken", "userId"}
    missing  = required - cookies.keys()
    if missing:
        console.print(f"\n[{RED}]Missing keys: {', '.join(missing)} | Response: {redact_response(response_text)}[/]\n")
        return None

    passToken = {k: cookies[k] for k in required}

    where = store.save(sid, passToken)

    console.print("\nLogin successful", style=GREEN)
    if where in (store.KEYRING, store.DPAPI):
        console.print(f"[{DIM}]Session saved ({where}). Choose log out to remove it.[/]")
    elif where == store.FILE:
        console.print(
            f"[{DIM}]Session saved in {store.ROOT} (readable only by your user account, but not "
            f"encrypted). Delete it when you're done.[/]"
        )
    else:
        console.print(
            f"[{ORANGE}]Session saved in {store.ROOT}, NOT encrypted and its permissions could not be "
            f"restricted. Delete it as soon as you're done.[/]"
        )
    session.cookies.clear()

    return passToken
