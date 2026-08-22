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

Six asset dirs under `assets/`: `dj` (Atomika's voice clips) and five
soundtracks — `ssx3`, `tricky`, `sxot` (SSX On Tour), `ssx2012` (SSX 2012),
`tm` (Tricky Madness' own).

| Pool | Tracks | Artist-matched intros? |
|---|---|---|
| `ssx3` | 35 race + 3 hub loops | yes — ~28 have a dedicated Atomika intro naming the artist |
| `tricky` | 21 + a menu loop + 2 alternate recordings | no — instrumental, and they predate this DJ |
| `sxot` | 41 | no — On Tour dropped Atomika's station for a plain shuffle. One exception: **Queens Of The Stone Age are on both soundtracks**, so On Tour's *Medication* resolves to the real intro naming them |
| `ssx2012` | 36 | no — 2012 has its own in-game DJ, not Atomika, so these ride the generic intros. Filenames carry real artists because the ripper reads them off the disc's own MBSI table (`tricky_mods: ssx/ssx2012_musicbox.py`) |
| `tm` | 14 race + 3 lobby loops | no — original music by Jordan Schor, on no SSX soundtrack, so it rides the generic intros as `ssx2012` does. **Not shipped in the pack**; built locally by `radio/extract_tm_music.py` — see § The `tm` pool |

⚠️ **`sxot`, `ssx2012` and `tm` are optional and must stay that way.** The first two only
exist if you own that disc and ran the ripper (`tricky_mods:
ssx/audio_rip_music.py`); `tm` only exists once the player has run
`extract_tm_music.py` against their own install. A missing pool reads as `not installed` in the startup
diagnostic rather than `MISSING DIR`, `package.sh` skips it with a warning
instead of failing its prereq check, and `DJBrain._next_song` **renormalises
`SOURCE_WEIGHTS` over the pools that actually loaded** — so a two-soundtrack
install plays at the old ratio rather than going quiet 30% of the time.

⚠️ **`ssx3` and `tricky` are disc rips, and their FILENAMES are load-bearing.**
Since 1.2.0 both pools come off the PS2 discs (`tricky_mods:
ssx/music_build_pool.py`), but they ship under the *web rips'* titles, because
`parse_song` / `INTRO_ARTISTS` recover title and artist from the filename — that
is how Atomika knows whose track he is introducing. Deploying the raw disc rips,
which are named by artist slug (`fspoon.mp3`), silently kills every
artist-matched intro with nothing logged. The rename tables are
`tricky_mods: ssx/{ssx3,tricky}_song_names.tsv`; the regression check is that
artist-matched intros stay at **32**.

⚠️ **A user can switch any pool off** — plugin config `[Sources]` → player
`--sources`. Filtering lives in `Library.__init__` so the brain's bags and weight
renormalisation (above) absorb it with no second table; the `dj` pool is never
filtered. Details in `radio/README.md`.

⚠️ **Adding a soundtrack is a checklist, not one edit.** In `dj_library.py`:
a resolved path + env override in `_resolve_assets()` (and the module-level
unpack below it), a row in `_log_asset_diag`'s table, the slug in
`ALL_SOURCES`, and a `_list_music()` loop in `Library.__init__` tagged with the
new `source=`. Then `DJBrain.SOURCE_WEIGHTS`, a `[Sources]` toggle in
`RadioBig.cs`, and a `stage_optional` call + summary field in `package.sh`.
None of them fails loudly. Miss the `_list_music()` loop and the pool simply
never loads; miss `ALL_SOURCES` and the filter still works, but the plugin's own
toggle gets denounced on stdout as "not a known soundtrack".
Forgetting the **weight** no longer loses the pool — the bags are built from
**what actually loaded**, so an unweighted source plays at
`DJBrain.UNWEIGHTED_SHARE` and says so on stdout. (It used to be built from the
weight table, which meant the songs loaded, counted, printed in the library dump
and could never be drawn.)

⚠️ **Filenames are the metadata.** `parse_song()` reads track number, title and
artist out of `<NN> - <Title> (<Artist>).mp3`; the artist is the **last**
parenthetical. Nothing reads ID3 tags. Rename a pool and you silently lose its
artist matching.

## The `tm` pool — Tricky Madness' own soundtrack

Radio Big *replaces* the game's music wholesale (the `PostEvent` prefix mutes all
8 music events). This pool adds it back as a **fifth soundtrack**, on equal
footing with the four rips: same filename contract, same `[Sources]` toggle, same
weight renormalisation. Built 2026-08-22; facts below verified against the
shipped Mac + Windows installs unless flagged otherwise.

⚠️ **The music is never played back through Wwise.** Un-muting the game's own
events for `tm` tracks was considered and rejected: two processes means no
ducking, Atomika can't talk over a track he isn't mixing, and Wwise gives the
Python side no end-of-track callback. The pool goes through the same decode →
MP3 → pygame path as every other pool.

**The game hands us the metadata.** TM ships its Wwise
`GeneratedSoundBanks/` with `SoundbanksInfo.xml` and per-bank `.txt` intact, so
every track is named and ID'd — there is **no bank RE to do**. `Music_Bank.txt`
alone gives the full event → media-ID → title mapping. Decoding is
`vgmstream-cli` + `ffmpeg`, already this project's sibling toolchain
(`tricky_mods: ssx/AUDIO_EXTRACTION.md`); proven end-to-end on
`255779309.wem` → 2:54 / 44.1 kHz / stereo MP3.

⚠️ **`vgmstream-cli` is required even for `--dry-run`** — durations and the
subsong join both come from probing, so there is no metadata-only mode. Only the
encode step needs `ffmpeg`, which is why the two tools are guarded separately.

⚠️ **Mac and Windows ship identical media** — same 14 `.wem` IDs, same Custom
Vorbis encoding, same `.txt`. One extractor covers both; only the base path
differs:

| OS | Banks under |
|---|---|
| macOS | `TrickyMadness.app/Contents/Resources/Data/StreamingAssets/Audio/GeneratedSoundBanks/Mac/` |
| Windows | `Tricky Madness_Data/StreamingAssets/Audio/GeneratedSoundBanks/Windows/` |

### What's actually in there: 14 songs, of which the game plays 7

`Music_Bank.txt` lists **15 music events** (`Play_00_Menu` … `Play_14_Back_To_Life`).
`MenuManager.RegisterSongs()` registers **7**. The other seven are fully authored,
sit in the bank, and **the game never plays them** — so this pool roughly doubles
TM's playable soundtrack rather than merely restoring it.

| Track | Media | Registered in-game? |
|---|---|---|
| 01 White Powder | `Media/255779309.wem` | yes |
| 02 Inertia | `Media/413322008.wem` | **no** |
| 03 APEX | `Media/1067108288.wem` | yes |
| 04 LSD | `Media/866279913.wem` | yes |
| 05 Shellshock | `Media/145550048.wem` | yes |
| 06 Hypnotized | `Media/23143563.wem` | **no** |
| 07 Play It Right | `Media/713564020.wem` | **no** |
| 08 Backside Rodeo | `Music_Bank.bnk` subsong 9 | **no** |
| 09 Bringin' Tha Noize | `Music_Bank.bnk` subsong 7 | **no** |
| 10 Like Woah | `Music_Bank.bnk` subsong 6 | **no** |
| 11 Psychic Damage | `Music_Bank.bnk` subsong 3 | yes |
| 12 Burn It Down | `Music_Bank.bnk` subsong 4 | **no** |
| 13 Amnesia | `Music_Bank.bnk` subsong 8 | yes |
| 14 Back To Life | `Music_Bank.bnk` subsong 2 | yes |

Plus **three lobby loops** — `Main Menu Music` (`661609931`), `Log Cabin`
(`249736487`), `Sunset Slopes` (`396527700`). `Music_Bank.bnk` subsongs 1 and 5
are KSHMR impact stingers, and the four remaining loose `.wem`s are ambience /
a fan loop — none of those are music, don't rip them.

### The menu loops feed `menu_tracks`, not the race shuffle

The split mechanism already exists and needs no new wiring: SSX 3's Hub Themes
and Tricky's Menu track already peel off into `Library.menu_tracks`
(`dj_library.py` ~L295), which `DJBrain._menu_bag` / `_menu_broadcast` draw for
the `MENU` broadcast. TM's three loops append there the same way.

This also fixes a live edge case: menu music currently comes **only** from SSX 3
+ Tricky, so switching both off leaves the lobby silent (the warning at
`dj_library.py` ~L351). TM's loops give the menu a floor — this is the one pool
that is always installed, because everyone running this mod owns the game.

⚠️ **Don't split them with the `"menu" in title` heuristic** — only one of the
three has "menu" in its name. Have the extractor number the loops **90–92** and
split on `num >= 90`, mirroring SSX 3's track-number range test. Songs are 01–14
off their own event names, so the 90s are free.

### Extraction is a release-time step, not a player-facing one

The pool **ships in the pack** like every other soundtrack. `extract_tm_music.py`
is run by whoever cuts the release, against their own install; players install
the mod and the music is simply there.

⚠️ **Do not re-propose shipping the extractor instead of the audio.** It was
built that way first and the numbers kill it: the pool is **63 MB**, while
bundling the decoders it shells out to is **~108 MB for macOS alone** (ffmpeg
57.7 MB and vgmstream 49.8 MB, both counting the libraries they link — the bare
`ffmpeg` binary is a misleading 417 KB), with a separate set again for Windows.
That is triple the download to avoid the download, plus a command-line `.exe` in
a Windows mod folder for antivirus to flag. The alternative — telling a
non-technical audience to install Python, ffmpeg and vgmstream — is not one.
Against a pack that is **already 1.2 GB**, the 63 MB it "saves" is ~5%.

`radio/extract_tm_music.py`, run before packaging:

```
python3 extract_tm_music.py                  # auto-locate install and output
python3 extract_tm_music.py --dry-run        # resolve + list, decode nothing
python3 extract_tm_music.py --install <dir> --out <dir> --force
```

It needs `vgmstream-cli` and `ffmpeg` on PATH (`brew install vgmstream ffmpeg`).
Output defaults to **`<game>/BepInEx/plugins/RadioBig/assets/tm`** when RadioBig
is installed, which is exactly where `dj_library` looks — so the common case is
zero-config, no env var and no path to set. With no RadioBig present it falls
back to `~/Downloads/SSX_Audio/tricky_madness/music` and prints the
`RADIO_BIG_TM` export needed to use it from there.

What it does, and why none of it is a hardcoded table:

1. Locate the install; pick the `Mac/` or `Windows/` bank dir.
2. Parse `Music_Bank.txt` for ID → title. **Don't hardcode the table** — a game
   update that adds a track should be picked up, not silently dropped.
3. Streamed: `vgmstream-cli -i Media/<id>.wem`. In-bank:
   `vgmstream-cli -i -s <n> Music_Bank.bnk` — and `<n>` is a **subsong index,
   not an ID**, so resolve it by enumerating subsongs and joining on the
   `stream name` vgmstream reports (which is the media ID). Same join as
   `tricky_mods: ssx/AUDIO_EXTRACTION.md`. Today that lands Back To Life at 2,
   Psychic Damage 3, Burn It Down 4, Like Woah 6, Bringin' Tha Noize 7,
   Amnesia 8, Backside Rodeo 9 — derive it, don't bake it.
4. Pipe to `ffmpeg` → `<NN> - <Title> (Jordan Schor).mp3`. The whole pool is
   one composer, so the artist is a constant, not something to parse out of
   the bank.

⚠️ **Track identity comes from the Wwise *object path*, not the `Name` field.**
The segment after `JordanMusic\` is `01 White Powder`; the media `Name` is a
working title (`[-24LUFS] Back to Life - Cmin 135BPM`). Parse the wrong one and
every filename — and therefore every title the DJ announces — is studio shorthand.

⚠️ **Stingers share a song's folder** (a 1 s and a 4 s KSHMR impact under
`09 Bringin' Tha Noize`), and nothing in the metadata marks them as non-music.
Length is the only discriminator — `MIN_TRACK_SECONDS = 30`, against a real
minimum of 1:44.

⚠️ **`vgmstream-cli` renders the loop by default** — every one of these tracks
has loop points, so without `-i` each comes out played twice with a fade
(White Powder decodes 5:58 instead of 2:54). Nothing errors; the whole pool is
just silently double-length.

### Where it is wired

Same shape as § The soundtrack pools' warning — none of these fail loudly, so
this is also the map for whoever adds a sixth soundtrack:

| File | Edit |
|---|---|
| `dj_library.py` | resolved path + env override in `_resolve_assets()` (~L64) and the module-level unpack (~L96); a row in `_log_asset_diag` (~L99); `"tm"` in `ALL_SOURCES` (~L263); a `_list_music()` loop tagged `source="tm"` that routes `num >= 90` to `menu_tracks` (~L300) |
| `dj_brain.py` | a `SOURCE_WEIGHTS` entry (~L100) **and rebalance the other four** — they currently sum to exactly 1.00, so a fifth added without adjusting them rides `UNWEIGHTED_SHARE` (0.10) and says so on stdout |
| `RadioBigPlugin/RadioBig.cs` | `[Sources]` → `TrickyMadness`, default on; `srcs.Add("tm")` in the launch-arg builder. Default-on is safe because a missing `assets/tm` just loads nothing |
| `package.sh` | a `stage_optional` call like the two disc rips, and a `tm=` count in the summary. It is *mechanically* optional (absent until the extractor runs) but, unlike `sxot`/`ssx2012`, does not depend on owning another disc — so `tm=0` in a release is a mistake, not a valid slimmer pack |
| `extract_tm_music.py` | `MENU_BASE = 90` — one half of a two-file contract with `dj_library.TM_MENU_BASE`. Drift between them doesn't fail; it quietly drops lobby loops into the race shuffle |

### Notes

- **Artist: Jordan Schor** — he composed the whole TM soundtrack, so all 17
  tracks carry the same credit. (Settled by the user, 2026-08-20; nothing in
  `Assembly-CSharp.dll` or `resources.assets` carries a composer string, and the
  only in-game trace is the `JordanMusic` Wwise object path.) `parse_song()`
  takes the artist from the last parenthetical, so name the files right the
  first time — a rename later silently breaks artist matching.
- **No Atomika intros exist for these tracks** (original music, on no SSX
  soundtrack), so the pool rides the generic intros exactly as `ssx2012` does.
  That is the established precedent, not a new gap.

## Where the pieces are

| Path | What |
|---|---|
| `radio/README.md` | Player architecture, run-from-source, dogfood commands, status. |
| `radio/BUILD.md` | Building the three artifacts (DLL, per-OS freeze, bundle). |
| `radio/RELEASE_README.md` | Ships as the end-user README (Win/Mac/Linux install). |
| `radio/radio_server.py` | IPC server + the DJ engine entry point. |
| `radio/dj_brain.py`, `dj_library.py`, `radio_player.py` | Scheduler / clip selection / pygame mixing. |
| `radio/RadioBigPlugin/RadioBig.cs` | The BepInEx bridge (mutes music, spawns player, forwards events). |
| `radio/extract_tm_music.py` | Builds the `tm` pool from an install. Release-time tool — run it before `package.sh`. |
| `radio/freeze.sh`, `freeze_windows.sh`, `package.sh` | Freeze (mac / windows-via-Wine) and assemble the bundle. |

## Status

- External-player path + live ducking: **proven by ear.**
- DJ brain, artist matching, IPC: **built + tested** (silent-stub dry runs).
- Plugin: **runs in-game** — spawns the player, mutes music, forwards `START` /
  `FINISH` / `MENU`. The Doorstop-inject and Windows-freeze problems are fixed.
- `tm` pool: **built** (2026-08-22) — extractor, library wiring, weights and the
  `[Sources]` toggle. Verified on Mac: 17/17 tracks decode at source length, the
  library loads 14 race + 3 lobby, source filtering and weight renormalisation
  behave. Verified on **Windows** by running the extractor under the bottle's
  Windows Python (`drive_c/py312/python.exe`, `sys.platform == 'win32'`) against
  the bottle's own install — same 17 song folders as Mac, native separators
  throughout, output resolving to `assets\tm`. Decode itself is unproven there:
  the bottle has no Windows `vgmstream-cli`/`ffmpeg`. **Not yet heard in game.**
- Reactive `EVENT` lines: player + protocol ready; the game-side combo/knockdown
  hooks are **not wired yet** (needs Assembly-CSharp RE).
