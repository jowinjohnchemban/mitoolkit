"""Entry point used by PyInstaller. One program: GUI by default, command line with --cli."""
import mitoolkit.gui
from mitoolkit.cli import main

# The CLI imports the GUI lazily, which PyInstaller cannot see; naming the module here keeps it in the program.
BUNDLED = (mitoolkit.gui,)

if __name__ == "__main__":
    main()
