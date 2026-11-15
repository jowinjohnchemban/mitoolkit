"""Plain-language explanations for responses from Xiaomi's unlock servers.

The causes and fixes mirror docs/error-codes.md. Xiaomi's own wording is kept
alongside so nothing is hidden; this only adds a readable title and a next step.
"""
from __future__ import annotations

import re
import time
from typing import NamedTuple, Optional


class Hint(NamedTuple):
    title: str
    advice: str
    # "wait" for situations that fix themselves with time, "error" otherwise.
    kind: str = "error"


_NOT_ADDED = Hint(
    "Your account isn't added on the phone yet",
    "On the phone open Settings > Additional settings > Developer options > "
    "Mi Unlock status > Add account and device, then check again. If you already "
    "did and still see this, the wrong data center may have been chosen.",
)

_HINTS = {
    10000: Hint("Xiaomi rejected the request", "Close and reopen the program and make sure it is up to date."),
    10013: Hint(
        "The phone isn't activated, or was activated too recently",
        "Use a SIM with mobile data, turn Find device off and on, and make sure the account "
        "is added in Mi Unlock status. If the message gives a number of hours, wait that long.",
    ),
    10023: Hint(
        "This account has already unlocked a device",
        "Xiaomi allows one device per account per year. Use a different Mi Account or wait.",
    ),
    20030: Hint(
        "Monthly limit reached",
        "A token was already requested this month. Try again from the 1st of next month.",
        "wait",
    ),
    20031: _NOT_ADDED,
    30002: _NOT_ADDED,
    20033: Hint(
        "This account is restricted by Xiaomi",
        "Try turning on Find device on the phone. If that doesn't help, use a different Mi Account.",
    ),
    20035: Hint("Xiaomi says this program is outdated", "Update MiToolkit to the latest version."),
    20036: Hint(
        "Xiaomi's waiting period is still running",
        "This is normal. Do not add the account on the phone again, because that restarts the wait. "
        "Check again once the time has passed.",
        "wait",
    ),
    20038: Hint(
        "The phone is locked by Find device",
        "Sign in at i.mi.com/mobile/find with the account that locked it and turn off Locate device.",
    ),
    20039: Hint(
        "Xiaomi couldn't verify the device data",
        "There is no confirmed fix for this one. See the error codes page for details.",
    ),
    20041: Hint(
        "No phone number on this Mi Account",
        "Add a phone number to the account, then try again.",
    ),
    20045: Hint(
        "Account and phone regions don't match",
        "Use a Mi Account from the same region as the phone, or choose a different data center.",
    ),
}


def explain(code: Optional[int], description: Optional[str] = None) -> Hint:
    """Return a readable Hint for a Xiaomi response code.

    For the waiting-period code the number of hours Xiaomi reports, if any, is added.
    Unknown codes fall back to Xiaomi's own description.
    """
    hint = _HINTS.get(code) if code is not None else None
    if hint is None:
        text = description or "Xiaomi declined the request without giving a reason."
        return Hint("Xiaomi declined the request", text)

    if code == 20036 and description:
        m = re.search(r"(\d+)\s*hours?", description)
        if m:
            hours = int(m.group(1))
            days = hours / 24
            span = f"about {hours} hours ({days:.1f} days)" if hours >= 48 else f"about {hours} hours"
            when = time.strftime("%a %d %b, %H:%M", time.localtime(time.time() + hours * 3600))
            return Hint(hint.title, f"Xiaomi says to wait {span}, so try again after {when} (your time). "
                        + hint.advice, hint.kind)
    return hint
