# Contributing

Contributions of any size are welcome: code, documentation, bug reports and ideas.

## Reporting issues

Open an [issue](https://github.com/jowinjohnchemban/mitoolkit/issues) with:

- your operating system and Python version (`python --version`)
- the `mitoolkit` command you ran and its output
- the device codename, if the problem involves a device

**Remove personal data first.** Do not paste your Mi Account ID, session files,
tokens, or the contents of `~/.mitoolkitsession/`. For security problems, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

```sh
git clone https://github.com/jowinjohnchemban/mitoolkit.git
cd mitoolkit
python -m venv .venv
# activate it: source .venv/bin/activate   or   .venv\Scripts\Activate.ps1
pip install -e .
mitoolkit --help
```

The code is in `src/mitoolkit/`; see [docs/architecture.md](docs/architecture.md).
Run the tests with `python -m unittest discover -s tests -v`. They use only dummy values and
never touch the network, a real session or a device. Please add a test with any fix that
touches credentials, logging or the unlock confirmation.

## Guidelines

**Code**

- Keep changes working on Windows, macOS and Linux.
- Keep it clean and concise, and prefer small files over large ones.
- Do not add dependencies without a good reason.
- `src/mitoolkit/unlock.py` and `src/mitoolkit/api.py` repeat the same request
  sequence. If you change one, change the other.

**Safety rules.** Pull requests that break these will not be merged:

- No code path may run `fastboot oem unlock` without an explicit confirmation from
  a person. Do not add defaults, environment variables or config options that
  supply it.
- Do not add password entry, or any way for the program to read or store the Mi
  Account password.
- Do not add network destinations other than Xiaomi's services and Google's USB
  driver download (Windows, on request), and no telemetry.
- Do not log tokens or session contents.

**Documentation**

- Write for people who are not experts.
- Keep pages short and focused, and link instead of repeating.
- Update [CHANGELOG.md](CHANGELOG.md) for user-visible changes.

## Pull requests

`main` is protected: nobody, including the maintainer, pushes to it directly. Every change is a pull
request that is squash-merged once these checks pass: **CI passed** (tests on Windows, macOS and Linux,
Python 3.9 and 3.13), **analyze** (CodeQL), **Vulnerable dependencies** (pip-audit), **Dependency review**
and **Secret scan**. Conversations must be resolved and the history stays linear. OSV-Scanner also checks
the exact dependency versions against Google's OSV database and reports to the Security tab.

1. Fork the repository and create a branch.
2. Make focused commits with clear messages.
3. Describe what changed and why, and how you checked it.
4. Open the pull request against `main`.

If a pull request is not merged, it is not a judgement of your work; it just may not
fit the direction of the project.

## Releasing

Releases are automatic. To publish one:

1. Change `__version__` in `src/mitoolkit/__init__.py` (major.minor.patch).
2. Add a `## [x.y.z] - date` section to `CHANGELOG.md`: it becomes the release notes.
3. Open a pull request. When it is merged to `main`, the release is built and published.

The Release workflow builds the programs for Windows, Linux and macOS and the Python packages, writes
`SHA256SUMS.txt`, and publishes the release with the tag `vx.y.z`. A version that already has a release is
skipped, so pushing again does nothing. The running app's updater (Help > Check for updates) installs from
that release and verifies the download against `SHA256SUMS.txt`, so keep that file in every release.

### Signing (Windows SmartScreen)

An unsigned Windows program makes SmartScreen show "Windows protected your PC". Signing it with a code-signing
certificate (an OV or EV certificate from a certificate authority) is the only way to avoid that. To turn
signing on, add two repository secrets (Settings > Secrets and variables > Actions): `WINDOWS_CERT_PFX_BASE64`
(the `.pfx` file, base64-encoded) and `WINDOWS_CERT_PASSWORD`. The Release workflow then signs and verifies
`mitoolkit.exe` before it is checksummed and published; without the secrets it builds unsigned. A new OV
certificate still needs some downloads to build reputation; an EV certificate is trusted at once.

## License

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
