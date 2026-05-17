from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class DockerManager:
    def __init__(self, compose_file: str, project_dir: str | None = None, port: int = 8765) -> None:
        self._compose_file = compose_file
        self._project_dir  = project_dir or str(Path(compose_file).parent)
        self._port         = port

    def _cmd(self, *args: str) -> list[str]:
        return ["docker", "compose", "-f", self._compose_file, *args]

    def start(self) -> None:
        subprocess.Popen(
            self._cmd("up", "-d"),
            cwd=self._project_dir,
        )

    def stop(self) -> None:
        subprocess.run(
            self._cmd("down"),
            cwd=self._project_dir,
            check=False,
            capture_output=True,
        )

    def restart(self) -> None:
        self.stop()
        self.start()

    def is_running(self) -> bool:
        result = subprocess.run(
            self._cmd("ps", "--services", "--filter", "status=running"),
            cwd=self._project_dir,
            capture_output=True,
            text=True,
        )
        return "verdikt" in result.stdout

    def open_logs(self, tail: int = 200) -> None:
        cmd = self._cmd("logs", f"--tail={tail}", "-f")
        if sys.platform == "win32":
            subprocess.Popen(
                ["cmd", "/c", "start", "cmd", "/k", " ".join(cmd)],
                cwd=self._project_dir,
            )
        elif sys.platform == "darwin":
            script = (
                'tell application "Terminal" to do script'
                f' "cd {self._project_dir!r} && {" ".join(cmd)}"'
            )
            subprocess.Popen(["osascript", "-e", script])
        else:
            for term in ["gnome-terminal", "xterm", "xfce4-terminal", "konsole"]:
                try:
                    subprocess.Popen([term, "--"] + cmd, cwd=self._project_dir)
                    return
                except FileNotFoundError:
                    continue
            # Fallback: just run in background and hope for the best
            subprocess.Popen(cmd, cwd=self._project_dir)
