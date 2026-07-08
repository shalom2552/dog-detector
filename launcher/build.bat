@echo off
REM Build the launcher into a single .exe.
REM - Installs PyInstaller in a local venv (no system pip changes).
REM - Keeps all build files under launcher\build\ so they never mix with source.
REM - Drops the finished .exe in the repo root, next to docker-compose.yml,
REM   ready to run.
cd /d "%~dp0"

python -m venv build\venv
build\venv\Scripts\python -m pip install --upgrade pip pyinstaller
build\venv\Scripts\python -m PyInstaller --onefile --noconsole --name "Dog Detector" ^
  --specpath build --workpath build\work --distpath build\dist ^
  launcher.py

copy /Y "build\dist\Dog Detector.exe" "..\Dog Detector.exe"
echo Built: ..\Dog Detector.exe  (repo root, next to docker-compose.yml)
