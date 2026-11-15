# AI agents

An agent can control and read `mitoolkit` directly through the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP). It is the same program, started
with a flag:

```sh
mitoolkit --mcp
```

The server talks over stdin/stdout, needs no extra package, and every result is JSON.

## Connecting

Add it to your agent's MCP configuration. For example, in a Claude Code or Claude Desktop
config:

```json
{
  "mcpServers": {
    "mitoolkit": { "command": "mitoolkit", "args": ["--mcp"] }
  }
}
```

If you only have the Python package, use `"command": "python", "args": ["-m", "mitoolkit", "--mcp"]`.

## In the running app

`mitoolkit --mcp` starts a separate program. To use the MiToolkit window that is already open, with its phone,
saved session and settings, a person turns on **Help > AI Agent Connection > Turn On**. The app then listens on
`127.0.0.1` (this computer only) at an address and with a secret token it shows. Any program that speaks MCP over
HTTP can use it. Choose the client under **Settings For** and press **Copy Settings**:

| Settings for | What you get |
|---|---|
| Any MCP Client (JSON) | The standard `mcpServers` entry (`type`, `url`, `headers`): most clients, including Cursor and Claude Desktop's custom connectors |
| Claude Code (Command) | `claude mcp add --transport http mitoolkit URL --header "Authorization: Bearer TOKEN"` |
| VS Code (JSON) | The same entry for `mcp.json`, where the list is called `servers` |
| Clients That Start a Program (Command) | `npx -y mcp-remote URL --header ...`, for clients that can only run a command (they talk over stdin and stdout) and not call an address |
| ChatGPT and OpenAI API (JSON) | The `mcp` tool entry for the Responses API, with `require_approval` set to `always` |
| Test with curl (Command) | A `curl` line that asks for the tool list, to try it with no client |

**ChatGPT and the OpenAI API** make the call from OpenAI's servers, so they can only reach an address that is public on
the internet; a `127.0.0.1` address works for clients that run on this computer. To use ChatGPT you would have to put
this address behind a tunnel or a proxy you trust. Anyone who can reach it and has the token can use the tools while it
is on, so do that only with care. Clients that run on this computer (Claude Code, Codex, Cursor, VS Code and the like)
need nothing more.

- It is off until switched on and stops when switched off or when the app closes. The token changes every time.
- The tools are the same as below. Those that change something (`reboot_to_fastboot`) or use the saved session
  (`login`) show a question in the app, with the agent's name, and run only if the person answers Allow. No answer is a no.
- The window follows what an agent does. While a tool runs the status bar says what it is doing (for example "Cursor is
  running the security check", with the agent's own name) with the progress bar, and says when it is done. A device or reboot call makes the window
  look at the phone again at once, and a security check colours the Security Check button, as if you had run it.
  Xiaomi's eligibility answer is deliberately not copied into step 3: unlocking is a person's decision, so you press
  Check Eligibility yourself.
- The status bar on the right shows the agent's name in green while it is connected, amber while it waits for an
  answer, and "AI agent connection on" when none is using it. The Activity log lists every tool an agent used.
- Requests without the token, from another site (a browser page), or with another host name are refused.

## Tools

| Tool | What it does |
|---|---|
| `version` | Version, and a reminder that agents cannot unlock |
| `list_devices` | Phones seen by adb (model, codename, Android and MIUI version, bootloader locked or not) and by fastboot |
| `reboot_to_fastboot` | Reboots a phone running Android into fastboot with adb. Erases nothing |
| `login` | Uses the saved session. With none, a person must sign in in the browser; the call waits |
| `check_eligibility` | Asks Xiaomi whether the fastboot phone can be unlocked now. Read-only. Returns an error at once if no phone is in fastboot mode |
| `security_check` | Read-only security check of a phone running Android (OSV bulletins, Play Protect, app access, known stalkerware) |
| `device_details` | Everything a phone running Android reports over USB, in sections. Read-only. Serial number, IMEI, Android ID and addresses are left out |
| `connections` | Read-only state of Wi-Fi, the mobile network (modem), SIM, Bluetooth and USB, with findings that say what looks wrong. Network and device names and addresses are hidden |
| `doctor` | Read-only check of the setup (Python, USB access, adb key, saved session, settings, log) with what is wrong and how to fix it. Agents get the diagnosis only; a person runs `mitoolkit doctor --fix` |
| `read_log` | The last lines of `mitoolkit.log`, with tokens scrubbed |

## What an agent cannot do

**Unlock.** Erasing a phone is a person's decision, so the MCP server has no unlock tool
and no setting that adds one. A person runs it in the GUI, or with
`mitoolkit --cli unlock --confirm-wipe`. Session tokens never leave the program either: results
contain status and device details only. See the [safety model](safety.md).

## Without MCP

The command line prints JSON too, so an agent with a shell can use it directly:
`mitoolkit devices`, `mitoolkit check`. The [Python API](api.md) offers the same as functions.
