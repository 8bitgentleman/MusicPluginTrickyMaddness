# Radio Big — a live DJ radio for Tricky Madness

Turns the game's music slot into **Radio Big**, the SSX3 station: Atomika
introduces each track by name, the lobby runs mountain news / rider gossip
between races, and it's paced and shuffled so no two sessions sound alike.

Nothing to install beyond dropping in the files — **no Python, no setup.** The
radio runs as a small bundled player that the plugin launches and shuts down
with the game automatically.

## Install

1. You need **BepInEx 5** already working in Tricky Madness (the same setup the
   level mods / LevelHook use).
2. Copy **both** of these into your game's `BepInEx/plugins/` folder:
   - `RadioBigTM.dll`
   - the whole `RadioBig/` folder (the player + all the audio)
   So you end up with:
   ```
   BepInEx/plugins/
     RadioBigTM.dll
     RadioBig/
       player/ …
       assets/ …
   ```
3. Launch the game. That's it — Radio Big starts with it and stops with it.

## macOS: "cannot be opened / unidentified developer"

The bundled player is an unsigned binary, so if macOS quarantined the download
it may refuse to launch (and you'll get silence + a note in
`BepInEx/LogOutput.log`). Clear the quarantine flag once:

```
xattr -dr com.apple.quarantine "/path/to/Tricky Madness/…/BepInEx/plugins/RadioBig"
```

(The `package.sh` build already strips it locally; this only bites downloaded
copies.)

## Config

`BepInEx/config/com.mtv.radiobig.cfg` (written on first run):

- `Enabled` — master switch.
- `SuppressGameMusic` — mute the game's own music so Radio Big owns the slot
  (SFX are never touched). Off = hear both, for debugging.
- `AutoLaunchPlayer` — launch the bundled player with the game. Turn off only if
  you're running the player yourself from source.
- `Host` / `Port` — where the player listens (defaults are fine).
- `VerboseLogging` — log every event forwarded to the player.

## What it plays

The SSX 3 and SSX Tricky soundtracks, with Atomika's real DJ segments. When an
SSX3 track has a dedicated intro, the DJ actually names the artist about to play.
The lobby only recaps races *after* you've raced one — a cold boot never
references a race that hasn't happened.
