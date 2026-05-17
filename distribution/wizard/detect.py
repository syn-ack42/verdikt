from __future__ import annotations

import subprocess
import urllib.request


def detect_docker() -> tuple[bool, str]:
    """Return (is_running, version_string)."""
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=5,
        )
        version = result.stdout.strip()
        return bool(version), version
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""


def detect_ollama() -> bool:
    """Return True if Ollama is reachable on localhost:11434."""
    try:
        urllib.request.urlopen("http://localhost:11434/api/version", timeout=1)
        return True
    except Exception:
        return False


def detect_nvidia_gpu() -> bool:
    """Return True if nvidia-smi reports at least one GPU."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
