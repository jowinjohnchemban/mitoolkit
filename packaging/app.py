"""Entry point used by PyInstaller. One program: GUI by default, command line with --cli."""
import mitoolkit.gui  # noqa: F401  (imported lazily by the CLI, so tell PyInstaller about it)
from mitoolkit.cli import main

if __name__ == "__main__":
    main()
