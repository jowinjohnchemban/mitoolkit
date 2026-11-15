# AI agents

An agent can control and read `miunlock` directly through the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP). It is the same program, started
with a flag:

```sh
miunlock --mcp
```

The server talks over stdin/stdout, needs no extra package, and every result is JSON.

## Connecting

Add it to your agent's MCP configuration. For example, in a Claude Code or Claude Desktop
config:

```json
{
  "mcpServers": {
    "miunlock": { "command": "miunlock", "args": ["--mcp"] }
  }
}
```

If you only have the Python package, use `"command": "python", "args": ["-m", "miunlock", "--mcp"]`.

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
| `read_log` | The last lines of `miunlock.log`, with tokens scrubbed |

## What an agent cannot do

**Unlock.** Erasing a phone is a person's decision, so the MCP server has no unlock tool
and no setting that adds one. A person runs it in the GUI, or with
`miunlock --cli unlock --confirm-wipe`. Session tokens never leave the program either: results
contain status and device details only. See the [safety model](safety.md).

## Without MCP

The command line prints JSON too, so an agent with a shell can use it directly:
`miunlock devices`, `miunlock check`. The [Python API](api.md) offers the same as functions.
