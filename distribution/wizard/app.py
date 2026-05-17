from __future__ import annotations

import json
import subprocess
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from . import detect, env_writer

DIST_DIR = Path(__file__).parent.parent
CONFIG_FILE = Path.home() / ".verdikt_tray.json"

COMPOSE_MAP = {
    "native": "compose.native-ollama.yml",
    "docker": "compose.docker-ollama.yml",
    "none":   "compose.no-ollama.yml",
}

STEPS = ["Welcome", "Prerequisites", "Model Backend", "Port", "Data Folder", "Install"]

_PRIMARY = "#6b7de0"
_BG      = "white"
_SUBTLE  = "#f5f5f5"
_TEXT    = "#1a1a1a"
_MUTED   = "#666"
_RED     = "#c00"
_GREEN   = "#1a7a1a"


class WizardApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Verdikt Setup")
        self.root.resizable(False, False)
        self.root.geometry("560x460")
        self.root.configure(bg=_BG)

        # Wizard answers
        self.compose_choice: str = "native"
        self.pull_llm: bool = True
        self.port: int = 8765
        self.data_dir: str = str(Path.home() / "VerdiktData")

        # Detection results
        self.docker_ok: bool = False
        self.docker_version: str = ""
        self.ollama_found: bool = False
        self.nvidia_found: bool = False

        self._step: int = 0
        self._build_chrome()
        self._show_step()

    def run(self) -> None:
        self.root.mainloop()

    # ------------------------------------------------------------------ chrome

    def _build_chrome(self) -> None:
        hdr = tk.Frame(self.root, bg=_PRIMARY, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="Verdikt", bg=_PRIMARY, fg="white",
                 font=("Helvetica", 18, "bold")).pack(side="left", padx=20, pady=12)
        self._step_label = tk.Label(hdr, text="", bg=_PRIMARY, fg="white",
                                     font=("Helvetica", 11))
        self._step_label.pack(side="right", padx=20)

        self.content = tk.Frame(self.root, bg=_BG, padx=28, pady=18)
        self.content.pack(fill="both", expand=True)

        ftr = tk.Frame(self.root, bg=_SUBTLE, height=56)
        ftr.pack(fill="x")
        ftr.pack_propagate(False)

        self.back_btn = tk.Button(
            ftr, text="← Back", command=self._back, width=10,
            relief="flat", bg=_SUBTLE, fg=_TEXT, activebackground="#ddd", cursor="hand2",
        )
        self.back_btn.pack(side="left", padx=16, pady=12)

        self.next_btn = tk.Button(
            ftr, text="Next →", command=self._next, width=12,
            relief="flat", bg=_PRIMARY, fg="white", activebackground="#5566cc",
            cursor="hand2", font=("Helvetica", 11, "bold"),
        )
        self.next_btn.pack(side="right", padx=16, pady=12)

        self._dots = tk.Frame(ftr, bg=_SUBTLE)
        self._dots.pack(side="left", padx=4)

    def _refresh_chrome(self) -> None:
        self._step_label.config(text=f"Step {self._step + 1} of {len(STEPS)}")
        for w in self._dots.winfo_children():
            w.destroy()
        for i in range(len(STEPS)):
            c = _PRIMARY if i <= self._step else "#ccc"
            tk.Label(self._dots, text="●", fg=c, bg=_SUBTLE,
                     font=("Helvetica", 9)).pack(side="left")
        self.back_btn.config(state="disabled" if self._step == 0 else "normal")
        self.next_btn.config(
            text="Install" if self._step == len(STEPS) - 1 else "Next →",
        )

    def _clear(self) -> None:
        for w in self.content.winfo_children():
            w.destroy()

    # ------------------------------------------------------------------ nav

    def _show_step(self) -> None:
        self._refresh_chrome()
        self._clear()
        [
            self._s0_welcome,
            self._s1_prereqs,
            self._s2_backend,
            self._s3_port,
            self._s4_datadir,
            self._s5_install,
        ][self._step]()

    def _back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._show_step()

    def _next(self) -> None:
        if self._step == len(STEPS) - 1:
            self._do_install()
            return

        if self._step == 1 and not self.docker_ok:
            messagebox.showerror(
                "Docker Required",
                "Docker is not running.\n\nInstall Docker Desktop and make sure it is started, then try again.",
            )
            return

        if self._step == 3:
            try:
                p = int(self._port_var.get())
                if not (1024 <= p <= 65535):
                    raise ValueError
                self.port = p
            except ValueError:
                messagebox.showerror("Invalid Port", "Enter a number between 1024 and 65535.")
                return

        if self._step == 4:
            d = self._datadir_var.get().strip()
            err = env_writer.validate_data_dir(d)
            if err:
                self._datadir_error.config(text=err)
                return
            self.data_dir = d

        self._step += 1
        self._show_step()

    # ------------------------------------------------------------------ helpers

    def _h(self, parent: tk.Widget, text: str, size: int = 16) -> tk.Label:
        return tk.Label(parent, text=text, bg=_BG, fg=_TEXT,
                        font=("Helvetica", size, "bold"), anchor="w", justify="left")

    def _p(self, parent: tk.Widget, text: str, **kw) -> tk.Label:
        kw.setdefault("fg", _TEXT)
        return tk.Label(parent, text=text, bg=_BG, anchor="w", justify="left",
                        wraplength=500, **kw)

    # ------------------------------------------------------------------ steps

    def _s0_welcome(self) -> None:
        self._h(self.content, "Welcome to Verdikt", size=20).pack(anchor="w", pady=(0, 12))
        self._p(
            self.content,
            "This wizard will configure and start Verdikt on your machine.\n\n"
            "Verdikt is a local-first preference learning platform — all your data "
            "stays on your device and is encrypted at rest.\n\n"
            "You will need Docker Desktop installed and running.\n"
            "Ollama is optional but recommended for local AI features.",
            font=("Helvetica", 12),
        ).pack(anchor="w")

    def _s1_prereqs(self) -> None:
        self._h(self.content, "Checking prerequisites…").pack(anchor="w", pady=(0, 14))
        self._docker_lbl = self._p(self.content, "⏳  Checking Docker…",
                                    font=("Helvetica", 12))
        self._docker_lbl.pack(anchor="w", pady=4)
        self._ollama_lbl = self._p(self.content, "⏳  Checking Ollama…",
                                    font=("Helvetica", 12))
        self._ollama_lbl.pack(anchor="w", pady=4)

        def _run() -> None:
            ok, ver = detect.detect_docker()
            self.docker_ok = ok
            self.docker_version = ver
            self.ollama_found = detect.detect_ollama()
            self.nvidia_found = detect.detect_nvidia_gpu()

            docker_txt = f"✅  Docker {ver}" if ok else "❌  Docker not found — install Docker Desktop first"
            docker_fg  = _TEXT if ok else _RED
            ollama_txt = ("✅  Ollama running locally"
                          if self.ollama_found
                          else "ℹ️   Ollama not detected (you can run it in Docker)")

            self.root.after(0, lambda: self._docker_lbl.config(text=docker_txt, fg=docker_fg))
            self.root.after(0, lambda: self._ollama_lbl.config(text=ollama_txt))

        threading.Thread(target=_run, daemon=True).start()

    def _s2_backend(self) -> None:
        self._h(self.content, "AI Model Backend").pack(anchor="w", pady=(0, 8))
        self._p(self.content, "How should Verdikt access language models?",
                fg=_MUTED).pack(anchor="w", pady=(0, 12))

        var = tk.StringVar(value="native" if self.ollama_found else "docker")

        options = [
            ("native",
             "Use Ollama already installed on this machine",
             "Recommended — fastest; all models stay local"),
            ("docker",
             "Run Ollama inside Docker",
             "Downloads the Ollama image (~4 GB)"
             + (" — NVIDIA GPU detected ✓" if self.nvidia_found else "")),
            ("none",
             "Cloud AI only (Venice / OpenRouter)",
             "No local models — configure API keys in Admin after setup"),
        ]

        for val, label, sub in options:
            row = tk.Frame(self.content, bg=_BG)
            row.pack(fill="x", pady=3)
            rb = tk.Radiobutton(
                row, variable=var, value=val, bg=_BG, activebackground=_BG, cursor="hand2",
                command=lambda v=var: setattr(self, "compose_choice", v.get()),
            )
            rb.pack(side="left")
            txt = tk.Frame(row, bg=_BG)
            txt.pack(side="left", fill="x")
            tk.Label(txt, text=label, bg=_BG, fg=_TEXT, font=("Helvetica", 11, "bold"),
                     anchor="w").pack(anchor="w")
            tk.Label(txt, text=sub, bg=_BG, fg=_MUTED, font=("Helvetica", 10),
                     anchor="w").pack(anchor="w")

        self.compose_choice = var.get()

        if self.ollama_found:
            pull_row = tk.Frame(self.content, bg=_BG)
            pull_row.pack(fill="x", pady=(10, 0))
            pv = tk.BooleanVar(value=True)
            tk.Checkbutton(
                pull_row, variable=pv, bg=_BG, activebackground=_BG, cursor="hand2",
                command=lambda: setattr(self, "pull_llm", pv.get()),
            ).pack(side="left")
            tk.Label(pull_row, text="Pull default LLM now  (llama3.1:8b, ~5 GB)",
                     bg=_BG, fg=_TEXT).pack(side="left")

    def _s3_port(self) -> None:
        self._h(self.content, "Network Port").pack(anchor="w", pady=(0, 8))
        self._p(self.content, "Verdikt will be accessible at  http://localhost:<port>",
                fg=_MUTED).pack(anchor="w", pady=(0, 14))

        row = tk.Frame(self.content, bg=_BG)
        row.pack(fill="x")
        tk.Label(row, text="Port:", bg=_BG, fg=_TEXT).pack(side="left")
        self._port_var = tk.StringVar(value=str(self.port))
        tk.Entry(row, textvariable=self._port_var, width=8,
                 font=("Helvetica", 12)).pack(side="left", padx=10)

        self._p(self.content, "Default: 8765.  Change only if that port is already in use.",
                fg=_MUTED, font=("Helvetica", 10)).pack(anchor="w", pady=(10, 0))

    def _s4_datadir(self) -> None:
        self._h(self.content, "Data Folder").pack(anchor="w", pady=(0, 8))
        self._p(
            self.content,
            "Verdikt will store all encrypted user data here.\n"
            "Choose a new or empty folder — Verdikt manages everything inside it.",
            fg=_MUTED,
        ).pack(anchor="w", pady=(0, 14))

        row = tk.Frame(self.content, bg=_BG)
        row.pack(fill="x")
        self._datadir_var = tk.StringVar(value=self.data_dir)
        tk.Entry(row, textvariable=self._datadir_var, width=38,
                 font=("Helvetica", 11)).pack(side="left")

        def _browse() -> None:
            d = filedialog.askdirectory(initialdir=str(Path.home()))
            if d:
                self._datadir_var.set(d)
                self._datadir_error.config(text="")

        tk.Button(row, text="Browse…", command=_browse, relief="flat",
                  bg=_SUBTLE, fg=_TEXT, cursor="hand2").pack(side="left", padx=8)

        self._datadir_error = tk.Label(
            self.content, text="", bg=_BG, fg=_RED,
            font=("Helvetica", 10), wraplength=500, justify="left",
        )
        self._datadir_error.pack(anchor="w", pady=(6, 0))

    def _s5_install(self) -> None:
        self._h(self.content, "Ready to Install").pack(anchor="w", pady=(0, 12))

        rows = [
            ("Model backend:", COMPOSE_MAP[self.compose_choice]),
            ("Port:", str(self.port)),
            ("Data folder:", self.data_dir),
        ]
        if self.compose_choice == "native" and self.pull_llm:
            rows.append(("Model pull:", "llama3.1:8b  (~5 GB, after start)"))

        for k, v in rows:
            r = tk.Frame(self.content, bg=_BG)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=k, bg=_BG, fg=_MUTED, width=16, anchor="w").pack(side="left")
            tk.Label(r, text=v, bg=_BG, fg=_TEXT,
                     font=("Helvetica", 11, "bold"), anchor="w").pack(side="left")

        self._progress = ttk.Progressbar(self.content, mode="indeterminate", length=480)
        self._status_lbl = tk.Label(self.content, text="", bg=_BG, fg=_MUTED,
                                     font=("Helvetica", 10), wraplength=500, justify="left")

    # ------------------------------------------------------------------ install

    def _do_install(self) -> None:
        self.back_btn.config(state="disabled")
        self.next_btn.config(state="disabled")
        self._progress.pack(pady=(18, 4))
        self._progress.start(10)
        self._status_lbl.pack(anchor="w")

        compose_name = COMPOSE_MAP[self.compose_choice]
        compose_path = str(DIST_DIR / compose_name)

        def _run() -> None:
            try:
                self._status("Writing configuration…")
                env_writer.write_env(
                    compose_file=compose_name,
                    port=self.port,
                    data_dir=self.data_dir,
                    dist_dir=DIST_DIR,
                )

                self._status("Pulling Verdikt image…")
                subprocess.run(
                    ["docker", "compose", "-f", compose_path, "pull"],
                    cwd=str(DIST_DIR), check=True, capture_output=True,
                )

                self._status("Starting Verdikt…")
                subprocess.run(
                    ["docker", "compose", "-f", compose_path, "up", "-d"],
                    cwd=str(DIST_DIR), check=True, capture_output=True,
                )

                if self.compose_choice == "native" and self.pull_llm:
                    self._status("Pulling llama3.1:8b — this may take several minutes…")
                    subprocess.run(["ollama", "pull", "llama3.1:8b"], check=False)

                (Path.home() / ".verdikt_tray.json").write_text(
                    json.dumps({
                        "compose_file": compose_path,
                        "distribution_dir": str(DIST_DIR),
                        "port": self.port,
                    }, indent=2)
                )

                self.root.after(0, self._install_done)

            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.decode(errors="replace") if exc.stderr else str(exc)
                self.root.after(0, lambda msg=stderr: self._install_error(msg))

        threading.Thread(target=_run, daemon=True).start()

    def _status(self, msg: str) -> None:
        self.root.after(0, lambda: self._status_lbl.config(text=msg))

    def _install_done(self) -> None:
        self._progress.stop()
        self._progress.pack_forget()
        self._clear()

        self._h(self.content, "✅  Verdikt is running!", size=16).pack(anchor="w", pady=(0, 12))
        self._p(
            self.content,
            f"Open your browser at  http://localhost:{self.port}\n\n"
            "Create your admin account on first launch.\n\n"
            "Use the Verdikt tray icon to start, stop, and reopen the app.",
            font=("Helvetica", 12),
        ).pack(anchor="w")

        tk.Button(
            self.content,
            text=f"Open Verdikt  →  http://localhost:{self.port}",
            command=lambda: webbrowser.open(f"http://localhost:{self.port}"),
            relief="flat", bg=_PRIMARY, fg="white",
            font=("Helvetica", 12, "bold"), cursor="hand2", padx=16, pady=8,
        ).pack(pady=(16, 0))

        self.next_btn.config(state="disabled")
        self.back_btn.config(state="disabled")

    def _install_error(self, msg: str) -> None:
        self._progress.stop()
        self._progress.pack_forget()
        self._status_lbl.config(
            text=f"Install failed:\n{msg[:400]}", fg=_RED,
        )
        self.next_btn.config(state="normal", text="Retry")
        self.back_btn.config(state="normal")
