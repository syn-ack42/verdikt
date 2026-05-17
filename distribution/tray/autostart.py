from __future__ import annotations

import sys
from pathlib import Path


def register_autostart(exe_path: str) -> None:
    """Register the tray executable to start at login."""
    if sys.platform == "win32":
        _windows_register(exe_path)
    elif sys.platform == "darwin":
        _macos_register(exe_path)
    else:
        _linux_register(exe_path)


def unregister_autostart() -> None:
    """Remove the autostart registration."""
    if sys.platform == "win32":
        _windows_unregister()
    elif sys.platform == "darwin":
        _macos_unregister()
    else:
        _linux_unregister()


# ------------------------------------------------------------------ Windows

def _windows_register(exe: str) -> None:
    import winreg
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0, winreg.KEY_SET_VALUE,
    )
    winreg.SetValueEx(key, "VerdiktTray", 0, winreg.REG_SZ, exe)
    winreg.CloseKey(key)


def _windows_unregister() -> None:
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.DeleteValue(key, "VerdiktTray")
        winreg.CloseKey(key)
    except FileNotFoundError:
        pass


# ------------------------------------------------------------------ macOS

def _macos_register(exe: str) -> None:
    plist = Path.home() / "Library" / "LaunchAgents" / "com.verdikt.tray.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"'
        ' "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        '    <key>Label</key>\n'
        '    <string>com.verdikt.tray</string>\n'
        '    <key>Program</key>\n'
        f'    <string>{exe}</string>\n'
        '    <key>RunAtLoad</key>\n'
        '    <true/>\n'
        '    <key>KeepAlive</key>\n'
        '    <false/>\n'
        '</dict>\n'
        '</plist>\n'
    )


def _macos_unregister() -> None:
    import subprocess
    plist = Path.home() / "Library" / "LaunchAgents" / "com.verdikt.tray.plist"
    if plist.exists():
        subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
        plist.unlink()


# ------------------------------------------------------------------ Linux (XDG)

def _linux_register(exe: str) -> None:
    desktop = Path.home() / ".config" / "autostart" / "verdikt-tray.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Verdikt Tray\n"
        f"Exec={exe}\n"
        "Hidden=false\n"
        "NoDisplay=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def _linux_unregister() -> None:
    desktop = Path.home() / ".config" / "autostart" / "verdikt-tray.desktop"
    if desktop.exists():
        desktop.unlink()
