# What this fork changes (and why)

Fork of [GlitcherOG/MusicPluginTrickyMaddness](https://github.com/GlitcherOG/MusicPluginTrickyMaddness).
Doubles as the PR description when we push upstream. Fork point:
`a0b3f17` (upstream/main).

## TL;DR

The upstream plugin was written against an **old game beta and no longer runs** —
it referenced `audioInfos` / `SongIndex` / `StartNewSong` / `audioSource`, none of
which exist in the shipped build. This fork is a **from-scratch rewrite against the
current game API** that also adds the features that were actually wanted:
**per-level song selection** (incl. custom mod maps), a **menu-music override**,
**custom `.bnk` bank loading**, a **JSON config**, and a **native-macOS build**.

## Why the original didn't work

Static RE of the shipped `Assembly-CSharp.dll` (Unity 2022.3.62, BepInEx 5.4.23.2)
against the upstream source:

| Upstream referenced | Reality in the current build |
|---|---|
| `audioInfos`, `SongIndex`, `StartNewSong`, `audioSource` | **Don't exist.** The code can't compile, let alone run, against the shipped game. |
| A Unity `AudioSource`/`AudioClip` music path | The game is **Wwise-only** — all audio is `AkSoundEngine.PostEvent(eventName, GameObject)`. There is **no live Unity `AudioListener`**, so a Unity clip would be silent. |
| Music "playlist" with an index | The real system is a blind non-repeating random pull from one shared 7-song pool, posted inline in `LevelManager.Start()`. Music is **not scoped to a level** at all. |

Consequence, established up front and stated plainly in the README: **mp3/ogg
drop-in is impossible on this engine, and SFX replacement is out of scope** — both
would require authoring a Wwise `.bnk`, not a config file. This fork does the thing
that *is* possible: decide **which Wwise event** plays where.

## What the fork adds

1. **Per-level song selection (headline).** Maps a level name → a Wwise event and
   posts it when that level starts. Works for built-in levels **and custom mod maps**
   (Garibaldi, the SSX ports) because it reads the same `LevelEntry.name` the
   LevelHook registers maps under. Unmapped levels keep vanilla random music.
2. **Menu-music override.** Swap the main-menu track for an event of your choice.
3. **Custom Wwise banks.** Load user `.bnk` files named in the JSON; reference their
   events anywhere a built-in event goes.
4. **JSON config** via Unity's built-in `JsonUtility` (no Newtonsoft in the game),
   plus BepInEx global toggles.
5. **Native-macOS build.** `build.sh` mirrors our LevelHook's `--mac` mcs path;
   cross-platform Music-folder resolution walks out of `TrickyMadness.app/Contents/…`
   (kills the upstream hardcoded Windows `\` paths).

## How to use it

Full detail (schema, event table, bank authoring) is in the **README**; this is the
quickstart.

1. **Install.** Build with `./build.sh` (needs `brew install mono`), or grab the
   release DLL, and copy `MusicPluginTrickyMaddness.dll` into
   `<game>/BepInEx/plugins/` (BepInEx 5 must already be installed — same as the
   LevelHook).
2. **Launch once.** The plugin creates a `Music/` folder next to the game
   (next to `run_bepinex.sh` on macOS, next to the exe on Windows) and writes a
   default `Music/music_config.json`.
3. **Edit `Music/music_config.json`** to map levels to songs, then relaunch:

   ```json
   {
       "menuEvent": "Play_03_APEX",
       "banks": [],
       "levels": [
           { "level": "Garibaldi Rebuilt", "event": "Play_04_LSD" },
           { "level": "Elysium Alps",      "event": "Play_01_White_Powder" }
       ]
   }
   ```

   - `level` = the level's name (the label on the level-select card,
     case-insensitive). For a **custom mod map** it's the map's `.asset` filename,
     e.g. `Garibaldi Rebuilt` — the LevelHook registers each map under that name.
   - `event` = a Wwise event. Use a **built-in** one (table below) or a **custom**
     one from a bank you list in `banks`.
   - Unlisted levels are left alone (vanilla random music plays).

4. **Built-in song events** you can drop into `event` / `menuEvent`:

   | Song | Event | Song | Event |
   |---|---|---|---|
   | White Powder | `Play_01_White_Powder` | Psychic Damage | `Play_11_Psychic_Damage` |
   | APEX | `Play_03_APEX` | Amnesia | `Play_13_Amnesia` |
   | LSD | `Play_04_LSD` | Back To Life | `Play_14_Back_To_Life` |
   | Shellshock | `Play_05_Shellshock` | Menu | `Play_00_Menu` |

5. **Menu override (optional).** Set `menuEvent` and flip
   `[Menu] OverrideMenuMusic = true` in
   `BepInEx/config/com.glitcherog.musicplugin.cfg`. Empty `menuEvent` = vanilla menu.

6. **Custom songs (advanced).** Author a Wwise SoundBank (`.bnk`), drop it in
   `Music/`, add its filename to `banks`, and reference its event name from any
   `event` / `menuEvent`. (This is the *only* way to add a **new** sound — there is
   no mp3 drop-in; see "Hard limits" in the README for why.)

**BepInEx toggles** (`com.glitcherog.musicplugin.cfg`): `Enabled` (master, default
on), `VerboseLogging` (logs each music decision + the level names it sees — handy for
finding the exact string to put in `level`), `OverrideMenuMusic` (default off).

## How it hooks the game (all verified against the IL)

| Hook | Target | Purpose |
|---|---|---|
| Prefix | `MenuManager.LoadScene(LevelEntry)` | Capture the current level's `name` (earliest reliable point; catches custom maps). |
| **Postfix** | `LevelManager.Start()` | Gameplay music. `StopAll` the vanilla random pick and `PostEvent` the mapped event on the same `musicPlayer` GO, leaving `MusicState=Intro` so Intro/Verse/Outro transitions still fire. A postfix (not a false-returning prefix) because `Start` also does racer/camera/HUD setup. |
| **Prefix** | `AkSoundEngine.PostEvent(string, GameObject)` | Menu override. Rewrites the vanilla `"Play_00_Menu"` → your `menuEvent` at the source. That event is posted from both `MenuManager.Start` and the `UnloadLevel` coroutine, so one choke-point hook covers cold-boot **and** return-to-menu. Early-outs on a bool when the override is off, so SFX are untouched. |

## Fixed bugs from the original

- **Double-play:** the old *void* prefix let the original song and the replacement
  both play. The rewrite stops the vanilla track before posting (and for the menu,
  substitutes at the source so it never plays at all).
- **Playlist off-by-one:** the old index-based playlist wrapped with an off-by-one
  (`== Count` reset after use). Selection is now a direct map lookup — no wrap.

## Files

| File | Change |
|---|---|
| `Plugin.cs` | Rewritten: config load, cross-platform paths, the three Harmony patches, bank loading. |
| `MusicConfig.cs` | New. `JsonUtility`-shaped config model (`List<LevelSong>`, no Dictionary). |
| `PluginInfo.cs` | New. Hand-written GUID/NAME/VERSION consts (mcs has no `PluginInfoProps` codegen). |
| `build.sh` | New. mcs build, `--mac` default, mirrors the LevelHook. |
| `README.md` | New. Usage, JSON schema, built-in event table, and the honest Wwise-only limits. |
| `MusicReplacer.cs` | **Deleted.** Referenced the non-existent beta API. |
| `.csproj` | Dropped `PluginInfoProps`; added the AK.Wwise references. |
| `.gitignore` | Ignore build output. |

## Verification status

**Compile-verified (static):** clean build against the shipped `Assembly-CSharp.dll`
and `AK.Wwise.Unity.API.dll`; every hook target + member access confirmed present in
the IL with the expected signatures; JSON round-trips through `JsonUtility`.

**Boot-pending (needs an in-game run):** that posting a mapped event actually plays
the intended song, `StopAll` cleanly cuts the vanilla track, custom `.bnk`
loading/playback, the menu swap across both entry points, and whether the
`MusicState` transitions drive a re-posted event. The game could not be run in the
build environment. See the README "Status / boot-test pending" section.

## Commits (branch `feat/per-level-music-mac-json`)

- `4ed8655` build: add mcs build script and hand-written PluginInfo
- `280328d` feat: per-level Wwise music selection against the current game API
- `d5e5a4c` docs: document per-level music, JSON schema, and Wwise-only limits
- `fd795fb` Cover return-to-menu in menu override via PostEvent rewrite
