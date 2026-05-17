"""Entry point: python -m tray  (run from distribution/)"""
try:
    import pystray   # noqa: F401
    from PIL import Image  # noqa: F401
except ImportError:
    print(
        "Missing dependencies. Install with:\n"
        "  pip install pystray Pillow"
    )
    raise SystemExit(1)

from .launcher import run

run()
