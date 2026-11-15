# Working on MiToolkit (for AI agents and new contributors)

MiToolkit is a desktop tool (Python, Tkinter) for Xiaomi, Redmi and POCO phones: unlock, device details, live status,
backup, apps, security check, adb over USB and Wi-Fi, and an MCP server for agents. Read [CONTRIBUTING.md](CONTRIBUTING.md)
and [docs/architecture.md](docs/architecture.md) first. Using MiToolkit from an agent (rather than changing it) is in
[docs/agents.md](docs/agents.md).

## Commands

```sh
pip install -e .
python -m unittest discover -s tests          # the whole suite (about 100 s; UI tests need a display)
python -m unittest tests.test_text_standard   # the text standard below
```

## How changes are made

- `main` is protected: work on a branch and open a pull request. Never push to `main`.
- The pull request title is a [Conventional Commit](https://www.conventionalcommits.org): `feat:` is a minor release,
  `fix:`, `docs:`, `ci:` and the like are patches, `!` is a major release, `[skip release]` skips the release. Every
  merge to `main` is released automatically with its version worked out from that title.
- Do not add `Co-Authored-By` or any other attribution line to commits or pull requests.
- Wait for every check (tests on three systems, CodeQL, OSV, secret scan) and fix what they find before merging.
- Edit files with the editor's edit tools, not with search-and-replace scripts. Keep changes small and in focus.
- Add or update tests with every change. Tests use fakes: never a real phone, a real account or the real
  `~/.mitoolkit` (use `tests/isolate.py` for settings).

## Safety rules (a change that breaks one is not merged)

- Never unlock without a person's explicit confirmation in the GUI or `--confirm-wipe`. No tool, option or environment
  variable may supply it. The MCP servers have no unlock tool.
- Do not change the Xiaomi protocol code (`xiaomi.py`, the unlock and sign-in flow in `unlock.py` and `api.py`) unless the
  change is the point of the pull request; those two files repeat one request sequence and change together.
- No password entry, no telemetry, no network destinations other than Xiaomi, Google's driver download, GitHub (updates)
  and OSV (security check). Tokens are never logged or shown.
- Tools offered to agents are read and check only. Anything that changes a phone or uses the saved session asks the
  person first.

## Text standard

Everything a person reads follows one standard, and `tests/test_text_standard.py` fails when new text breaks it.

- **Labels** (buttons, menu items, tabs, window titles, field names, headings that name a thing) are in **Title Case**:
  *Back Up Files*, *Pair or Connect*, *Reboot to Fastboot*, *Sign In to Mi Account*. Short words in the middle stay
  small (a, an, the, and, or, to, in, on, for, of, by, from, with).
- **Sentences and messages** are in sentence case: a capital at the start, a full stop at the end, and a capital
  after "Step 2:" (*Step 2: Connect your phone.*). A message says what happened, why, and what to do.
- **Names are spelled the same everywhere**: MiToolkit, Wi-Fi, USB, Android, Google, Xiaomi, HyperOS, MIUI, GPU, RAM, SoC,
  ADB. The mode is called Wi-Fi in the app; "Wireless debugging" is only Android's own setting.
- **No "..."** in text. A button names what it does (*Back Up Files*, not *Back up files...*); a status says what is
  happening (*Looking for the phone*). When a list is cut short say *and more*.
- **No decorative symbols** (middle dots, bullets, arrows, play marks). Separate with a comma. A status never relies on
  colour alone: a word says it too.
- Write for people who are not experts. Short, plain, kind.

## Testing with a real phone

Only when asked, and read-only: details, live status, security check, scans. Never unlock, erase or reboot into fastboot
on a phone you were not told to. Leave things as you found them: if you started Google's adb server, stop it
(`adb kill-server`), and never leave a program holding the phone's USB interface.

## Upstream watch

This project grew from two others by offici5l: [MiUnlockTool](https://github.com/MiForge/MiUnlockTool) and
[migate](https://github.com/MiForge/migate). **Listen to both** for patches, updates and ideas, at the start of
work on the unlock or sign-in code and at least once a month:

```sh
gh api repos/MiForge/MiUnlockTool/commits --jq '.[0:15][] | "\(.sha[0:9]) \(.commit.committer.date) \(.commit.message | split("\n")[0])"'
gh api repos/MiForge/MiUnlockTool/releases/latest --jq '.tag_name + " " + .published_at'
gh issue list --repo MiForge/MiUnlockTool --limit 20     # and the same for MiForge/migate
```

Compare with the last reviewed versions in [docs/upstream.md](docs/upstream.md), decide what is worth bringing over
(Xiaomi server changes first, then fixes for phones and drivers, then ideas), do each as its own pull request with a
test, keep the licences and [NOTICE](NOTICE) intact, and update the table in that file. Do not copy code blindly.
