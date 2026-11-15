"""MCP inside the running app: let an AI agent work with the MiToolkit that is already connected to the phone.

``mitoolkit --mcp`` starts a separate program that talks over stdin and stdout. This is the other way round: the
window the person is using offers the same tools (see mcp.py) over a local HTTP address, so an agent can use the
app that has the phone, the saved session and the open windows. It is off until the person turns it on (Help > AI
agent connection) and it stops when they turn it off or close the app.

Safety, in the order a request meets it:

* It listens on 127.0.0.1 only, so nothing else on the network can reach it, on a port the system picks.
* Every request needs the secret token of this run (a different one each time it is switched on), sent as
  ``Authorization: Bearer <token>``. A web page in a browser cannot send it, and a request that names another
  site in ``Origin`` or ``Host`` is refused (the DNS rebinding trick).
* The tools are the stdio server's: read and check, never unlock. Those that change something on the phone or use
  the saved session (``approval`` below) first ask the person in the app and wait for their answer.
* One tool runs at a time (a phone takes one conversation at a time), a request over 1 MB is refused, and the
  token is never logged. The log and the Activity log say which tool was called, never its answer.
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from mitoolkit import log, mcp

PATH = "/mcp"
MAX_BODY = 1_000_000
HOST = "127.0.0.1"
# Tools that change something on the phone or use the person's account: the person is asked first, each time.
APPROVAL: Dict[str, str] = {
    "reboot_to_fastboot": "restart the phone into fastboot mode (nothing is erased)",
    "login": "use your saved Mi Account session, or open the sign-in page if there is none",
}

Approve = Callable[[str, dict], bool]
OnCall = Callable[[str], None]
OnClient = Callable[[str], None]


def client_name(params: Any) -> str:
    """The name an agent gives itself when it connects (``clientInfo.name`` of the initialize request), made fit to
    show: "claude-code" becomes "Claude Code". Empty when it gave none. Only printable text, 40 characters at most."""
    info = params.get("clientInfo") if isinstance(params, dict) else None
    raw = str(info.get("name", "")) if isinstance(info, dict) else ""
    text = "".join(ch for ch in raw if ch.isprintable()).strip()[:40]
    if text and text == text.lower() and any(sep in text for sep in "-_"):
        text = text.replace("-", " ").replace("_", " ").title()
    return text
_running: List["McpHttpServer"] = []         # the servers that are on, so closing the app can stop them


def stop_all() -> str:
    """Stop every server that is on (the app is closing). Says what it did, or nothing."""
    servers = list(_running)
    for server in servers:
        server.stop()
    return "Stopped the AI agent connection." if servers else ""


def _declined() -> dict:
    return {"isError": True, "content": [{"type": "text", "text": json.dumps(
        {"error": "A person declined this in the MiToolkit window, or did not answer in time."})}]}


class McpHttpServer:
    def __init__(self, approve: Optional[Approve] = None, on_call: Optional[OnCall] = None, port: int = 0,
                 on_client: Optional[OnClient] = None):
        """``approve(tool, arguments)`` is asked for the tools in APPROVAL and must answer True to let one run (no
        ``approve`` means none of them run). ``on_call(tool)`` hears about every call, ``on_client(name)`` about an agent
        saying who it is when it connects. ``port`` 0 lets the system pick."""
        self.token = secrets.token_urlsafe(32)
        self.client = ""                      # the name the last agent that connected gave itself
        self._approve, self._on_call, self._on_client = approve, on_call, on_client
        self._lock = threading.Lock()
        self._httpd = ThreadingHTTPServer((HOST, port), self._handler())
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="mcp-http")

    # ---------------------------------------------------------------------------------------- lifecycle
    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}{PATH}"

    def start(self) -> "McpHttpServer":
        self._thread.start()
        _running.append(self)
        log.get("mcp").info("MCP server for agents started on port %s", self.port)
        return self

    def stop(self) -> None:
        if self in _running:
            _running.remove(self)
        try:
            self._httpd.shutdown()
        finally:
            self._httpd.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=3)
        log.get("mcp").info("MCP server for agents stopped")

    # ----------------------------------------------------------------------------------------- settings to copy
    def claude_code_command(self) -> str:
        """The command that adds this server to Claude Code."""
        return (f'claude mcp add --transport http mitoolkit {self.url} '
                f'--header "Authorization: Bearer {self.token}"')

    def json_settings(self) -> str:
        """The same as the JSON that MCP clients read (for example Claude Desktop through mcp-remote, or Cursor)."""
        return json.dumps({"mcpServers": {"mitoolkit": {
            "type": "http", "url": self.url, "headers": {"Authorization": f"Bearer {self.token}"}}}}, indent=2)

    # ------------------------------------------------------------------------------------------- one request
    def dispatch(self, msg: Any) -> Any:
        """The reply to one JSON-RPC message (None for a notification)."""
        if not isinstance(msg, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        if msg.get("method") == "initialize":
            self.client = client_name(msg.get("params")) or self.client
            if self._on_client is not None:
                self._on_client(self.client)
        if msg.get("method") == "tools/call":
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
            name = str(params.get("name", ""))
            if self._on_call is not None:
                self._on_call(name)
            if name in APPROVAL and msg.get("id") is not None:
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                allowed = self._approve is not None and self._approve(name, arguments)
                if not allowed:
                    return {"jsonrpc": "2.0", "id": msg.get("id"), "result": _declined()}
        with self._lock:
            return mcp.handle(msg)

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "MiToolkit"

            def log_message(self, *_args) -> None:       # the default prints every request to the console
                pass

            def _send(self, code: int, body: bytes = b"", headers: Optional[Dict[str, str]] = None) -> None:
                self.send_response(code)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                if body:
                    self.send_header("Content-Type", "application/json")
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _refuse(self, code: int, text: str, headers: Optional[Dict[str, str]] = None) -> None:
                # The request body was not read: on a kept-alive connection it would be taken for the next request.
                self.close_connection = True
                self._send(code, json.dumps({"error": text}).encode(), {"Connection": "close", **(headers or {})})

            def _allowed(self) -> Tuple[bool, int, str]:
                """(ok, status, reason): is this request from the program on this computer that was given the token?"""
                host = (self.headers.get("Host") or "").lower()
                if host not in (f"127.0.0.1:{server.port}", f"localhost:{server.port}"):
                    return False, 403, "Wrong host."
                origin = (self.headers.get("Origin") or "").lower()
                if origin and not origin.startswith(("http://127.0.0.1", "http://localhost", "https://127.0.0.1",
                                                     "https://localhost")):
                    return False, 403, "Requests from web pages are not accepted."
                given = self.headers.get("Authorization") or ""
                if not given.startswith("Bearer ") or not hmac.compare_digest(given[7:].encode(), server.token.encode()):
                    return False, 401, "A valid token is needed."
                return True, 200, ""

            def do_POST(self) -> None:
                if self.path.split("?", 1)[0] != PATH:
                    return self._refuse(404, "Not found.")
                ok, status, reason = self._allowed()
                if not ok:
                    return self._refuse(status, reason, {"WWW-Authenticate": "Bearer"} if status == 401 else None)
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._refuse(400, "Bad length.")
                if length <= 0 or length > MAX_BODY:
                    self.close_connection = True
                    return self._refuse(413 if length > MAX_BODY else 400, "The request is empty or too large.")
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw)
                except ValueError:
                    return self._send(200, json.dumps({"jsonrpc": "2.0", "id": None,
                                                       "error": {"code": -32700, "message": "Parse error"}}).encode())
                if isinstance(payload, list):                   # a batch: answer each request, skip notifications
                    replies = [r for r in (server.dispatch(m) for m in payload) if r is not None]
                    reply: Any = replies or None
                else:
                    reply = server.dispatch(payload)
                if reply is None:
                    return self._send(202)                       # only notifications: accepted, nothing to say
                self._send(200, json.dumps(reply).encode())

            def _not_offered(self) -> None:
                self._refuse(405, "Only POST is offered.", {"Allow": "POST"})

            do_GET = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_offered      # no streaming, no browser access

        return Handler
