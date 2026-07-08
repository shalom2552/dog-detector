"""Dog Detector launcher — entry point. GUI in gui.py, Docker control in
docker_ctl.py, paths/URLs in paths.py.

Build to a single .exe:
    python -m PyInstaller --onefile --noconsole --name "Dog Detector" launcher.py
"""

from paths import load_env
from gui import Launcher

if __name__ == "__main__":
    load_env()  # .env -> os.environ before anything reads credentials
    Launcher().mainloop()
