"""Device details as a file: plain text, CSV (for a spreadsheet) or Markdown (for a bug report or notes).

The same rows the window shows, nothing more. They include the serial number and, in the extra
details, identifiers such as the IMEI: the person who exports decides where the file goes.
"""
from __future__ import annotations

import csv
import io
from typing import Dict, List, Sequence, Tuple

Rows = Sequence[Tuple[str, object]]
Sections = Sequence[Tuple[str, Rows]]

FORMATS: Dict[str, str] = {"txt": "Text", "csv": "CSV (spreadsheet)", "md": "Markdown"}


def _all(summary: Rows, sections: Sections, title: str) -> List[Tuple[str, Rows]]:
    out: List[Tuple[str, Rows]] = []
    rows = [(k, v) for k, v in summary if v not in (None, "")]
    if rows:
        out.append((title, rows))
    out += [(name, [(k, v) for k, v in items if v not in (None, "")]) for name, items in sections]
    return [(name, items) for name, items in out if items]


def render(fmt: str, summary: Rows, sections: Sections = (), title: str = "Summary") -> str:
    """The details in one format ("txt", "csv" or "md")."""
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format: {fmt!r}")
    groups = _all(summary, sections, title)
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["Section", "Item", "Value"])
        for name, items in groups:
            for key, value in items:
                writer.writerow([name, key, _flat(value)])
        return buf.getvalue()
    if fmt == "md":
        parts = []
        for name, items in groups:
            parts.append(f"## {name}\n\n| Item | Value |\n|---|---|")
            parts += [f"| {_cell(key)} | {_cell(value)} |" for key, value in items]
            parts.append("")
        return "# Device details\n\n" + "\n".join(parts)
    parts = []
    for name, items in groups:
        parts.append(name)
        parts += [f"  {key}: {_flat(value)}" for key, value in items]
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _flat(value: object) -> str:
    return " ".join(str(value).split())


def _cell(value: object) -> str:
    return _flat(value).replace("|", "\\|")


def suggested_name(fmt: str, device: str = "phone") -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in device.strip()).strip("-") or "phone"
    return f"{safe}-details.{fmt}"
