#!/bin/sh
# Build RadioBigTM.dll — the Radio Big companion-player bridge plugin.
# Requires mono's mcs (brew install mono). Output lands here; copy it to
# <game>/BepInEx/plugins/ to install.
#
# Wwise-only game, so AK.Wwise is load-bearing (AkSoundEngine lives there).
# The DJ HUD icon is embedded as two PNGs (-resource:, logical names WITHOUT a
# path so DjFaceArt.FromResource can ask for them by bare filename). They are
# generated -- regenerate with `python3 make_dj_face.py` in this directory --
# and UnityEngine.ImageConversionModule is what supplies Texture2D.LoadImage to
# decode them; drop that ref and the build dies on LoadImage, not on the PNGs.
#
# The socket sender uses System.Net.Sockets.TcpClient — mcs auto-references its
# own System.dll for that, so do NOT add the game's System.dll (duplicate-type
# clash on TcpClient/NetworkStream). The BCL socket API is ABI-stable against the
# game's Mono runtime.
set -e

if [ "$1" = "--mac" ] || [ -z "$1" ]; then
  GAME="${GAME:-/Users/mtvogel/Library/Application Support/Steam/steamapps/common/Tricky Madness}"
  MANAGED="${MANAGED:-$GAME/TrickyMadness.app/Contents/Resources/Data/Managed}"
else
  GAME="${GAME:-/Users/mtvogel/Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Tricky Madness}"
  MANAGED="${MANAGED:-$GAME/Tricky Madness_Data/Managed}"
fi
CORE="${CORE:-$GAME/BepInEx/core}"
HERE="$(cd "$(dirname "$0")" && pwd)"

mcs -target:library -out:"$HERE/RadioBigTM.dll" \
  "$HERE/RadioBig.cs" \
  "$HERE/RadioStatus.cs" \
  "$HERE/RadioHudGraphics.cs" \
  "$HERE/RadioHud.cs" \
  -r:"$MANAGED/Assembly-CSharp.dll" \
  -r:"$MANAGED/AK.Wwise.Unity.API.dll" \
  -r:"$MANAGED/UnityEngine.dll" \
  -r:"$MANAGED/UnityEngine.CoreModule.dll" \
  -r:"$MANAGED/netstandard.dll" \
  -r:"$CORE/BepInEx.dll" \
  -r:"$CORE/0Harmony.dll" \
  -r:"$MANAGED/UnityEngine.UI.dll" \
  -r:"$MANAGED/Unity.TextMeshPro.dll" \
  -r:"$MANAGED/UnityEngine.UIModule.dll" \
  -r:"$MANAGED/UnityEngine.JSONSerializeModule.dll" \
  -r:"$MANAGED/UnityEngine.InputLegacyModule.dll" \
  -r:"$MANAGED/UnityEngine.ImageConversionModule.dll" \
  -resource:"$HERE/dj_face_lit.png",dj_face_lit.png \
  -resource:"$HERE/dj_face_dark.png",dj_face_dark.png

echo "Built: $HERE/RadioBigTM.dll"
