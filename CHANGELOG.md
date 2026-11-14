# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The history of the original MiUnlockTool (versions 1.4.8 through 1.7.5)
is kept in [docs/upstream-changelog.md](docs/upstream-changelog.md).

## [Unreleased]

## [1.8.0] - 2026-11-15

First release of this fork. It starts from MiUnlockTool 1.7.5 and migate 1.1.11,
both by offici5l.

### Added

- Python API, `miunlock.api`, with `login`, `get_account_zone`,
  `get_device_codename`, `check_unlock_eligibility` and `perform_unlock`.
- Command line subcommands that print JSON: `login`, `status`, `check`, `unlock`.
- `miunlock-gui`, a small Tkinter GUI.
- `--confirm-wipe` / `confirm_wipe=True` confirmation for the unlock step in the
  CLI and API, and a confirmation dialog in the GUI.
- `login_method` option on `get_passtoken` to choose browser or QR login without a
  prompt.
- `NOTICE` file with attribution and the MIT notice for migate-derived code.
- Documentation rewritten into `docs/` with an index.
- `miunlock --version`.
- Release builds: Windows, Linux and macOS executables (`miunlock` and
  `miunlock-gui`), a wheel and an sdist, with SHA-256 checksums, built by GitHub
  Actions from the tagged source.
- CI that installs on three operating systems and checks the confirmation gate.

### Changed

- migate is merged into the package as `miunlock.auth`; `import migate` no longer
  works. There is now a single package and no external git dependency.
- The saved session moved from `~/.migatesession` to `~/.miunlocksession`.
- The session file is restricted to the current user after it is written.
- Installation is from this repository, not PyPI.
- The version number lives in one place, `miunlock.__version__`, and starts at
  1.8.0 (upstream was at 1.7.5).
- Minimum Python raised to 3.9, which the build backend requires.
- Running `miunlock` with no arguments behaves as before.

### Removed

- Upstream's manual "Publish to PyPI" workflow; this fork is not published on PyPI.
- Password ("Terminal") login and its two-factor helpers (`login/terminal.py`,
  `verify.py`, `sendcode.py`, `verifycode.py`). Only browser and QR login remain.
  The old code sent an unsalted MD5 of the account password to Xiaomi's login
  endpoint.

### Security

- Error messages no longer print login or config responses, which carry session
  tokens; only status fields and field names are shown.
- Failed requests no longer report the URL, which contains one-time login tokens, and no
  longer chain the original exception into tracebacks.
- The session file is created owner-only from the start (and its folder restricted) instead
  of being tightened afterwards, and the program no longer claims it is protected if the
  restriction could not be applied.
- The signed unlock token goes to a private, randomly named temporary file, not a
  predictable file in the home folder.
- URLs from Xiaomi's responses are opened without a shell (previously a quote in the URL
  could run a command on Linux and Termux) and only if they are https.
- The GUI masks the account ID.
- CI: actions pinned to commits, read-only default token permissions, checkout no longer
  persists the token, and a regression test suite runs on every push.
- See [docs/safety.md](docs/safety.md) for the full model and its limits.
