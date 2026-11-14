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
   Deleted `migate/login/terminal.py`, `verify.py`, `sendcode.py`, and
   `verifycode.py`. `terminal.py` read the Mi Account password from the
   console and computed an unsalted `hashlib.md5(password).hexdigest().upper()`,
   POSTed to Xiaomi's own `serviceLoginAuth2` endpoint -- this mirrors
   Xiaomi's own legacy passport protocol (not a flaw this project
   introduced), but an unsalted MD5 digest is password-equivalent if ever
   intercepted or logged. Only **Browser** (default) and **QR code** login
   remain; both open Xiaomi's real login page, so the password never
   touches this project's code at all.

2. **The saved session file is locked down.** After writing
   `~/.migatesession/<sid>/session.json` (which holds a long-lived
   `passToken` -- effectively a bearer credential for the account),
   `migate/passtoken.py` now restricts that file to the current user
   account (`icacls ... /grant:r` on Windows, `chmod 600` elsewhere) and
   prints its path with a reminder to delete it when done.

3. **`migate` is vendored into `src/migate/` instead of being an external
   dependency.** Previously this project depended on `migate` from PyPI
   (no supply-chain provenance linking the package back to its GitHub
   source) or, in an earlier revision of this fork, from a separate git
   branch. Merging it directly into this repository means `pip install .`
   builds everything from one reviewed source tree, with no external
   fetch at install time beyond `requests`/`rich`/`qrcode`/`pyaes` from
   PyPI (migate's and miunlock's own ordinary dependencies).

No functional network destination was changed anywhere: every request
still goes only to `account.xiaomi.com`, `api.account.xiaomi.com`, and the
regional `*.unlock.update*.miui.com` endpoints, exactly as upstream.

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
