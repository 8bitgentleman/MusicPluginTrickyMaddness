#!/usr/bin/env bash
# Freeze the Radio Big player into a standalone binary (no Python needed to run).
# Output: dist/RadioBigPlayer/  (onedir: RadioBigPlayer exe + _internal/).
# Requires: pip install pyinstaller   (build-time only; nothing extra ships).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

rm -rf build dist RadioBigPlayer.spec
pyinstaller --onedir --noconfirm --clean --name RadioBigPlayer \
  --collect-submodules pygame \
  --hidden-import dj_brain --hidden-import dj_library --hidden-import radio_player \
  radio_server.py

echo "frozen -> $HERE/dist/RadioBigPlayer"
