"""MCP in the app: the local HTTP server (token, host and origin checks, approval, one call at a time), the status bar,
and the AI agent connection window."""
import http.client
import json
import os
import sys
import threading
import time
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from tkhelper import make_root  # noqa: E402

from mitoolkit import mcp, mcp_http  # noqa: E402

try:
    import tkinter as tk
    tk.Tk().destroy()
    HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


class Client:
    """A bare HTTP client, so a test can send any header it likes."""

    def __init__(self, server):
        self.server = server

    def post(self, body, token=True, headers=None, path=mcp_http.PATH, raw=None):
        conn = http.client.HTTPConnection(mcp_http.HOST, self.server.port, timeout=10)
        sent = {"Content-Type": "application/json"}
        if token:
            sent["Authorization"] = f"Bearer {self.server.token}"
        sent.update(headers or {})
        payload = raw if raw is not None else json.dumps(body)
        conn.request("POST", path, body=payload, headers=sent)
        reply = conn.getresponse()
        data = reply.read()
        conn.close()
        return reply.status, (json.loads(data) if data else None), dict(reply.getheaders())

    def call(self, name, arguments=None, ident=1):
        return self.post({"jsonrpc": "2.0", "id": ident, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments or {}}})


class ServerTests(unittest.TestCase):
    def start(self, **kw):
        server = mcp_http.McpHttpServer(**kw).start()
        self.addCleanup(server.stop)
        return server, Client(server)

    def test_it_listens_on_this_computer_only_and_each_run_has_its_own_token(self):
        a, _ = self.start()
        b, _ = self.start()
        self.assertEqual(a._httpd.server_address[0], "127.0.0.1")
        self.assertNotEqual(a.token, b.token)
        self.assertGreaterEqual(len(a.token), 40)
        self.assertEqual(a.url, f"http://127.0.0.1:{a.port}/mcp")

    def test_the_name_an_agent_gives_itself_is_kept_and_made_fit_to_show(self):
        self.assertEqual(mcp_http.client_name({"clientInfo": {"name": "claude-code"}}), "Claude Code")
        self.assertEqual(mcp_http.client_name({"clientInfo": {"name": "Claude Desktop"}}), "Claude Desktop")
        self.assertEqual(mcp_http.client_name({"clientInfo": {"name": "cursor_vscode\n\x1b[31m"}}), "Cursor Vscode[31M")
        self.assertEqual(len(mcp_http.client_name({"clientInfo": {"name": "x" * 200}})), 40)
        for nothing in (None, {}, {"clientInfo": None}, {"clientInfo": {"name": 5}}, "text"):
            self.assertEqual(mcp_http.client_name(nothing) if nothing != {"clientInfo": {"name": 5}}
                             else mcp_http.client_name(nothing).strip(), mcp_http.client_name(nothing))
        self.assertEqual(mcp_http.client_name({}), "")

    def test_connecting_tells_the_app_who_the_agent_is(self):
        met = []
        server, client = self.start(on_client=met.append)
        client.post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "claude-code"}}})
        self.assertEqual((server.client, met), ("Claude Code", ["Claude Code"]))
        client.post({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}})
        self.assertEqual(server.client, "Claude Code")                      # one that gives no name keeps the last one

    def test_a_request_needs_the_token(self):
        _, client = self.start()
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        status, _, headers = client.post(ping, token=False)
        self.assertEqual((status, headers.get("WWW-Authenticate")), (401, "Bearer"))
        self.assertEqual(client.post(ping, token=False, headers={"Authorization": "Bearer wrong"})[0], 401)
        self.assertEqual(client.post(ping, token=False, headers={"Authorization": "Basic abc"})[0], 401)
        self.assertEqual(client.post(ping)[0], 200)

    def test_another_site_in_host_or_origin_is_refused_even_with_the_token(self):
        """The DNS rebinding trick: a web page makes the browser send a request here under its own name."""
        _, client = self.start()
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        self.assertEqual(client.post(ping, headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(client.post(ping, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(client.post(ping, headers={"Origin": "http://localhost:5173"})[0], 200)   # a local tool is fine

    def test_only_post_to_the_mcp_path_is_offered(self):
        server, client = self.start()
        self.assertEqual(client.post({}, path="/other")[0], 404)
        conn = http.client.HTTPConnection(mcp_http.HOST, server.port, timeout=10)
        for method in ("GET", "PUT", "DELETE", "OPTIONS"):
            conn.request(method, mcp_http.PATH, headers={"Authorization": f"Bearer {server.token}"})
            reply = conn.getresponse()
            reply.read()
            self.assertEqual((method, reply.status, reply.getheader("Allow")), (method, 405, "POST"))
        conn.close()

    def test_a_request_that_is_too_large_or_not_json_is_refused_politely(self):
        server, client = self.start()
        conn = http.client.HTTPConnection(mcp_http.HOST, server.port, timeout=10)
        conn.putrequest("POST", mcp_http.PATH)
        conn.putheader("Authorization", f"Bearer {server.token}")
        conn.putheader("Content-Length", str(mcp_http.MAX_BODY + 1))
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 413)
        conn.close()
        status, body, _ = client.post(None, raw="{not json")
        self.assertEqual((status, body["error"]["code"]), (200, -32700))           # a JSON-RPC parse error

    def test_the_protocol_version_is_the_one_the_client_asks_for_when_it_is_supported(self):
        _, client = self.start()

        def version(params):
            return client.post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})[1]["result"]
        self.assertEqual(version({"protocolVersion": "2025-06-18"})["protocolVersion"], "2025-06-18")
        self.assertEqual(version({"protocolVersion": "2099-01-01"})["protocolVersion"], mcp.PROTOCOL)
        self.assertEqual(version({})["protocolVersion"], mcp.PROTOCOL)

    def test_notifications_get_202_and_a_batch_is_answered_request_by_request(self):
        _, client = self.start()
        status, body, _ = client.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual((status, body), (202, None))
        status, body, _ = client.post([{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                       {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                       {"jsonrpc": "2.0", "id": 2, "method": "ping"}])
        self.assertEqual((status, [r["id"] for r in body]), (200, [1, 2]))

    def test_the_tools_are_the_stdio_servers_and_never_include_unlocking(self):
        _, client = self.start()
        names = [t["name"] for t in client.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[1]["result"]["tools"]]
        self.assertEqual(names, list(mcp.TOOLS))
        self.assertFalse([n for n in names if "unlock" in n and n != "check_eligibility"])
        version = client.call("version")[1]["result"]
        self.assertIn('"can_unlock": false', version["content"][0]["text"])

    def test_the_tools_that_change_something_ask_the_person_and_the_others_do_not(self):
        asked = []
        calls = []

        def approve(tool, arguments):
            asked.append((tool, arguments))
            return True
        heard = []
        server, client = self.start(approve=approve, on_call=heard.append)
        fake = {"reboot_to_fastboot": ("x", mcp._SCHEMA_NONE, lambda a: calls.append(a) or {"ok": True})}
        with mock.patch.dict(mcp.TOOLS, fake):
            client.call("version")
            client.call("reboot_to_fastboot", {"serial": "abc"})
        self.assertEqual(asked, [("reboot_to_fastboot", {"serial": "abc"})])        # only the one that changes the phone
        self.assertEqual(calls, [{"serial": "abc"}])
        self.assertEqual(heard, ["version", "reboot_to_fastboot"])                  # the app hears of every call

    def test_a_no_or_no_answer_stops_the_call_before_it_runs(self):
        for approve in (lambda t, a: False, None):
            ran = []
            _, client = self.start(approve=approve)
            fake = {"reboot_to_fastboot": ("x", mcp._SCHEMA_NONE, lambda a: ran.append(a) or {"ok": True}),
                    "login": ("x", mcp._SCHEMA_NONE, lambda a: ran.append(a) or {"ok": True})}
            with mock.patch.dict(mcp.TOOLS, fake):
                for tool in ("reboot_to_fastboot", "login"):
                    result = client.call(tool)[1]["result"]
                    self.assertTrue(result["isError"])
                    self.assertIn("declined", result["content"][0]["text"])
            self.assertEqual(ran, [])

    def test_one_tool_runs_at_a_time(self):
        running, peak = [0], [0]

        def slow(_args):
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            time.sleep(0.15)
            running[0] -= 1
            return {"ok": True}
        _, client = self.start()
        with mock.patch.dict(mcp.TOOLS, {"list_devices": ("x", mcp._SCHEMA_NONE, slow)}):
            threads = [threading.Thread(target=client.call, args=("list_devices", None, i)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(peak[0], 1)

    def test_stopping_closes_the_door_and_closing_the_app_stops_what_is_on(self):
        server, client = self.start()
        self.assertIn(server, mcp_http._running)
        server.stop()
        self.assertNotIn(server, mcp_http._running)
        with self.assertRaises(OSError):
            client.post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        other = mcp_http.McpHttpServer().start()
        self.assertEqual(mcp_http.stop_all(), "Stopped the AI agent connection.")
        self.assertEqual((mcp_http._running, mcp_http.stop_all()), ([], ""))
        self.assertFalse(other._thread.is_alive())

    def test_the_settings_to_copy_carry_the_address_and_the_token(self):
        server, _ = self.start()
        command, settings = server.claude_code_command(), json.loads(server.json_settings())
        self.assertIn(server.url, command)
        self.assertIn(f"Authorization: Bearer {server.token}", command)
        entry = settings["mcpServers"]["mitoolkit"]
        self.assertEqual((entry["url"], entry["headers"]["Authorization"]), (server.url, f"Bearer {server.token}"))

    def test_the_closing_steps_include_the_agent_connection(self):
        from mitoolkit import shutdown
        self.assertIs(shutdown.STEPS[0], shutdown._stop_agents)           # before the phone is let go
        server = mcp_http.McpHttpServer().start()
        self.assertEqual(shutdown._stop_agents(), "Stopped the AI agent connection.")
        self.assertFalse(server._thread.is_alive())


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class AppTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit import gui
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app._polling = True
        self.root.update()


    def tearDown(self):
        self.app.agent_stop()                      # before the window goes: it ends the server and its timer
        self.root.destroy()

    def pump(self, until, tries=100):
        for _ in range(tries):
            self.root.update()
            if until():
                return True
            time.sleep(0.02)
        return until()

    def dot(self):
        return self.app.agent_dot.itemcget(self.app._agent_dot_item, "fill")

    def test_the_status_bar_shows_a_dot_and_the_agents_name_in_green_when_it_is_connected(self):
        from mitoolkit.ui.theme import AMBER, GREEN, MUTED
        app = self.app
        self.assertFalse(app.agent_box.winfo_manager())                          # off: nothing there
        self.assertEqual(app.agent_info.cget("text"), "")
        app.agent_start()
        self.root.update()
        self.assertTrue(app.agent_box.winfo_manager())
        self.assertEqual(app.agent_info.cget("text"), "AI agent connection on")   # on, but no agent yet: grey
        self.assertEqual((str(app.agent_info.cget("foreground")), self.dot()), (MUTED, MUTED))
        app._agent.dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"clientInfo": {"name": "claude-code", "version": "2.0"}}})
        self.assertTrue(self.pump(lambda: app.agent_info.cget("text") == "Claude Code connected"))
        self.assertEqual((str(app.agent_info.cget("foreground")), self.dot()), (GREEN, GREEN))   # green, with its name
        app._agent_asking = True                                                 # it asked, and waits for the person
        app._agent_status()
        self.assertEqual(app.agent_info.cget("text"), "Claude Code is waiting for your answer")
        self.assertEqual((str(app.agent_info.cget("foreground")), self.dot()), (AMBER, AMBER))
        app._agent_asking = False
        app._agent_last -= 200                                                   # then it went quiet: back to grey
        app._agent_status()
        self.assertEqual(app.agent_info.cget("text"), "AI agent connection on")
        app.agent_stop()
        self.assertFalse(app.agent_box.winfo_manager())
        self.assertEqual(app.agent_info.cget("text"), "")

    def test_the_status_bar_uses_a_calls_too_and_the_footer_order_is_agent_then_link(self):
        app = self.app
        app.agent_start()
        app._agent_called("list_devices")
        self.assertTrue(self.pump(lambda: "connected" in app.agent_info.cget("text")))
        self.root.update()
        self.assertLess(app.agent_box.winfo_rootx(), app.link_info.winfo_rootx())   # left of how the phone is connected
        self.assertIn("AI agent connected", app.agent_info.cget("text"))             # no name given: a plain one

    def test_the_activity_lines_about_agents_are_not_shown_as_errors(self):
        """"They cannot unlock" turned the line red: the Activity log colours any line with "cannot" as a problem."""
        from mitoolkit.ui.activity_window import kind_of
        self.app.agent_start()
        queued = []
        while not self.app.q.empty():
            queued.append(self.app.q.get_nowait())
        self.app._agent.client = "Claude Code"
        self.app._agent_called("list_devices")
        self.app._agent_met("Claude Code")
        while not self.app.q.empty():
            queued.append(self.app.q.get_nowait())
        lines = [rest[0] for kind, *rest in queued if kind == "log"]
        self.assertTrue(len(lines) >= 3, lines)
        self.assertEqual([kind_of(line) for line in lines], [""] * len(lines), lines)

    def test_a_second_start_gives_the_same_server_and_stop_is_safe_twice(self):
        first = self.app.agent_start()
        self.assertIs(self.app.agent_start(), first)
        self.app.agent_stop()
        self.app.agent_stop()
        self.assertIsNone(self.app._agent)

    def test_the_person_is_asked_in_the_window_and_no_answer_means_no(self):
        app = self.app
        outcome = []
        with mock.patch("mitoolkit.gui.messagebox.askyesno", return_value=True) as ask:
            thread = threading.Thread(target=lambda: outcome.append(app._agent_approve("reboot_to_fastboot", {})))
            thread.start()
            self.assertTrue(self.pump(lambda: bool(outcome)))
            thread.join()
        self.assertEqual(outcome, [True])
        self.assertIn("restart the phone into fastboot mode", ask.call_args[0][1])
        self.assertEqual(ask.call_args.kwargs.get("default"), "no")              # Enter does not allow it
        with mock.patch("mitoolkit.gui.messagebox.askyesno", return_value=False):
            outcome.clear()
            thread = threading.Thread(target=lambda: outcome.append(app._agent_approve("login", {})))
            thread.start()
            self.assertTrue(self.pump(lambda: bool(outcome)))
            thread.join()
        self.assertEqual(outcome, [False])

    def test_the_window_turns_it_on_and_off_and_copies_the_settings(self):
        from mitoolkit.ui.agent_dialog import AgentDialog
        d = AgentDialog(self.app)
        self.root.update()
        size = (d.win.winfo_width(), d.win.winfo_height())
        self.assertEqual((d.state.cget("text"), d.address.get(), d.token.get()), ("Off", "", ""))
        self.assertEqual(str(d.copy_buttons[0].cget("state")), "disabled")
        d.switch.invoke()
        self.root.update()
        server = self.app._agent
        self.assertEqual((d.address.get(), d.token.get()), (server.url, server.token))
        self.assertEqual(str(d.switch.cget("text")), "Turn Off")
        d._copy_command()
        self.assertEqual(self.root.clipboard_get(), server.claude_code_command())
        self.assertIn("Copied the Claude Code command", d.copied.cget("text"))
        d._copy_json()
        self.assertEqual(json.loads(self.root.clipboard_get())["mcpServers"]["mitoolkit"]["url"], server.url)
        self.assertEqual((d.win.winfo_width(), d.win.winfo_height()), size)        # the window never changes size
        d.switch.invoke()
        self.root.update()
        self.assertIsNone(self.app._agent)
        self.assertEqual((d.address.get(), d.token.get()), ("", ""))
        d.close()

    def test_what_agents_used_is_listed_in_the_window(self):
        from mitoolkit.ui.agent_dialog import AgentDialog
        d = AgentDialog(self.app)
        self.app._agent_called("list_devices")
        d._poll()
        self.assertIn("list_devices", d.recent.get("1.0", "end"))
        d.close()


if __name__ == "__main__":
    unittest.main()
