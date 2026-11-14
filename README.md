<div align="center">

<a href="https://github.com/jowinjohnchemban/miunlock">
  <img src="https://img.shields.io/badge/MiUnlockTool-%23FF6900?style=flat&logo=xiaomi&logoColor=white" alt="MiUnlockTool" width="200"/>
</a>

**Developed to retrieve [`encryptData(token)`](docs/encryptData.md) for Xiaomi devices to unlock the bootloader.**

---

[![Standalone fork](https://img.shields.io/badge/standalone_fork-password--login_removed-brightgreen)](docs/CHANGES.md)
[![Changelog](https://img.shields.io/badge/Changelog-blue?style=flat&logoColor=white)](docs/CHANGELOG.md)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)

> Not published to PyPI -- install from source (see [Installation](#installation)).
> For the original upstream project and its PyPI package, see the credits below.

---

### Contents

**In this README:** [Installation](#installation) · [Usage](#usage) ·
[Scripting, automation, and the GUI](#scripting-automation-and-the-gui) ·
[About this repository](#about-this-repository)

**In [`docs/`](docs/):**
[Installation Guide](docs/INSTALL.md) ·
[FAQ & Troubleshooting](docs/FAQ.md) ·
[Bootloader Unlock Guide](docs/unlock_guide.md) ·
[encryptData Reference](docs/encryptData.md) ·
[Error Codes & Messages Reference](docs/miunlock-codes-reference.md) ·
[Changes in this Fork](docs/CHANGES.md) ·
[Changelog](docs/CHANGELOG.md) ·
[Contributing](docs/CONTRIBUTING.md)

---

| | MiUnlockTool | Official MiFlashUnlock |
|---|---|---|
| Supported platforms | All | Windows only |
| Save login session | ✅ | ❌ |
| Verification methods | SMS / Email | SMS |
| dataCenterZone config | Automatic / Manual | Automatic |

</div>

---

## Installation

```sh
pip install git+https://github.com/jowinjohnchemban/miunlock.git
```

> See the **[Installation Guide](docs/INSTALL.md)** for detailed instructions.

---

## Usage

```sh
miunlock
```

### Scripting, automation, and the GUI

```sh
miunlock login            # log in (or reuse a saved session), prints JSON
miunlock status           # account + device info, prints JSON
miunlock check            # is this account/device eligible to unlock right now?
miunlock unlock --confirm-wipe   # actually unlocks -- WIPES THE DEVICE, no undo

miunlock-gui               # simple Tkinter GUI with the same three steps
```

`login`, `status`, and `check` are safe and read-only. `unlock` refuses
to do anything unless `--confirm-wipe` is passed explicitly -- there is
no default that enables it. A Python API (`miunlock.api`) backs all of
this for agents/scripts that want structured calls instead of a
subprocess; see [docs/CHANGES.md](docs/CHANGES.md#the-safety-gate-please-read-this-if-youre-wiring-up-automation)
for the safety design before you build on it.

---

## About this repository

This is a **standalone fork**, detached from the GitHub fork network of
the original projects, merging two previously separate repositories into
one for simpler installation (no external git dependency):

- **[MiForge/MiUnlockTool](https://github.com/MiForge/MiUnlockTool)** by
  [**offici5l**](https://github.com/offici5l) -- the `miunlock` package
  (`src/miunlock/`).
- **[offici5l/migate](https://github.com/MiForge/migate)** by
  [**offici5l**](https://github.com/offici5l) -- the `migate` package
  (`src/migate/`), vendored in directly rather than installed as a
  separate dependency.

All credit for the original design, the Xiaomi authentication/unlock
protocol implementation, and the vast majority of this code belongs to
**offici5l**. This repository only adds the security hardening and
documentation changes described in `CHANGES.md` -- see that file for the
exact diff and rationale. `migate`'s original MIT license and copyright
notice are preserved in `THIRD_PARTY_LICENSE_migate.txt`.

If you don't need the hardening changes, use the original projects linked
above instead -- they're actively maintained by their original author.

---

<div align="center">


❓ [FAQ & Troubleshooting](docs/FAQ.md)


</div>