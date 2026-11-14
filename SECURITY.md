# Security policy

## Supported versions

Only the latest commit on the `main` branch is supported. There are no tagged
releases yet.

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue.

Use GitHub's private reporting: open the repository's **Security** tab and choose
**Report a vulnerability**. Include what you found, how to reproduce it, and the
impact you expect.

I will acknowledge the report as soon as I can and work with you on a fix. This is
a small volunteer project, so there is no guaranteed response time.

## Scope

In scope:

- Anything that could leak, log or weaken the protection of a Mi Account password,
  session token or `~/.miunlocksession/session.json`
- Any way to run `fastboot oem unlock` without the explicit confirmation described
  in [docs/safety.md](docs/safety.md)
- Command injection or unsafe subprocess use
- Network requests to destinations other than those listed in the safety model

Out of scope:

- Weaknesses in Xiaomi's own login page, servers or unlock protocol. Report those
  to Xiaomi.
- Problems that need an attacker who already controls your computer or your
  user account
- Issues in the original MiUnlockTool or migate that this fork has not changed:
  report them to [MiForge](https://github.com/MiForge) as well

## Handling your own data

If you use this tool, delete `~/.miunlocksession/` when you finish and check the
signed-in devices on your Mi Account. See [docs/safety.md](docs/safety.md).
