# Radio Big — a live DJ radio for Tricky Madness

**Version 1.3.0.** Report bugs with the version line from `BepInEx/LogOutput.log`
(`Loading [Radio Big 1.3.0]`) so it's clear which build you're on.

Turns the game's music slot into **Radio Big**, the SSX3 station: Atomika
introduces each track by name, the lobby runs mountain news / rider gossip
between races, and it's paced and shuffled so no two sessions sound alike.

**New in 1.3.0:** the **SSX (2012)** soundtrack joins the station — 36 licensed
tracks off that game's own disc, switchable like the rest under *Choosing which
soundtracks play*. 2012 had its own in-game DJ rather than Atomika, so those
tracks get his generic intros instead of ones naming the artist.

**Fixed in 1.2.1:** the DJ no longer talks over your race every ~30 seconds.
Lobby chatter was leaking into races — leaving the menu didn't reliably shut the
lobby down, so it kept splicing in banter for the rest of the session (and each
new race could add another). Races are back to intro-then-music. If Atomika is
mid-sentence when you drop into a course he still finishes the line and *then*
hands over to the track intro, the same as before — that part was never the bug.

**New in 1.2.0:** the **SSX On Tour** soundtrack joins SSX 3 and SSX Tricky, you
can **switch any of the three off** (see *Choosing which soundtracks play*), and
all the music now comes straight off the original discs instead of web rips.

**No Python, no setup on Windows or macOS** — the radio runs as a small bundled
player that the plugin launches and shuts down with the game automatically. Linux
runs it from the included source (one `pip install`).

---

## What's in this download

```
RadioBigTM.dll            the BepInEx plugin (same file on every OS)
RadioBig/
  assets/                 the audio: DJ voice + the SSX3 / Tricky / On Tour /
                          SSX 2012 soundtracks (sxot/ and ssx2012/ only if the
                          packer owned those discs)
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

---

## Choosing which soundtracks play

Radio Big draws on four soundtracks, and you can switch any of them off — if you
never want to hear On Tour, or you only want the Tricky album, say so here. In
`BepInEx/config/com.mtv.radiobig.cfg`, under the `[Sources]` section:

```ini
[Sources]

## Play the SSX 3 soundtrack.
# Setting type: Boolean
# Default value: true
SSX3 = true

## Play the SSX Tricky soundtrack.
# Setting type: Boolean
# Default value: true
Tricky = true

## Play the SSX On Tour soundtrack (only if its audio is installed).
# Setting type: Boolean
# Default value: true
OnTour = true

## Play the SSX (2012) soundtrack (only if its audio is installed).
# Setting type: Boolean
# Default value: true
SSX2012 = true
```

Set one to `false` and restart the game. Things worth knowing before you do:

- **The radio doesn't get quieter in proportion.** The remaining soundtracks
  simply take up the freed airtime, so switching three off gives you the fourth
  on heavy rotation rather than long silences.
- **DJ Atomika keeps presenting either way.** He's SSX 3's announcer, but he
  fronts the whole station — muting him along with the SSX 3 songs would turn
  "I'd rather not hear this soundtrack" into "the radio has no host". His intros,
  news and banter are unaffected by these switches.
- **He only names the artist when he has a clip for that artist.** Those intros
  are SSX 3's, so turning SSX 3 off means most songs get a generic lead-in
  instead of a by-name introduction. Nothing breaks; the station is just less
  chatty about who's playing.
- **Turning all four off is allowed**, and gives you a talk station: DJ, news
  and banter, no music. If that wasn't what you meant, `LogOutput.log` says so
  in as many words.
- **Menu/lobby music comes only from SSX 3 and Tricky.** With both of those off,
  menus are silent while races still have music — that's expected, not a bug,
  and the log calls it out.

If a name is misspelled the log says which one and lists the valid names, rather
than silently filtering everything out.

## What it plays

The **SSX 3**, **SSX Tricky**, **SSX On Tour** and **SSX (2012)** soundtracks,
with Atomika's real DJ segments. When a track has a dedicated intro, the DJ
actually names the artist about to play. The lobby only recaps races *after*
you've raced one — a cold boot never references a race that hasn't happened.

As of 1.2.0 the SSX 3 and Tricky music is ripped **from the original PS2 discs**
rather than sourced from the web, so it's the game's own audio at a higher
bitrate — including the full-length "Screw Up", which circulated online only as a
truncated copy. On Tour's comes from the PSP UMD and SSX 2012's from the PS3
disc; each ships only if whoever built your pack owned that disc. If one is
absent the other soundtracks play as normal and its switch simply has nothing to
do.

## Troubleshooting

Silent radio? Check `BepInEx/LogOutput.log` for `Radio Big` lines and
`BepInEx/plugins/RadioBig/player.log` for the player's own output (the plugin tees
it there). The player log shows whether pygame started, whether it found the
assets, and any crash.
