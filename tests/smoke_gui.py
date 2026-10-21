"""Builds the main window and exercises the code paths behind the buttons
that open dialogs, without showing any dialog. Run on the CI build machine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402

a = app.App()
assert app.DND_FILES is not None, "drag-and-drop library failed to load"
# The method name must not shadow tkinter's internal Misc._options,
# which every file dialog and message box relies on.
assert app.App._options is app._BaseTk._options, "App overrides tkinter's _options"
opts = a._collect_options()
assert opts is not None and opts.columns, "options not collected"
a.update()
a.destroy()
print("GUI smoke test passed")
