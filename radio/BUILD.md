# Building Radio Big from source

Three artifacts make up a release, built independently:

| Artifact | What | Built by |
|---|---|---|
| `RadioBigTM.dll` | BepInEx bridge plugin (portable IL — one file, every OS) | `RadioBigPlugin/build.sh` |
| frozen player | the audio player as a standalone binary (per-OS) | `freeze.sh` / `freeze_windows.sh` |
| the bundle | DLL + players + audio + this source, laid out for install | `package.sh` |

## The player (Python)

`radio_server.py` is the whole player: a localhost socket the plugin talks to,
driving `dj_brain.py` (scheduling) + `dj_library.py` (clip/song selection) +
`radio_player.py` (pygame audio + ducking). Run it directly on any OS:

```
pip3 install pygame
RADIO_BIG_ASSETS=/path/to/RadioBig/assets python3 radio_server.py
```

Assets resolve from `RADIO_BIG_ASSETS`, else next to a frozen binary, else the
dev paths baked into `dj_library.py`.

## The plugin (C#)

Needs mono's `mcs` (`brew install mono`) and the game's managed assemblies. The
DLL is portable managed IL — build it once on any OS and it runs on all of them:

```
RadioBigPlugin/build.sh --mac      # references the native-Mac game install
```

(Windows refs: drop `--mac`; see the paths in `build.sh`.)

## Freezing the player per-OS

PyInstaller can't cross-compile — each OS's binary must be frozen on that OS (or a
convincing stand-in). All three use the same recipe; only the host differs.

- **macOS (Apple Silicon):** `./freeze.sh` → `dist/RadioBigPlayer/` (Mach-O arm64).
- **Windows:** `./freeze_windows.sh` → `dist-windows/RadioBigPlayer/`. Runs a
  Windows Python + PyInstaller under **CrossOver's Wine** from a Mac — no Windows
  box needed. First run bootstraps Python into the bottle automatically.
- **Linux:** run the same PyInstaller line from `freeze.sh` on a Linux host, then
  drop the result into `RadioBig/players/linux/` before `package.sh`, OR just ship
  source and run `radio_server.py` (see the release README's Linux section).
- **Intel Mac:** freeze on an Intel Mac; stage under `RadioBig/players/mac`.

The plugin resolves the player by host OS: `players/windows`, `players/mac-arm64`
(then `players/mac`), or `players/linux`, falling back to a legacy flat `player/`.

## Assembling the release

```
./package.sh
```

Collects the DLL, whatever frozen players you've built (missing ones are skipped
with a warning), the audio, and this source into
`_release/RadioBig - Tricky Madness Mod/`. Edit the asset source paths at the top
of `package.sh` if your soundtracks live elsewhere.
