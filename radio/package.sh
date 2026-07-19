#!/usr/bin/env bash
# Assemble the shippable Radio Big drop-in: the bridge DLL + the frozen player +
# all the audio, laid out exactly as the plugin expects under BepInEx/plugins/.
#
# Prereqs (run these first):
#   RadioBigPlugin/build.sh --mac                 # -> RadioBigTM.dll
#   pyinstaller ... radio_server.py               # -> dist/RadioBigPlayer/  (see freeze.sh)
#
# Usage: ./package.sh [output-dir]
# macOS ships bash 3.2 — keep this 3.2-safe (no assoc arrays / ${x,,}).
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/_release/RadioBig - Tricky Madness Mod}"

PLAYER_SRC="$HERE/dist/RadioBigPlayer"
DLL="$HERE/RadioBigPlugin/RadioBigTM.dll"
DJ_SRC="/Users/mtvogel/Downloads/claude_scratch/Radio_Big/Radio_Big_Sections"
SSX3_SRC="/Users/mtvogel/Documents/PythonScripts/youtube-dl/SSX 3 [Soundtrack⧸Gamerip]"
TRICKY_SRC="/Users/mtvogel/Documents/PythonScripts/youtube-dl/SSX Tricky (Complete Soundtrack OST)"

for p in "$PLAYER_SRC/RadioBigPlayer" "$DLL" "$DJ_SRC" "$SSX3_SRC" "$TRICKY_SRC"; do
  [ -e "$p" ] || { echo "missing prerequisite: $p" >&2; exit 1; }
done

echo "staging -> $OUT"
rm -rf "$OUT"
mkdir -p "$OUT/RadioBig/player" \
         "$OUT/RadioBig/assets/dj" \
         "$OUT/RadioBig/assets/ssx3" \
         "$OUT/RadioBig/assets/tricky"

cp "$DLL" "$OUT/RadioBigTM.dll"
cp "$HERE/RELEASE_README.md" "$OUT/README.md"
cp -R "$PLAYER_SRC/." "$OUT/RadioBig/player/"

echo "  copying DJ voice clips…";  cp "$DJ_SRC"/*.mp3     "$OUT/RadioBig/assets/dj/"
echo "  copying SSX3 soundtrack…"; cp "$SSX3_SRC"/*.mp3   "$OUT/RadioBig/assets/ssx3/"
echo "  copying Tricky soundtrack…"; cp "$TRICKY_SRC"/*.mp3 "$OUT/RadioBig/assets/tricky/"

# Best-effort: clear quarantine so the unsigned player runs locally without a prompt.
xattr -dr com.apple.quarantine "$OUT/RadioBig/player" 2>/dev/null || true

echo "done."
printf 'dj=%s  ssx3=%s  tricky=%s clips\n' \
  "$(ls "$OUT/RadioBig/assets/dj"/*.mp3 | wc -l | tr -d ' ')" \
  "$(ls "$OUT/RadioBig/assets/ssx3"/*.mp3 | wc -l | tr -d ' ')" \
  "$(ls "$OUT/RadioBig/assets/tricky"/*.mp3 | wc -l | tr -d ' ')"
du -sh "$OUT"
