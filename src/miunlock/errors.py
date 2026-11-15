"""Error types shared across miunlock. Every error raised on purpose derives from
MiunlockError and has a human-readable message, so callers (CLI, GUI, MCP) can catch one
type and show str(e) as is."""


class MiunlockError(Exception):
    """Base for every expected failure. str(e) is meant for people."""


class UnlockError(MiunlockError):
    """A step of the account, server or unlock flow was rejected or failed."""
