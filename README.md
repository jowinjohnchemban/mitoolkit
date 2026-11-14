<div align="center">

<a href="https://github.com/MiForge/MiUnlockTool/releases/latest">
  <img src="https://img.shields.io/badge/MiUnlockTool-%23FF6900?style=flat&logo=xiaomi&logoColor=white" alt="MiUnlockTool" width="200"/>
</a>

**Developed to retrieve [`encryptData(token)`](docs/encryptData.md) for Xiaomi devices to unlock the bootloader.**

---

[![Version](https://img.shields.io/pypi/v/miunlock?label=Version&labelColor=black&color=brightgreen)](https://pypi.org/project/miunlock/)
[![Changelog](https://img.shields.io/badge/Changelog-blue?style=flat&logoColor=white)](docs/CHANGELOG.md)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)

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