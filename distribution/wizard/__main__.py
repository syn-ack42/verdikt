"""Entry point: python -m wizard  (run from distribution/)"""
try:
    import tkinter  # noqa: F401
except ImportError:
    print(
        "tkinter is not installed.\n"
        "  Debian/Ubuntu:  sudo apt install python3-tk\n"
        "  Fedora:         sudo dnf install python3-tkinter\n"
        "  macOS/Windows:  tkinter ships with the standard Python installer."
    )
    raise SystemExit(1)

from .app import WizardApp

WizardApp().run()
