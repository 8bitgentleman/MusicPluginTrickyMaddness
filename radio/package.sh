#!/usr/bin/env bash
# Assemble the shippable Radio Big drop-in — one release tree that installs on
# Windows, macOS, and Linux. The bridge DLL and the audio are shared across all
# platforms; only the frozen player differs, so each OS's freeze lands in its own
# players/<os>/ subdir and the plugin picks the matching one at launch. The full
# Python + C# source ships under source/ so any platform (incl. Linux) can run
# from source or re-freeze.
#
# Prereqs (build whatever platforms you want to ship; missing ones are skipped
# with a warning, not an error):
#   RadioBigPlugin/build.sh --mac     # -> RadioBigTM.dll        (portable, required)
#   ./freeze.sh                       # -> dist/RadioBigPlayer/          (mac-arm64)
#   ./freeze_windows.sh               # -> dist-windows/RadioBigPlayer/  (windows)
#
# Usage: ./package.sh [output-dir]
# macOS ships bash 3.2 — keep this 3.2-safe (no assoc arrays / ${x,,}).
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/_release/RadioBig - Tricky Madness Mod}"

DLL="$HERE/RadioBigPlugin/RadioBigTM.dll"
MAC_SRC="$HERE/dist/RadioBigPlayer"
WIN_SRC="$HERE/dist-windows/RadioBigPlayer"

# Audio source. The canonical store is the live game install's bundled assets —
# a full standalone copy — so the original dev-path rips can be deleted without
# breaking a re-package. Override with RADIO_BIG_ASSETS_SRC if it lives elsewhere.
ASSETS_SRC="${RADIO_BIG_ASSETS_SRC:-$HOME/Library/Application Support/Steam/steamapps/common/Tricky Madness/BepInEx/plugins/RadioBig/assets}"
DJ_SRC="$ASSETS_SRC/dj"
SSX3_SRC="$ASSETS_SRC/ssx3"
TRICKY_SRC="$ASSETS_SRC/tricky"

# Required prerequisites (the DLL + the audio); players are per-OS and optional.
for p in "$DLL" "$DJ_SRC" "$SSX3_SRC" "$TRICKY_SRC"; do
  [ -e "$p" ] || { echo "missing prerequisite: $p" >&2; exit 1; }
done

echo "staging -> $OUT"
rm -rf "$OUT"
mkdir -p "$OUT/RadioBig/assets/dj" \
         "$OUT/RadioBig/assets/ssx3" \
         "$OUT/RadioBig/assets/tricky" \
         "$OUT/RadioBig/players" \
         "$OUT/source/RadioBigPlugin"

# --- shared: DLL + README ----------------------------------------------------
cp "$DLL" "$OUT/RadioBigTM.dll"
cp "$HERE/RELEASE_README.md" "$OUT/README.md"

# --- per-OS frozen players ---------------------------------------------------
stage_player() {  # <src dir> <dest-subdir> <label>
  if [ -d "$1" ]; then
    cp -R "$1" "$OUT/RadioBig/players/$2"
    xattr -cr "$OUT/RadioBig/players/$2" 2>/dev/null || true
    echo "  + player ($3)"
  else
    echo "  ! no $3 freeze at $1 — skipping (build it or ship source only)" >&2
  fi
}
stage_player "$MAC_SRC" "mac-arm64" "mac-arm64"
stage_player "$WIN_SRC" "windows"   "windows"

# --- source tree (so Linux / any platform can run or re-freeze) --------------
cp "$HERE/radio_server.py" "$HERE/dj_brain.py" "$HERE/dj_library.py" \
   "$HERE/radio_player.py" "$HERE/run_radio.sh" \
   "$HERE/freeze.sh" "$HERE/freeze_windows.sh" "$HERE/package.sh" \
   "$OUT/source/"
cp "$HERE/RadioBigPlugin/RadioBig.cs" "$HERE/RadioBigPlugin/build.sh" \
   "$OUT/source/RadioBigPlugin/"
cp "$HERE/BUILD.md" "$OUT/source/BUILD.md"

# --- audio (the big part) ----------------------------------------------------
echo "  copying DJ voice clips…";   cp "$DJ_SRC"/*.mp3     "$OUT/RadioBig/assets/dj/"
echo "  copying SSX3 soundtrack…";  cp "$SSX3_SRC"/*.mp3   "$OUT/RadioBig/assets/ssx3/"
echo "  copying Tricky soundtrack…";cp "$TRICKY_SRC"/*.mp3 "$OUT/RadioBig/assets/tricky/"

echo "done."
printf 'players: %s   dj=%s ssx3=%s tricky=%s clips\n' \
  "$(ls "$OUT/RadioBig/players" 2>/dev/null | tr '\n' ',' | sed 's/,$//')" \
  "$(ls "$OUT/RadioBig/assets/dj"/*.mp3     | wc -l | tr -d ' ')" \
  "$(ls "$OUT/RadioBig/assets/ssx3"/*.mp3   | wc -l | tr -d ' ')" \
  "$(ls "$OUT/RadioBig/assets/tricky"/*.mp3 | wc -l | tr -d ' ')"
du -sh "$OUT"
