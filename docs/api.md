# Python API

`miunlock.api` exposes the unlock process as plain functions. They return
dictionaries and raise `UnlockError` instead of printing or waiting on `input()`,
so they can be used from scripts, CI jobs and other tools. The command line
subcommands are a thin wrapper around this module.

```python
from miunlock import api
```

## Example

```python
from miunlock import api

try:
    token = api.login()                          # reuses a saved session if present
    result = api.check_unlock_eligibility(token) # read-only; device must be in fastboot

    if not result["eligible"]:
        print("Not eligible:", result.get("code"), result.get("description"))
    else:
        print("Device:", result["product"])
        print("Will erase data:", result["will_wipe_data"])
        print("Server notice:", result["notice"])

        # A human decides this, every time. See "The confirmation gate" below.
        # api.perform_unlock(token, result, confirm_wipe=True)
except api.UnlockError as err:
    print("Failed:", err)
```

## Functions

### `login(login_method="1", silent_if_cached=True) -> dict`

Returns the session dictionary `{"deviceId", "passToken", "userId"}`.

- `login_method`: `"1"` for browser login, `"3"` for a QR code. Ignored when a
  saved session is reused.
- `silent_if_cached`: reuse a saved session without prompting.

If no saved session exists, a browser opens (or a QR code is printed) and the call
waits until a person finishes logging in on Xiaomi's page. There is no way to
automate that step. Raises `UnlockError` if login fails or is cancelled.

### `get_account_zone(passtoken) -> str`

Returns the Xiaomi data center for the account: `"Singapore"`, `"China"`,
`"India"`, `"Russia"` or `"Europe"`. These select the unlock server
(see [architecture](architecture.md)).

### `get_device_codename(fastboot_cmd=None) -> str`

Returns the device codename, for example `"gram"`. The device must be in fastboot
mode. If no device is connected this waits for one. `fastboot_cmd` is the path to
a `fastboot` binary; when omitted it is found or downloaded.

### `check_unlock_eligibility(passtoken, zone=None) -> dict`

Safe and read-only. Asks Xiaomi whether this account and device can be unlocked
now. It does not fetch an unlock token and does not run `fastboot oem unlock`.

Returns a dictionary with `"eligible": bool`. When eligible it also contains:

| Key | Meaning |
|---|---|
| `product` | Device codename |
| `zone` | Data center used |
| `will_wipe_data` | `True` if unlocking erases user data |
| `notice` | Text from Xiaomi to show the user |

When not eligible it contains `code` and `description` from Xiaomi (see
[error codes](error-codes.md)), or `error` for a transport-level failure. The
dictionary also carries an internal `_service` entry that
`perform_unlock` needs; do not build or edit it by hand.

### `perform_unlock(passtoken, eligibility, *, confirm_wipe) -> dict`

Runs the unlock: fetches the unlock token from Xiaomi and runs
`fastboot stage` followed by `fastboot oem unlock`. **This erases the device on
most models and cannot be undone.**

Returns `{"success": True, "product": "<codename>"}`. Raises `UnlockError` if the
device is not eligible, if the `eligibility` value was not produced by
`check_unlock_eligibility`, or if any step fails.

## The confirmation gate

`confirm_wipe` is keyword-only and has no default. If it is not exactly `True`,
`perform_unlock` raises `UnlockError` without contacting the server or the device.
Nothing in this project sets it for you: no environment variable, config file or
default.

If you build automation on this API, treat the line that sets
`confirm_wipe=True` as the point where a person decides, every run. Do not
hard-code it, and do not let an unattended process or an AI agent choose it. See
the [safety model](safety.md).

## Errors

`UnlockError` is the exception raised for expected failures, and `str(err)` is a
readable message. One case is reported differently: if Xiaomi's server rejects the
eligibility request itself, `check_unlock_eligibility` returns
`{"eligible": False, ...}` with `code`/`description` or `error` instead of raising,
so always check `result["eligible"]`.

## Stability

This API was added in this fork and is not part of the original MiUnlockTool. It
is young and may change. Xiaomi can also change its server protocol at any time;
`api.py` repeats the request sequence from `unlock.py`, so both files must be
updated if that happens.
