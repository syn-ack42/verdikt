# Verdikt Distribution

Cross-platform installer and system-tray launcher for Verdikt.

## Quick install

**Linux**
```bash
bash installers/linux/install.sh
```

**macOS / Windows** — run the installer package produced by the build scripts, or launch the wizard manually:
```bash
cd distribution
python3 -m wizard
```

---

## Compose variants

| File | When to use |
|------|-------------|
| `compose.native-ollama.yml` | Ollama installed natively on this machine |
| `compose.docker-ollama.yml` | No local Ollama; runs Ollama inside Docker |
| `compose.no-ollama.yml` | Cloud AI only — configure Venice / OpenRouter in Admin |

All variants read a `.env` file in this directory (auto-loaded by Docker Compose).
The wizard generates it; see `wizard/env_writer.py` for the format.

---

## Setup wizard (GUI)

Requires Python 3.9+ and tkinter (ships with macOS/Windows Python; on Linux: `sudo apt install python3-tk`).

```bash
cd distribution
python3 -m wizard
```

Steps:
1. Checks Docker is running
2. Detects Ollama and NVIDIA GPU, offers model backend choice
3. Port selection (default 8765)
4. Data folder — must be empty; Verdikt manages all encrypted data inside it
5. Pulls image, starts stack, writes `~/.verdikt_tray.json`

---

## System tray launcher

```bash
pip install pystray Pillow
cd distribution
python3 -m tray
```

Reads `~/.verdikt_tray.json` (written by the wizard or `install.sh`).
Menu: **Open Verdikt · Start · Stop · Restart · Open Logs · Quit**
Icon is green when the container is running, grey when stopped.

---

## Building distributable packages

### Windows (Inno Setup 6)

```cmd
cd distribution
pip install pyinstaller
pyinstaller --onefile --windowed --name VerdiktTray   tray\__main__.py
pyinstaller --onefile --windowed --name VerdiktWizard wizard\__main__.py
iscc installers\windows\verdikt.iss
```

Output: `Output\VerdiktSetup.exe`

### macOS

```bash
pip install pyinstaller
cd distribution
bash installers/macos/build.sh
```

Output: `build/Verdikt-<VERSION>.pkg`

### Linux

No binary build needed — `install.sh` installs the Python source directly and sets up a systemd user service for the tray.

---

## Manual operations

```bash
# Start
docker compose -f distribution/compose.native-ollama.yml up -d

# Stop
docker compose -f distribution/compose.native-ollama.yml down

# Logs
docker compose -f distribution/compose.native-ollama.yml logs -f

# Upgrade (pull latest image)
docker compose -f distribution/compose.native-ollama.yml pull
docker compose -f distribution/compose.native-ollama.yml up -d
```
