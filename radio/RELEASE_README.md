# Radio Big — a live DJ radio for Tricky Madness

**Version 1.0.0.** Report bugs with the version line from `BepInEx/LogOutput.log`
(`Loading [Radio Big 1.0.0]`) so it's clear which build you're on.

Turns the game's music slot into **Radio Big**, the SSX3 station: Atomika
introduces each track by name, the lobby runs mountain news / rider gossip
between races, and it's paced and shuffled so no two sessions sound alike.

**No Python, no setup on Windows or macOS** — the radio runs as a small bundled
player that the plugin launches and shuts down with the game automatically. Linux
runs it from the included source (one `pip install`).

---

## What's in this download

```
RadioBigTM.dll            the BepInEx plugin (same file on every OS)
RadioBig/
  assets/                 the audio: DJ voice + SSX3 + Tricky soundtracks
  players/
    windows/              frozen player for Windows        (RadioBigPlayer.exe)
    mac-arm64/            frozen player for Apple-Silicon  (RadioBigPlayer)
README.md                 this file
source/                   full Python + C# source (Linux path, or DIY re-build)
```

The plugin auto-picks the player folder that matches your OS — you don't choose.

---

## Install (Windows & macOS)

1. You need **BepInEx 5** already working in Tricky Madness (the same setup the
   level mods / LevelHook use).
2. Copy **both** of these into your game's `BepInEx/plugins/` folder:
   - `RadioBigTM.dll`
   - the whole `RadioBig/` folder (players + audio)

   So you end up with:
   ```
   BepInEx/plugins/
     RadioBigTM.dll
     RadioBig/
       assets/ …
       players/ …
   ```
3. Launch the game. That's it — Radio Big starts with it and stops with it.

### macOS: "cannot be opened / unidentified developer"

The bundled player is unsigned, so if macOS quarantined the download it may refuse
to launch (silence + a note in `BepInEx/LogOutput.log`). Clear the flag once:

```
xattr -dr com.apple.quarantine "/path/to/Tricky Madness/…/BepInEx/plugins/RadioBig"
```

### Windows: antivirus false-positive

PyInstaller-frozen `.exe`s are sometimes flagged by antivirus/SmartScreen (a known
false positive for *all* PyInstaller apps, not this one specifically). If the radio
is silent and your AV quarantined `RadioBigPlayer.exe`, allow-list the `RadioBig`
folder — or use the Linux/source path below, which runs the identical Python.

---

## Install (Linux, or anyone who'd rather run from source)

No frozen Linux binary ships (freeze it yourself if you want auto-launch — see
`source/BUILD.md`). The easy path is to run the player from source; the plugin
reconnects, so start order doesn't matter:

1. Copy `RadioBigTM.dll` + `RadioBig/` into `BepInEx/plugins/` as above.
2. Install the runtime: `pip3 install pygame`  (Python 3.9+).
3. Point the player at the shipped audio and start it:
   ```
   RADIO_BIG_ASSETS="/path/to/BepInEx/plugins/RadioBig/assets" \
     python3 source/radio_server.py
   ```
   (or just `source/run_radio.sh` if the assets sit in the default dev location).
4. Launch the game. Leave the player running; Ctrl-C stops it.

Set `AutoLaunchPlayer = false` in the config so the plugin doesn't also try to
spawn a (non-existent) bundled Linux player.

---

## Config

`BepInEx/config/com.mtv.radiobig.cfg` (written on first run):

- `Enabled` — master switch.
- `SuppressGameMusic` — mute the game's own music so Radio Big owns the slot
  (SFX are never touched). Off = hear both, for debugging.
- `AutoLaunchPlayer` — launch the bundled player with the game. Turn **off** if
  you run the player yourself from source (Linux, or dev).
- `Host` / `Port` — where the player listens (defaults are fine).
- `VerboseLogging` — log every event forwarded to the player.

## What it plays

The SSX 3 and SSX Tricky soundtracks, with Atomika's real DJ segments. When an
SSX3 track has a dedicated intro, the DJ actually names the artist about to play.
The lobby only recaps races *after* you've raced one — a cold boot never
references a race that hasn't happened.

## Troubleshooting

Silent radio? Check `BepInEx/LogOutput.log` for `Radio Big` lines and
`BepInEx/plugins/RadioBig/player.log` for the player's own output (the plugin tees
it there). The player log shows whether pygame started, whether it found the
assets, and any crash.
