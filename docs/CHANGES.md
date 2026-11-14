# Changes in this fork (standalone)

This is a security-hardened, standalone merge of
[MiForge/MiUnlockTool](https://github.com/MiForge/MiUnlockTool) and its
`migate` dependency ([offici5l/migate](https://github.com/MiForge/migate)),
both by **offici5l**. It was created after a full file-by-file review of
both projects, which found no telemetry, analytics, or network destination
outside official Xiaomi domains and `dl.google.com` (for downloading
`fastboot`). Full credit for the original design and implementation belongs
to offici5l -- see the README's "About this repository" section.

## What changed from upstream

1. **Removed the password-based "Terminal" login path entirely.**
   Deleted `login/terminal.py`, `verify.py`, `sendcode.py`, and
   `verifycode.py`. `terminal.py` read the Mi Account password from the
   console and computed an unsalted `hashlib.md5(password).hexdigest().upper()`,
   POSTed to Xiaomi's own `serviceLoginAuth2` endpoint -- this mirrors
   Xiaomi's own legacy passport protocol (not a flaw this project
   introduced), but an unsalted MD5 digest is password-equivalent if ever
   intercepted or logged. Only **Browser** (default) and **QR code** login
   remain; both open Xiaomi's real login page, so the password never
   touches this project's code at all.

2. **The saved session file is locked down.** After writing
   `~/.miunlocksession/<sid>/session.json` (which holds a long-lived
   `passToken` -- effectively a bearer credential for the account),
   `passtoken.py` now restricts that file to the current user account
   (`icacls ... /grant:r` on Windows, `chmod 600` elsewhere) and prints
   its path with a reminder to delete it when done.

3. **The Xiaomi auth gateway is fully merged into this codebase, not
   just vendored alongside it.** It started life as a separate package
   (`migate`), was first pinned as an external git dependency, then
   vendored in as a sibling package under the same `src/` tree, and is
   now merged all the way in as `miunlock.auth` -- one package, one
   namespace, no second top-level import (`import migate` no longer
   works; everything is `miunlock.auth.*`). `pip install .` builds one
   reviewed source tree, with no external fetch at install time beyond
   `requests`/`rich`/`qrcode`/`pyaes` from PyPI (its own and miunlock's
   ordinary dependencies). Full attribution to its original author,
   offici5l, and its original MIT license are preserved in
   `THIRD_PARTY_LICENSE_migate.txt` and the README's credits section --
   merging the code doesn't change who wrote it.

No functional network destination was changed anywhere: every request
still goes only to `account.xiaomi.com`, `api.account.xiaomi.com`, and the
regional `*.unlock.update*.miui.com` endpoints, exactly as upstream.

## Added: a programmatic API, CLI subcommands, and a GUI

Running `miunlock` with no arguments still does exactly what it always
did -- that interactive flow is byte-for-byte unchanged. Everything below
is new and additive.

**`src/miunlock/api.py`** -- a plain Python API for scripts, CI, and
agents: `login()`, `get_account_zone()`, `get_device_codename()`,
`check_unlock_eligibility()` (safe, read-only, asks Xiaomi's server
whether unlock is currently possible without fetching a token), and
`perform_unlock()`.

**`miunlock login|status|check|unlock`** -- non-interactive CLI
subcommands built on the API above, each printing JSON. `login`,
`status`, and `check` are all safe and read-only.

**`miunlock-gui`** -- a Tkinter GUI (no new dependency) with the same
three steps as buttons.

### The safety gate (please read this if you're wiring up automation)

`perform_unlock()` -- the only function that calls `fastboot oem
unlock` -- raises `UnlockError` and refuses to run unless called with
`confirm_wipe=True`. There is no default, config value, or environment
variable that sets this for you. The `unlock` CLI subcommand mirrors
this with a required `--confirm-wipe` flag; omit it and the command
prints an error and exits 1 without touching the device. The GUI backs
this with an actual `askyesno` dialog showing the server's own
data-wipe notice -- there is no "don't ask again" checkbox.

This exists because unlocking wipes the device's user data immediately
and permanently, with nothing after that point to stop it. If you are
building an agent, a script, or any automation on top of this API: the
`confirm_wipe=True` / `--confirm-wipe` call site should be the one line
a human reviews and sets on purpose, every single run -- not inferred
from context, not hardcoded "to save a step," and not something an
agent decides on its own. Everything else in this tool (login, account
info, device info, eligibility checks) is unrestricted, because none of
it can destroy anything.

## Notes from real-world testing (India / POCO M2 Pro, MIUI 12, Nov 2026)

Documented here because neither Xiaomi nor upstream documents these
response codes anywhere public that we found:

- **Error 20031**: *"Please add your account in Settings > Developer
  options > Mi Unlock status."* -- being signed into a Mi Account on the
  device is **not** sufficient; the account must also be explicitly added
  via the on-device **Mi Unlock status** screen before the server will
  accept an unlock request at all.
- **Error 20036**: *"Please unlock 168 hours later. And do not add your
  account in MIUI again, otherwise you will wait from scratch."* -- adding
  the account (step above) starts a mandatory ~168-hour (7-day) wait
  before Xiaomi's server will issue an unlock token. **Re-adding the
  account during this wait resets the timer to zero.** Leave the Mi
  Unlock status screen alone entirely once the account has been added.

Neither error reaches `fastboot stage` / `fastboot oem unlock` -- both are
rejected at the server step before any token is issued, so a rejected
request does not touch the device's data.
