# Upstream projects

MiToolkit began from two projects by [offici5l](https://github.com/offici5l), which now live under the
[MiForge](https://github.com/MiForge) organisation. Their authors keep fixing how Xiaomi's servers and phones behave, so
their patches, updates and ideas are worth reading regularly. How to do it is in [AGENTS.md](../AGENTS.md#upstream-watch).

| Project | What it is | Licence | Last reviewed |
|---|---|---|---|
| [MiForge/MiUnlockTool](https://github.com/MiForge/MiUnlockTool) | The unlock tool this project's unlock code came from | Apache-2.0 | release v1.7.5, commit `43a80a879` (2026-11-12) |
| [MiForge/migate](https://github.com/MiForge/migate) | The Mi Account sign-in this project's login came from | MIT | release v1.1.11, commit `59c2a263a` (2026-09-30) |

Update the last two columns every time you review, even when nothing is worth taking, so the next person starts from there.

## What to look for

- A change in how Xiaomi's servers answer (new address, region, error code, wait time, field name): the unlock and
  sign-in code in `src/mitoolkit/api.py`, `unlock.py` and `xiaomi.py` must keep up, and any change there is made
  in `unlock.py` and `api.py` together.
- Fixes for particular phones, drivers or operating systems that this project may not have met yet.
- Open issues and pull requests that describe a problem users also have here.
- Ideas for features or wording worth building in this project's own way.

Bring a change over as its own pull request with a test, and keep the licences and the notice in [NOTICE](../NOTICE)
intact. The authors are credited in [CREDITS.md](../CREDITS.md) when their code is used.
