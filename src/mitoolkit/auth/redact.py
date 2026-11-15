"""Keep secrets out of anything shown to the user or pasted into a bug report.

Xiaomi's login responses carry session tokens, so error messages must never print
them. These helpers reduce a response to a few harmless status fields.
"""
from __future__ import annotations

from typing import Any

# The only response fields that may be shown. Everything else is listed by name only.
_SAFE_KEYS = ("code", "result", "desc", "description", "descEN", "tips", "message", "msg")


def redact_response(data: Any) -> str:
    """Summarise a server response: show status fields, hide every other value."""
    if not isinstance(data, dict):
        return f"<{type(data).__name__} response, contents hidden>"
    shown = {
        key: data[key]
        for key in _SAFE_KEYS
        if key in data and isinstance(data[key], (int, str)) and len(str(data[key])) <= 200
    }
    hidden = sorted(str(key) for key in data if key not in shown)
    return f"{shown} (values of these fields are hidden: {', '.join(hidden) or 'none'})"


def mask_id(value: Any) -> str:
    """Shorten an account ID for display: 1234567890 -> 123***890."""
    text = str(value)
    if len(text) <= 6:
        return "*" * len(text)
    return f"{text[:3]}***{text[-3:]}"
