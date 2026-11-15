"""Write the release version into src/mitoolkit/__init__.py in the CI working tree (never committed).

The git tag is the source of truth; the file in the repository only holds a floor value. Building the wheel,
the programs and the Windows file properties after this gives them all the release's version.
"""
import re
import sys
from pathlib import Path

version = sys.argv[1].lstrip("v")
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    sys.exit(f"not a major.minor.patch version: {version!r}")
path = Path("src/mitoolkit/__init__.py")
text = path.read_text(encoding="utf-8")
stamped, count = re.subn(r'^__version__ = ".*?"', f'__version__ = "{version}"', text, count=1, flags=re.M)
if count != 1:
    sys.exit("__version__ line not found")
path.write_text(stamped, encoding="utf-8")
print(f"stamped {version}")
