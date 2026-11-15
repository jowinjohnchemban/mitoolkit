"""Keep a test away from the person's real settings: the phones' addresses MiToolkit remembers are written to the
settings file when a connection or pairing succeeds, so tests that mock those must not touch ~/.mitoolkit."""
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from mitoolkit import settings


def isolate_settings(case: unittest.TestCase) -> Path:
    """Point settings at an empty file in a temporary folder for the length of ``case``'s test."""
    folder = tempfile.TemporaryDirectory()
    case.addCleanup(folder.cleanup)
    path = Path(folder.name) / "settings.json"
    patcher = mock.patch.object(settings, "PATH", path)
    patcher.start()
    case.addCleanup(patcher.stop)
    return path
