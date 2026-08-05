# Radio Big — the external-player departure

This repo started as a fork of the upstream
[MusicPluginTrickyMaddness](https://github.com/GlitcherOG/MusicPluginTrickyMaddness)
music mod. It now carries **two divergent directions**, and this doc explains the
second one — the big architectural departure — so the split is on the record and
not just in one person's head.

| Direction | Lives in | What it does | Doc |
|---|---|---|---|
| **1. Per-level Wwise music** | repo root (`Plugin.cs`, `MusicConfig.cs`, …) | Rewrite of the upstream plugin against the *shipped* game API: map each level → a **built-in Wwise event**. Stays entirely inside the game's audio engine. | `CHANGES.md` |
| **2. Radio Big (this doc)** | `radio/` | A live SSX3-style DJ station. Audio plays in an **external Python process**; the plugin only mutes the game's music and narrates game events to it over a socket. | `radio/README.md`, `radio/BUILD.md` |

They solve different problems and **must not run together** — both claim the music
slot. Direction 1 is the conservative "pick a different in-engine song" tool.
Radio Big is the "play arbitrary audio the engine can't touch" tool.

## Why Radio Big had to leave the engine

Tricky Madness is **Wwise-only** and ships with **Unity audio disabled** — there is
no live `AudioListener`, so a Unity `AudioClip` is silent, and the only way to make
sound *inside* the game is `AkSoundEngine.PostEvent(<event>, <GameObject>)` against
events already baked into a `.bnk`. That kills every in-engine route for playing
custom mp3s (the DJ voice, the SSX3/Tricky rips):

- **Drop-in mp3/ogg** — impossible; no Unity audio path exists.
- **Author a custom `.bnk`** — possible in principle (Direction 1 supports loading
  banks), but it means committing to the full Wwise authoring toolchain for *every*
  clip and gives up runtime scheduling/ducking. A DJ that reacts to gameplay wants
  logic, not a static bank.

So Radio Big moves the audio **out of the process entirely** ("Route C"): a small
Python player owns all playback and mixing, and the plugin's only job in-engine is
to **suppress the game's own music events** (SFX untouched) and **report what the
player is doing** — course start, finish, menu, reactions.

```
   Tricky Madness                         localhost TCP (default :48757)
   ┌───────────────────────┐              ┌──────────────────────────────┐
   │ RadioBigTM plugin     │  START <lvl> │ radio_server.py              │
   │  · mutes music events │ ───FINISH──▶ │  ├ dj_brain.py   (scheduler) │
   │    (SFX left alone)   │ ───MENU────▶ │  ├ dj_library.py (clip pick) │
   │  · forwards events    │ ───EVENT───▶ │  └ radio_player.py (pygame,  │
   │  · spawns/kills player │              │       music bed + ducked DJ) │
   └───────────────────────┘              └──────────────────────────────┘
```

## The IPC contract

Newline-terminated, case-insensitive verbs over the socket. Source of truth is the
`radio_server.py` header; the plugin (`radio/RadioBigPlugin/RadioBig.cs`) is the
only client.

| Verb | Sent when | Player does |
|---|---|---|
| `HELLO` | on connect | replies `OK Radio Big <version>` (handshake) |
| `PING` | keepalive | replies `PONG` |
| `START <level>` | a course begins | race broadcast: artist intro → song |
| `FINISH` | race finished | outro now, then fade |
| `MENU` | return to menu / lobby | lobby broadcast (menu loops + banter) |
| `EVENT <combo\|knockdown>` | reactive moment | ducked reactive DJ line *(game-side hooks not wired yet)* |
| `QUIT` | — | close the connection |

**Managed lifetime:** the plugin spawns the player as a child and the player exits
when its one client disconnects, so quitting or crashing the game never leaves an
orphan radio running. Two runtime gotchas that were load-bearing to get right:

- **Doorstop injection had to be stripped from the child.** On macOS the game boots
  under Doorstop with `DYLD_INSERT_LIBRARIES=libdoorstop.dylib` (a *bare relative*
  name). A naively-spawned child inherits it, can't find the dylib from its own cwd,
  and dyld hard-kills it before Python starts. The plugin removes `DYLD_*` / `LD_*`
  from the child env. (Symptom was "nothing plays"; the fix is in `RadioBig.cs`.)
- **The player's stdout/stderr is teed** to `BepInEx/plugins/RadioBig/player.log`
  so a silent radio is diagnosable without a terminal.

## Packaging: Python-free drop-in, and the no-music-in-git rule

Windows and macOS users get a **frozen player** (PyInstaller onedir) so there is no
Python install step; the plugin launches and shuts it down with the game. Linux runs
from the shipped source (`pip install pygame`, `AutoLaunchPlayer = false`).

PyInstaller **can't cross-compile**, so each OS's binary is frozen on that OS — with
the wrinkle that the **Windows `.exe` is frozen from macOS under CrossOver's Wine**
(`radio/freeze_windows.sh`), no Windows box required. Build details: `radio/BUILD.md`.

> **The audio never goes in git.** The DJ voice + the soundtrack rips are ~1.2 GB
> and are *not our content*. `package.sh` copies them in from local paths at
> release time; `.gitignore` excludes `radio/_release/`, `radio/dist/`,
> `radio/dist-windows/`, and the built DLLs. Only **source, scripts, and docs** are
> tracked. If you add an asset step, keep it pointing at out-of-tree paths — a
> committed mp3 is a licensing problem, not just a big-file problem.

## The soundtrack pools

Four asset dirs under `assets/`: `dj` (Atomika's voice clips) and three
soundtracks — `ssx3`, `tricky`, `sxot` (SSX On Tour).

| Pool | Tracks | Artist-matched intros? |
|---|---|---|
| `ssx3` | 35 race + 3 hub loops | yes — ~28 have a dedicated Atomika intro naming the artist |
| `tricky` | ~21 + a menu loop | no — instrumental, and they predate this DJ |
| `sxot` | 41 | no — On Tour dropped Atomika's station for a plain shuffle. One exception: **Queens Of The Stone Age are on both soundtracks**, so On Tour's *Medication* resolves to the real intro naming them |

⚠️ **`sxot` is optional and must stay that way.** It only exists if you own the
PSP UMD and ran the ripper (`tricky_mods: ssx/audio_rip_music.py`). A missing
pool reads as `not installed` in the startup diagnostic rather than
`MISSING DIR`, `package.sh` skips it with a warning instead of failing its
prereq check, and `DJBrain._next_song` **renormalises `SOURCE_WEIGHTS` over the
pools that actually loaded** — so a two-soundtrack install plays at the old
ratio rather than going quiet 15% of the time.

⚠️ **Adding a fourth soundtrack is two edits.** A `_list_music()` loop in
`dj_library.Library.__init__` tagged with a new `source=`, *and* an entry in
`DJBrain.SOURCE_WEIGHTS`. Forgetting the weight no longer loses the pool — the
bags are built from **what actually loaded**, so an unweighted source plays at
`DJBrain.UNWEIGHTED_SHARE` and says so on stdout. (It used to be built from the
weight table, which meant the songs loaded, counted, printed in the library dump
and could never be drawn.)

⚠️ **Filenames are the metadata.** `parse_song()` reads track number, title and
artist out of `<NN> - <Title> (<Artist>).mp3`; the artist is the **last**
parenthetical. Nothing reads ID3 tags. Rename a pool and you silently lose its
artist matching.

## Where the pieces are

| Path | What |
|---|---|
| `radio/README.md` | Player architecture, run-from-source, dogfood commands, status. |
| `radio/BUILD.md` | Building the three artifacts (DLL, per-OS freeze, bundle). |
| `radio/RELEASE_README.md` | Ships as the end-user README (Win/Mac/Linux install). |
| `radio/radio_server.py` | IPC server + the DJ engine entry point. |
| `radio/dj_brain.py`, `dj_library.py`, `radio_player.py` | Scheduler / clip selection / pygame mixing. |
| `radio/RadioBigPlugin/RadioBig.cs` | The BepInEx bridge (mutes music, spawns player, forwards events). |
| `radio/freeze.sh`, `freeze_windows.sh`, `package.sh` | Freeze (mac / windows-via-Wine) and assemble the bundle. |

## Status

- External-player path + live ducking: **proven by ear.**
- DJ brain, artist matching, IPC: **built + tested** (silent-stub dry runs).
- Plugin: **runs in-game** — spawns the player, mutes music, forwards `START` /
  `FINISH` / `MENU`. The Doorstop-inject and Windows-freeze problems are fixed.
- Reactive `EVENT` lines: player + protocol ready; the game-side combo/knockdown
  hooks are **not wired yet** (needs Assembly-CSharp RE).
