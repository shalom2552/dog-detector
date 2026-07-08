"""Filesystem paths, service URLs, and platform constants for the launcher."""

import os
import subprocess
import sys

# REPO_DIR holds docker-compose.yml. The frozen .exe sits in the repo root next to
# it; from source this file is launcher/paths.py, so go up two levels.
if getattr(sys, "frozen", False):
    REPO_DIR = os.path.dirname(sys.executable)
else:
    REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WEB_URL   = "http://localhost:5000"
STATE_URL = f"{WEB_URL}/state"
SOUND_URL = f"{WEB_URL}/sound"

SOUND_PATH     = os.path.join(REPO_DIR, "data", "sound.mp3")
DOCKER_DESKTOP = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
EDGE           = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# Suppress the console window subprocess would otherwise flash on Windows.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def load_env(path=os.path.join(REPO_DIR, ".env")):
    """Load KEY=VALUE lines from .env into os.environ (real env vars win over the file)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass
