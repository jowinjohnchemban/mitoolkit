"""Error types shared across mitoolkit. Every error raised on purpose derives from
MitoolkitError and has a human-readable message, so callers (CLI, GUI, MCP) can catch one
type and show str(e) as is."""


class MitoolkitError(Exception):
    """Base for every expected failure. str(e) is meant for people."""


class UnlockError(MitoolkitError):
    """A step of the account, server or unlock flow was rejected or failed."""
