# Radio Big — a live SSX3-style DJ for Tricky Madness

Atomika-style radio takeover: the game's music slot is replaced by a dynamic
station that plays **DJ banter → an artist intro → a song → more banter → a song**,
paced by how long you're on the course, and **never the same twice**. When the
next track is an SSX3 song with a dedicated Atomika intro, the DJ actually names
the artist about to play.

## Why it's built this way (the short version)

Tricky Madness has **Unity audio disabled** and is **Wwise-only**, so custom mp3s
can't play *inside* the game (full RE: `../../tricky_mods/ssx/MUSIC_MOD_RE.md`).
So the audio lives in an **external Python player**, and a tiny BepInEx plugin
just mutes the game's own music and forwards events to it over a localhost socket:

```
   Tricky Madness ──(RadioBigTM plugin)──> localhost:48757 ──> radio_server.py
     mutes 8 music events (SFX untouched)        │                  │
     START <level> on course start               │            DJBrain (dj_brain.py)
     FINISH on race end, MENU on return           │            RadioPlayer (pygame)
     EVENT combo/knockdown (later)                │            + dj_library.py
```

## Pieces

| File | Role |
|------|------|
| `radio_player.py` | Audio core: music bed + DJ voice channel, real ducking. |
| `dj_library.py`   | Indexes the DJ clips + soundtracks; matches songs to artist intros. |
| `dj_brain.py`     | The scheduler — station ID, banter, intro, song, reactions. |
| `radio_server.py` | localhost socket the plugin talks to (verbs: HELLO/PING/START/FINISH/MENU/EVENT/QUIT). |
| `run_radio.sh`    | Convenience launcher for the server. |
| `RadioBigPlugin/` | The BepInEx bridge plugin (`RadioBig.cs`, `build.sh`). |

Asset locations are constants at the top of `dj_library.py` / `radio_player.py`
(the SSX3 + Tricky soundtrack rips and the `Radio_Big_Sections` DJ clips).

## Run it

1. **Player** (needs `python3` + `pip3 install pygame`):
   ```sh
   ./run_radio.sh
   ```
   Leave it running. It reconnects, so you can (re)start it any time.
2. **Plugin**: build and install once:
   ```sh
   RadioBigPlugin/build.sh --mac
   cp RadioBigPlugin/RadioBigTM.dll "<game>/BepInEx/plugins/"
   ```
3. Launch Tricky Madness, drop into a course — the radio takes over.

Config: `BepInEx/config/com.mtv.radiobig.cfg` (`Enabled`, `SuppressGameMusic`,
`Host`, `Port`, and a `[Sources]` section with one switch per soundtrack —
`SSX3`, `Tricky`, `OnTour`). Don't run this alongside the per-level
`MusicPluginTrickyMaddness` — both fight over the music slot.

⚠️ **`[Sources]` reaches the player by argv, not the environment** — env vars
don't reliably survive to a wine-spawned child, which is the same reason
`--assets` is an argument. The plugin always sends `--sources`, even when
everything is on, so the player's log states the effective set instead of leaving
it to be inferred. Filtering itself happens in `Library.__init__`, not in
`DJBrain`: the brain rebuilds its shuffle bags and renormalises its weights from
whatever the library hands it, so a source dropped there disappears cleanly all
the way through with no second table to keep in sync. The DJ voice pool is
deliberately **not** filtered — Atomika fronts the whole station.

⚠️ Editing the Python here is inert until you re-run `./freeze.sh` (and
`./freeze_windows.sh`) — the plugin launches the *frozen* player, so a source-only
change tests nothing that ships.

## Worker lifecycle — the "DJ talks over the race" trap

Only one broadcast may be live at a time, and `DJBrain` enforces that with a
worker thread plus a stop flag. Three rules, all of which shipped broken in 1.2.0
and produced the same audible symptom (lobby banter spliced over a race roughly
every `menu_banter_gap` seconds, forever):

- ⚠️ **Each worker owns its own `threading.Event`, handed to it as an argument,
  and a halted worker's Event is never cleared.** The 1.2.0 code kept one shared
  `self._stop` that `_begin` cleared before starting the next worker — which
  un-stopped any worker that had outlived the join, resurrecting it permanently.
  Never read `self._stop` from inside a broadcast; read the `stop` argument.
- ⚠️ **Anything a worker blocks in must take that Event.** `RadioPlayer.say()`
  blocks for a whole 12–20 s clip, an order of magnitude past `_halt_worker`'s
  2 s join, so without an interrupt the join always timed out and the halt was a
  no-op. The one deliberate exception is `_do_outro`'s sign-off, which passes no
  Event so a new broadcast can't cut Atomika off mid-goodbye.
- ⚠️ **`_say` waits for the voice lock in stop-aware slices and re-checks after
  acquiring it.** Because the sign-off above is uninterruptible, a worker can sit
  queued on that lock across its own halt; a plain `with self._voice_lock` wakes
  up afterwards and plays one stale line straight over the race.

Both failures have a deterministic regression test (fake player, compressed
timings, no audio, exit 1 on repro):

```sh
python3 tests/test_worker_lifecycle_zombie.py
python3 tests/test_worker_lifecycle_outro_lock.py
```

The outro-lock one only reproduces in a narrow window, so its `time.sleep`
values are load-bearing — if you retune `menu_banter_gap` semantics, re-check it
still fails against the old code before trusting it to pass against the new.

## Dogfood without the game

```sh
python3 dj_brain.py       # a compressed broadcast you can hear, no game running
python3 dj_library.py     # print the song<->intro match table
```

## Status

- Route C (external player) + live ducking: **proven by ear.**
- DJ brain, artist matching, IPC protocol: **built + tested** (silent-stub dry runs).
- Plugin: **compiles + statically verified** (Harmony targets bound, 8 music
  events + protocol verbs in the IL). **Boot-test pending.**
- Reactive `EVENT` lines: player + protocol ready; the game-side combo/knockdown/
  finish hooks are **not wired yet** (needs Assembly-CSharp RE) — START/END only.
