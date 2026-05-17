from __future__ import annotations

import json
import sys
import threading
import time
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from .docker_manager import DockerManager

CONFIG_FILE = Path.home() / ".verdikt_tray.json"
_POLL_INTERVAL = 10  # seconds


def _make_icon(running: bool) -> Image.Image:
    """Programmatic tray icon: indigo V on green (running) or grey (stopped) disc."""
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg = (80, 180, 80, 255) if running else (150, 150, 150, 255)
    draw.ellipse([2, 2, size - 2, size - 2], fill=bg)

    # Simple V shape
    pts = [
        (14, 16), (22, 16), (32, 40), (42, 16), (50, 16),
        (34, 52), (30, 52),
    ]
    draw.polygon(pts, fill=(255, 255, 255, 230))
    return img


def run() -> None:
    if not CONFIG_FILE.exists():
        print(
            "Verdikt tray: no config at ~/.verdikt_tray.json\n"
            "Run the Verdikt Setup Wizard first.",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg          = json.loads(CONFIG_FILE.read_text())
    compose_file = cfg["compose_file"]
    dist_dir     = cfg.get("distribution_dir", str(Path(compose_file).parent))
    port         = cfg.get("port", 8765)

    manager    = DockerManager(compose_file=compose_file, project_dir=dist_dir, port=port)
    _running   = [manager.is_running()]
    _icon_ref  : list[pystray.Icon | None] = [None]

    def _refresh() -> None:
        status = manager.is_running()
        _running[0] = status
        icon = _icon_ref[0]
        if icon is not None:
            icon.icon  = _make_icon(status)
            icon.title = "Verdikt — running" if status else "Verdikt — stopped"

    def _poll() -> None:
        while True:
            time.sleep(_POLL_INTERVAL)
            try:
                _refresh()
            except Exception:
                pass

    def on_open(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        webbrowser.open(f"http://localhost:{port}")

    def on_start(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        manager.start()
        threading.Timer(3.0, _refresh).start()

    def on_stop(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        manager.stop()
        threading.Timer(2.0, _refresh).start()

    def on_restart(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        manager.restart()
        threading.Timer(5.0, _refresh).start()

    def on_logs(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        manager.open_logs()

    def on_quit(icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Verdikt", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start",   on_start),
        pystray.MenuItem("Stop",    on_stop),
        pystray.MenuItem("Restart", on_restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Logs", on_logs),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon(
        "Verdikt",
        icon=_make_icon(_running[0]),
        title="Verdikt — running" if _running[0] else "Verdikt — stopped",
        menu=menu,
    )
    _icon_ref[0] = icon

    threading.Thread(target=_poll, daemon=True).start()
    icon.run()
