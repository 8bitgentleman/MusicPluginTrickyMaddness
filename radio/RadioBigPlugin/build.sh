#!/bin/sh
# Build RadioBigTM.dll — the Radio Big companion-player bridge plugin.
# Requires mono's mcs (brew install mono). Output lands here; copy it to
# <game>/BepInEx/plugins/ to install.
#
# Wwise-only game, so AK.Wwise is load-bearing (AkSoundEngine lives there).
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
  -r:"$MANAGED/Assembly-CSharp.dll" \
  -r:"$MANAGED/AK.Wwise.Unity.API.dll" \
  -r:"$MANAGED/UnityEngine.dll" \
  -r:"$MANAGED/UnityEngine.CoreModule.dll" \
  -r:"$MANAGED/netstandard.dll" \
  -r:"$CORE/BepInEx.dll" \
  -r:"$CORE/0Harmony.dll"

echo "Built: $HERE/RadioBigTM.dll"
