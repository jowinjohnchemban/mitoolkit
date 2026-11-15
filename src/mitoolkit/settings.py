"""A few remembered choices (for example "check for updates automatically"), in ``~/.mitoolkit/settings.json``.

Nothing secret is stored here. A missing or damaged file just means the defaults.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PATH = Path.home() / ".mitoolkit" / "settings.json"


def load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set(key: str, value: Any) -> None:  # noqa: A001 (reads naturally: settings.set("x", 1))
    data = load()
    data[key] = value
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_name(PATH.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, PATH)
    except OSError:
        pass  # a read-only home folder: the choice just is not remembered
