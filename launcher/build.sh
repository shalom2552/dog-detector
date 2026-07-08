#!/usr/bin/env bash
# Build the launcher into a single binary.
# - Installs PyInstaller in a local venv (no system pip changes; works on
#   PEP 668 distros like Arch).
# - Keeps all build files under launcher/build/ so they never mix with source.
# - Drops the finished binary in the repo root, next to docker-compose.yml,
#   ready to run.
set -e
cd "$(dirname "$0")"

python -m venv build/venv
build/venv/bin/python -m pip install --upgrade pip pyinstaller
build/venv/bin/python -m PyInstaller --onefile --noconsole --name "Dog Detector" \
  --specpath build --workpath build/work --distpath build/dist \
  launcher.py

cp "build/dist/Dog Detector" ".."
echo "Built: ../Dog Detector  (repo root, next to docker-compose.yml)"
