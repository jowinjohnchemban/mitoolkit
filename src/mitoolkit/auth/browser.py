"""Open a URL in the user's browser without ever building a shell command."""
from __future__ import annotations

import platform
import subprocess
import webbrowser
from urllib.parse import urlparse


def open_url(url: str) -> None:
    """Open ``url`` in the default browser.

    Only https URLs, or http to this machine (the local captcha page), are opened.
    The URL is passed as a single argument and never through a shell, so a crafted
    URL cannot run commands.
    """
    parts = urlparse(url)
    local = parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")
    if parts.scheme != "https" and not local:
        raise ValueError("Refusing to open a URL that is not https")

    if platform.system() in ("Linux", "Android"):
        subprocess.run(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        webbrowser.open(url)
