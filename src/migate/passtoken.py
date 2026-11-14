import json
import os
import platform
import stat
from pathlib import Path

# SANITIZED BUILD: the password-based terminal login path (migate.login.terminal,
# plus its verify.py/sendcode.py/verifycode.py 2FA helpers) has been deleted
# from this fork entirely, not just unused. It computed an unsalted MD5 of the
# account password and posted it to Xiaomi's login API -- password-equivalent
# if ever leaked. This build only offers browser/QR login, where the password
# is entered on Xiaomi's own login page and never touches this code at all.
from migate.login.browser_qr import handle_browser_qr
from migate.config import SERVICELOGIN_URL, console, GREEN, WHITE, ORANGE, RED, DIM
from migate.requester import session, get


def _lock_down(path: Path):
    """Best-effort: restrict the session file to the current user only."""
    try:
        if platform.system() == "Windows":
            import subprocess
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r",
                 f"{os.environ.get('USERNAME', '')}:F"],
                capture_output=True, text=True, check=False,
            )
        else:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass  # locking down is defense-in-depth, never block on it


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
    cookies_file = Path.home() / ".migatesession" / f"{sid}" / "session.json"

    if cookies_file.exists():
        try:
            with open(cookies_file, "r") as f:
                passToken = json.load(f)
        except (json.JSONDecodeError, OSError):
            cookies_file.unlink(missing_ok=True)
            console.print("Session corrupted, please log in again.\n", style=RED)
            passToken = None

        if passToken is not None:

            if silent:
                return passToken

            choice = console.input(
                f"\n[{GREEN}]Already logged in[/][{WHITE}]\nAccount ID: [/][{ORANGE}]{passToken['userId']}[/]\n\n"
                f"[{WHITE}](Enter to continue, [{RED}]2[/] To log out) > [/]"
            ).strip().lower()

            if choice == "2":
                cookies_file.unlink(missing_ok=True)
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
        console.print(f"\n[{RED}]Missing keys: {', '.join(missing)} | Response: {response_text}[/]\n")
        return None

    passToken = {k: cookies[k] for k in required}

    cookies_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cookies_file, "w") as f:
        json.dump(passToken, f)
    _lock_down(cookies_file)

    console.print("\nLogin successful", style=GREEN)
    console.print(
        f"[{DIM}]Session saved to {cookies_file} (access restricted to your user account). "
        f"Delete this file when you're done to end the saved session.[/]"
    )
    session.cookies.clear()

    return passToken
