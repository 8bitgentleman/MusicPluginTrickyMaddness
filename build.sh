#!/bin/sh
# Build MusicPluginTrickyMaddness.dll against the current game assemblies.
# Requires mono's mcs (brew install mono). Output lands in this folder; copy it
# to <game>/BepInEx/plugins/ to install.
#
# Mirrors the LevelHook build. Defaults target the native Mac build; the game
# is Wwise-only, so the AK.Wwise refs are load-bearing (AKRESULT / AkSoundEngine
# live there). netstandard + the UnityEngine JSON module are required for
# JsonUtility config.
set -e

if [ "$1" = "--mac" ] || [ -z "$1" ]; then
  # Native Mac build (default). CrossOver/Windows path kept as an override.
  GAME="${GAME:-/Users/mtvogel/Library/Application Support/Steam/steamapps/common/Tricky Madness}"
  MANAGED="${MANAGED:-$GAME/TrickyMadness.app/Contents/Resources/Data/Managed}"
else
  GAME="${GAME:-/Users/mtvogel/Library/Application Support/CrossOver/Bottles/Steam/drive_c/Program Files (x86)/Steam/steamapps/common/Tricky Madness}"
  MANAGED="${MANAGED:-$GAME/Tricky Madness_Data/Managed}"
fi
CORE="${CORE:-$GAME/BepInEx/core}"
HERE="$(cd "$(dirname "$0")" && pwd)"

mcs -target:library -out:"$HERE/MusicPluginTrickyMaddness.dll" \
  "$HERE/Plugin.cs" "$HERE/PluginInfo.cs" "$HERE/MusicConfig.cs" \
  -r:"$MANAGED/Assembly-CSharp.dll" \
  -r:"$MANAGED/AK.Wwise.Unity.API.dll" \
  -r:"$MANAGED/AK.Wwise.Unity.API.WwiseTypes.dll" \
  -r:"$MANAGED/AK.Wwise.Unity.MonoBehaviour.dll" \
  -r:"$MANAGED/UnityEngine.dll" \
  -r:"$MANAGED/UnityEngine.CoreModule.dll" \
  -r:"$MANAGED/UnityEngine.JSONSerializeModule.dll" \
  -r:"$MANAGED/netstandard.dll" \
  -r:"$CORE/BepInEx.dll" \
  -r:"$CORE/0Harmony.dll"

echo "Built: $HERE/MusicPluginTrickyMaddness.dll"
