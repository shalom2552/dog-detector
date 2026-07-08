# Dog Detector — Setup

A quick guide to get the detector running on a Windows PC.

## 1. Get `Dog Detector.exe`
If someone already gave you `Dog Detector.exe`, skip to step 2.

To build it yourself (needs Python), run this from the `launcher` folder:
```
build.bat
```
It installs PyInstaller (in a local venv), builds, and drops `Dog Detector.exe`
in the repo root next to `docker-compose.yml` — ready to use. All build files
stay under `launcher\build\`. (Linux/macOS: `./build.sh`.)

## 2. Install Docker Desktop (once)
- Download from [docker.com](https://www.docker.com/), install it, and open it once to accept the terms.
- In Docker Desktop → **Settings → General**, turn on **“Start Docker Desktop when you sign in”** so it’s ready after a reboot.

## 3. Put the app on your PC
- Copy the Dog Detector folder somewhere simple, e.g. `C:\dog-detector\`.
- Make sure `docker-compose.yml` and `Dog Detector.exe` sit **in the same folder**.

## 4. Make it easy to launch
Right-click `Dog Detector.exe` → **Send to → Desktop (create shortcut)**.

## Using it
- **Start detector** — boots Docker if needed, then starts watching. The first start after a reboot takes ~30–60s.
- **Open live view** — opens the camera view in your browser.
- **Stop detector** — stops it.

Closing the window stops it automatically.

