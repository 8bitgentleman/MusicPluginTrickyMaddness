#!/usr/bin/env bash
# Freeze the Radio Big player into a WINDOWS .exe from macOS, using CrossOver's
# bundled Wine to run a Windows Python + PyInstaller. No Windows machine needed.
# Output: dist-windows/RadioBigPlayer/  (RadioBigPlayer.exe + _internal/).
#
# PyInstaller can't cross-compile — it bundles the HOST OS's Python/libs. So we
# run a real Windows Python under Wine and let it freeze a real Windows PE. Wine-
# built PyInstaller binaries run on native Windows (verified: boots pygame, serves
# IPC, resolves assets under Wine — a good proxy for real Windows).
#
# Prereqs: CrossOver installed with a bottle (default "Steam"). One-time bootstrap
# (Python embeddable + pip + pygame + pyinstaller) runs automatically if absent.
# macOS ships bash 3.2 — keep this 3.2-safe.
set -eu

WINE="${WINE:-/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine}"
BOTTLE="${CX_BOTTLE:-Steam}"
PYVER="${PYVER:-3.12.8}"
HERE="$(cd "$(dirname "$0")" && pwd)"
DRIVE="$HOME/Library/Application Support/CrossOver/Bottles/$BOTTLE/drive_c"

[ -x "$WINE" ] || { echo "CrossOver wine not found at $WINE" >&2; exit 1; }
[ -d "$DRIVE" ] || { echo "bottle '$BOTTLE' not found ($DRIVE)" >&2; exit 1; }

run() { CX_BOTTLE="$BOTTLE" "$WINE" "$@"; }

# --- one-time: a self-contained Windows Python 3.12 + pip in the bottle ------
# The embeddable zip (no MSI installer — those silently no-op under Wine) plus a
# pip bootstrap. Enabling `import site` + a site-packages line is what lets pip
# and the installed packages import.
if [ ! -f "$DRIVE/py312/python.exe" ]; then
  echo "[freeze-win] bootstrapping Windows Python $PYVER in bottle '$BOTTLE'..."
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/embed.zip" \
    "https://www.python.org/ftp/python/$PYVER/python-3.12.8-embed-amd64.zip"
  curl -fsSL -o "$tmp/get-pip.py" https://bootstrap.pypa.io/get-pip.py
  rm -rf "$DRIVE/py312"; mkdir -p "$DRIVE/py312"
  unzip -oq "$tmp/embed.zip" -d "$DRIVE/py312"
  cp "$tmp/get-pip.py" "$DRIVE/py312/get-pip.py"
  printf 'python312.zip\n.\nLib\\site-packages\n\nimport site\n' \
    > "$DRIVE/py312/python312._pth"
  run 'C:\py312\python.exe' 'C:\py312\get-pip.py' --no-warn-script-location
  rm -rf "$tmp"
fi

echo "[freeze-win] ensuring pygame + pyinstaller..."
run 'C:\py312\python.exe' -m pip install --no-warn-script-location \
  pygame pyinstaller >/dev/null

# --- stage the source in the bottle and freeze -------------------------------
rm -rf "$DRIVE/rbbuild"; mkdir -p "$DRIVE/rbbuild"
cp "$HERE/radio_server.py" "$HERE/dj_brain.py" \
   "$HERE/dj_library.py"  "$HERE/radio_player.py" "$DRIVE/rbbuild/"

echo "[freeze-win] running PyInstaller under Wine..."
run 'C:\py312\python.exe' -m PyInstaller \
  --onedir --noconfirm --clean --name RadioBigPlayer \
  --collect-submodules pygame \
  --hidden-import dj_brain --hidden-import dj_library --hidden-import radio_player \
  --distpath 'C:\rbbuild\dist' --workpath 'C:\rbbuild\build' --specpath 'C:\rbbuild' \
  'C:\rbbuild\radio_server.py'

OUT="$HERE/dist-windows"
rm -rf "$OUT"; mkdir -p "$OUT"
cp -R "$DRIVE/rbbuild/dist/RadioBigPlayer" "$OUT/RadioBigPlayer"
xattr -cr "$OUT" 2>/dev/null || true

[ -f "$OUT/RadioBigPlayer/RadioBigPlayer.exe" ] \
  || { echo "freeze produced no .exe" >&2; exit 1; }
echo "frozen (windows) -> $OUT/RadioBigPlayer/RadioBigPlayer.exe"
