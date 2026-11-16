"""Let an AI agent control mitoolkit directly: ``mitoolkit --mcp``.

This speaks the Model Context Protocol over stdin/stdout (newline-delimited
JSON-RPC 2.0), so an agent such as Claude can call the tools below and read
their JSON results without screen scraping. No extra package is needed.

What an agent can do: list phones, reboot one into fastboot, sign in with a saved
session, check eligibility, and read the log. What it cannot do: unlock. Unlocking
erases the phone and must be a person's decision, made in the GUI or with
``mitoolkit --cli unlock --confirm-wipe``. That is deliberate, see docs/safety.md.
"""
import json
import re
import sys
from typing import Any, Dict

from mitoolkit import __version__, api, log

PROTOCOL = "2024-11-05"
SUPPORTED = ("2025-06-18", "2025-03-26", PROTOCOL)       # versions of the protocol this server can speak
_SCHEMA_NONE = {"type": "object", "properties": {}}


def _public(data: dict) -> dict:
    """Drop internal entries (they carry session tokens) before anything leaves the process."""
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _t_devices(_args: dict) -> dict:
    return api.list_devices()


def _t_reboot(args: dict) -> dict:
    return api.reboot_to_fastboot(args.get("serial"))


def _t_login(_args: dict) -> dict:
    """Uses the saved session. If there is none, a person must finish signing in in the
    browser window that opens; this call waits for them."""
    token = api.login(silent_if_cached=True)
    return {"logged_in": True, "zone": api.get_account_zone(token)}


def _t_check(_args: dict) -> dict:
    if not api.list_devices()["fastboot"]:  # otherwise the library would wait forever
        return {"eligible": None, "error": "No phone in fastboot mode. Use reboot_to_fastboot, "
                                           "or ask the person to put the phone in fastboot mode."}
    token = api.login(silent_if_cached=True)
    return _public(api.check_unlock_eligibility(token))


def _t_security(args: dict) -> dict:
    from mitoolkit import security
    return security.run(args.get("serial")).to_dict()


def _t_details(args: dict) -> dict:
    """Device details for an agent: everything except what identifies the phone or its owner
    (serial number, IMEI, Android ID, Wi-Fi and Bluetooth addresses)."""
    from mitoolkit import adb
    return {"sections": [{"title": title, "rows": _anonymous(rows)}
                         for title, rows in adb.more_details(args.get("serial")) if title != "Identity"]}


_IDENTIFYING_LABEL = re.compile(r"address|serial|imei|meid|android id|\bid\b", re.I)
_ADDRESS_IN_TEXT = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")


def _anonymous(rows) -> list:
    """The rows of one section without what names the phone or its network: rows that are an address, serial or ID are
    left out (whatever section they sit in), and an IP or MAC address inside any other value is replaced."""
    out = []
    for label, value in rows:
        if _IDENTIFYING_LABEL.search(str(label)):
            continue
        out.append({"label": label, "value": _ADDRESS_IN_TEXT.sub("(hidden)", value) if isinstance(value, str) else value})
    return out


def _t_connections(args: dict) -> dict:
    """Wi-Fi, mobile network, SIM, Bluetooth and USB state with findings. Network and device names and
    addresses are hidden; the state, signal and findings are what an agent needs."""
    from mitoolkit import adb, diagnostics
    return diagnostics.redact(diagnostics.run(adb.Phone(args.get("serial"))))


def _t_doctor(_args: dict) -> dict:
    """What is wrong with the setup, read-only: agents get the diagnosis, a person decides about fixes."""
    from mitoolkit import doctor
    checks = doctor.run(phone=False)
    return {"problems": len(doctor.problems(checks)), "checks": [c.to_dict() for c in checks]}


def _t_log(args: dict) -> dict:
    path = log.log_path()
    if path is None or not path.exists():
        return {"lines": [], "note": "No log file."}
    n = max(1, min(int(args.get("lines", 50)), 500))
    return {"path": str(path), "lines": path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]}


def _t_version(_args: dict) -> dict:
    return {"version": __version__, "can_unlock": False,
            "unlock_note": "Unlocking erases the phone and must be done by a person: GUI, or "
                           "`mitoolkit --cli unlock --confirm-wipe`."}


TOOLS: Dict[str, tuple] = {
    "version": ("Version, and a reminder that unlocking is not available to agents.", _SCHEMA_NONE, _t_version),
    "list_devices": ("Phones seen by adb (running Android; with model, codename, MIUI version, "
                     "bootloader lock state) and by fastboot. Read-only.", _SCHEMA_NONE, _t_devices),
    "reboot_to_fastboot": ("Reboot a phone running Android into fastboot mode with adb. Erases nothing.",
                           {"type": "object", "properties": {"serial": {"type": "string"}}}, _t_reboot),
    "login": ("Use the saved Mi Account session; if none, a person must sign in in the browser.",
              _SCHEMA_NONE, _t_login),
    "check_eligibility": ("Ask Xiaomi whether the connected fastboot phone can be unlocked now. "
                          "Read-only: returns eligible, product, zone, will_wipe_data, notice, or "
                          "Xiaomi's code and description (for example 20036 = wait 168 hours).",
                          _SCHEMA_NONE, _t_check),
    "security_check": ("Read-only security check of a phone running Android: security patch vs. Android "
                       "security bulletins (OSV), Play Protect, where apps came from, apps with powerful "
                       "access, known stalkerware. Changes nothing.",
                       {"type": "object", "properties": {"serial": {"type": "string"}}}, _t_security),
    "device_details": ("Everything a phone running Android reports over USB, in sections (hardware, modem, SIM, "
                       "boot, servicing, partitions, sensors). Read-only. Serial number, IMEI and addresses are "
                       "left out.", {"type": "object", "properties": {"serial": {"type": "string"}}}, _t_details),
    "connections": ("Read-only state of Wi-Fi, the mobile network (modem), SIM, Bluetooth and USB of a phone "
                    "running Android, with findings that say what looks wrong. Network names and addresses are "
                    "hidden.", {"type": "object", "properties": {"serial": {"type": "string"}}}, _t_connections),
    "doctor": ("Read-only check of the setup (Python, USB access, adb key, saved session, settings, log) with "
               "what is wrong and how to fix it. Fixes are not offered to agents: a person runs `mitoolkit "
               "doctor --fix`.", _SCHEMA_NONE, _t_doctor),
    "read_log": ("Last lines of mitoolkit.log (tokens are scrubbed).",
                 {"type": "object", "properties": {"lines": {"type": "integer"}}}, _t_log),
}


def _call(name: str, args: dict) -> dict:
    if name not in TOOLS:
        raise KeyError(name)
    try:
        return {"content": [{"type": "text", "text": json.dumps(TOOLS[name][2](args), indent=2, default=str)}]}
    except api.UnlockError as err:
        return {"isError": True, "content": [{"type": "text", "text": json.dumps({"error": str(err)})}]}
    except Exception as err:  # keep the server alive; never leak a traceback with data in it
        safe_name = name.replace("\r", "").replace("\n", "")  # name is a known tool, but never trust a log line
        log.get("mcp").error("tool %s failed: %s", safe_name, type(err).__name__)
        return {"isError": True, "content": [{"type": "text", "text": json.dumps({"error": type(err).__name__})}]}


def handle(msg: dict) -> Any:
    """Return the JSON-RPC response for one request, or None for a notification."""
    method, ident = msg.get("method"), msg.get("id")
    if ident is None:
        return None
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion") if isinstance(msg.get("params"), dict) else None
        result: Any = {"protocolVersion": asked if asked in SUPPORTED else PROTOCOL, "capabilities": {"tools": {}},
                       "serverInfo": {"name": "mitoolkit", "version": __version__}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s, _f) in TOOLS.items()]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        try:
            result = _call(params.get("name", ""), params.get("arguments") or {})
        except KeyError:
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "Unknown tool"}}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve() -> None:
    """Run until stdin closes. stdout carries only protocol; library output goes to stderr."""
    out = sys.stdout
    sys.stdout = sys.stderr
    log.get("mcp").info("MCP server started")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if reply is not None:
            out.write(json.dumps(reply) + "\n")
            out.flush()
