"""Write the Windows version resource (File properties > Details: product, version, copyright) for PyInstaller.

A program that says who made it and which version it is looks less like malware to Windows and to antivirus
tools than an anonymous one. The release workflow runs this on Windows:

    python packaging/make_version_file.py > packaging/version_info.txt
"""
import re
from pathlib import Path

version = re.search(r'__version__ = "(.+?)"', (Path(__file__).parent.parent / "src/mitoolkit/__init__.py").read_text()).group(1)
numbers = tuple(int(x) for x in version.split(".")) + (0,) * 4
quad = numbers[:4]

print(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={quad}, prodvers={quad}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Jowin John Chemban'),
      StringStruct('FileDescription', 'mitoolkit: unlock and look after Xiaomi, Redmi and POCO phones'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'mitoolkit'),
      StringStruct('LegalCopyright', 'Apache License 2.0'),
      StringStruct('OriginalFilename', 'mitoolkit.exe'),
      StringStruct('ProductName', 'mitoolkit'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)""")
