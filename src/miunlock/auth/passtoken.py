import json
import os
import platform
import stat
import subprocess
from pathlib import Path

# SANITIZED BUILD: the password-based terminal login path (miunlock.auth.login.terminal,
# plus its verify.py/sendcode.py/verifycode.py 2FA helpers) has been deleted
# from this fork entirely, not just unused. It computed an unsalted MD5 of the
# account password and posted it to Xiaomi's login API -- password-equivalent
# if ever leaked. This build only offers browser/QR login, where the password
# is entered on Xiaomi's own login page and never touches this code at all.
from miunlock.auth.login.browser_qr import handle_browser_qr
from miunlock.auth.config import SERVICELOGIN_URL, console, GREEN, WHITE, ORANGE, RED, DIM
from miunlock.auth.requester import session, get
from miunlock.auth.redact import redact_response


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _restrict_to_current_user(path: Path) -> bool:
    """Limit a file or folder to the current user. True only if it was applied."""
    try:
        if platform.system() == "Windows":
            user = os.environ.get("USERNAME")
            if not user:
                return False
            grant = f"{user}:(OI)(CI)F" if path.is_dir() else f"{user}:F"
            result = subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", grant],
                capture_output=True, text=True, check=False, creationflags=_NO_WINDOW,
            )
            return result.returncode == 0
        os.chmod(path, stat.S_IRWXU if path.is_dir() else stat.S_IRUSR | stat.S_IWUSR)
        return True
    except Exception:
        return False


def _write_session(path: Path, data: dict) -> bool:
    """Save the session so it is never readable by other users, not even briefly.

    The folder is restricted first, and on POSIX the file is created with mode 0600
    from the start instead of being tightened after it was written. Returns whether
    the restrictions could be applied, so the caller never claims protection it
    does not have.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = _restrict_to_current_user(path.parent)
    text = json.dumps(data)
    if os.name == "nt":
        path.write_text(text, encoding="utf-8")
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
    return _restrict_to_current_user(path) and safe


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
    cookies_file = Path.home() / ".miunlocksession" / f"{sid}" / "session.json"

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
        console.print(f"\n[{RED}]Missing keys: {', '.join(missing)} | Response: {redact_response(response_text)}[/]\n")
        return None

    passToken = {k: cookies[k] for k in required}

    protected = _write_session(cookies_file, passToken)

    console.print("\nLogin successful", style=GREEN)
    if protected:
        console.print(
            f"[{DIM}]Session saved to {cookies_file} (access restricted to your user account). "
            f"Delete it when you're done to end the saved session.[/]"
        )
    else:
        console.print(
            f"[{ORANGE}]Session saved to {cookies_file}, but its permissions could not be restricted "
            f"to your user account. Delete it as soon as you're done.[/]"
        )
    session.cookies.clear()

    return passToken
