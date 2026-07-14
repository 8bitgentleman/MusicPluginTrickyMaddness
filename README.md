# Tricky Madness Music Plugin

A BepInEx plugin for **Tricky Madness** that adds **per-level music selection**,
a **menu-music override**, and **custom Wwise bank loading** — configured from a
JSON file, cross-platform (Windows and native macOS).

This is a from-scratch rewrite against the **current** game build. The original
plugin was written against an old beta and no longer works (it referenced
`audioInfos` / `SongIndex` / `StartNewSong` / `audioSource`, none of which exist
in the shipped game).

## What it does

- **Per-level song selection (the headline feature).** Vanilla Tricky Madness
  music is *not* scoped to a level — every heat pulls a blind random track from
  one shared 7-song pool. This plugin maps a level to a specific song and posts
  that song when the level starts. Works for **built-in levels** and for
  **custom mod maps** (Garibaldi, the SSX ports) loaded by the LevelHook.
  Unmapped levels are left alone (vanilla random music still plays).
- **Menu-music override (optional).** Replace the main-menu track with an event
  of your choice.
- **Custom Wwise banks.** Load your own `.bnk` bank(s) named in the JSON, then
  reference their events from any level/menu mapping exactly like a built-in one.
- **JSON config** (via Unity's built-in `JsonUtility` — no Newtonsoft needed)
  plus BepInEx global toggles.

## Hard limits — read this before expecting mp3 support

**The game is Wwise-only.** All audio is fired by Wwise *event name* strings
(`AkSoundEngine.PostEvent`), and there is **no live Unity `AudioListener`** in
the game. That means:

- **You cannot drop in an mp3/ogg/wav and have it play.** A Unity `AudioClip`
  played through a Unity `AudioSource` would almost certainly be **silent**
  (no listener to render it). Custom audio therefore **requires a pre-authored
  Wwise `.bnk` soundbank** built in the Wwise authoring tool, exposing an event
  name this plugin can post.
- **SFX replacement is out of scope** for the same reason — the samples live in
  compiled banks, not in managed code, so there is no clip to swap.

In short: this plugin decides **which Wwise event** plays for a level/menu. Making
a *new* sound come out of the speakers is a Wwise-authoring task, not something a
config file can do. Don't expect a music-folder-of-mp3s workflow — that's not
possible on this engine.

## Install

1. Install BepInEx 5 into your Tricky Madness folder (same requirement as the
   LevelHook).
2. Build the plugin (see below) or grab the release `MusicPluginTrickyMaddness.dll`.
3. Copy `MusicPluginTrickyMaddness.dll` into `<game>/BepInEx/plugins/`.
4. Launch once. The plugin creates a `Music/` folder next to the game (next to
   `run_bepinex.sh` on macOS, next to the exe on Windows) and writes a default
   `Music/music_config.json`.
5. Edit `music_config.json`, drop any custom `.bnk` files into `Music/`, relaunch.

### Build

Requires mono's `mcs` (`brew install mono`). The maintained build is the shell
script (mirrors the LevelHook's `--mac` pattern):

```sh
./build.sh --mac      # native Mac build (default)
./build.sh            # same as --mac
GAME=... ./build.sh   # override game path (e.g. CrossOver/Windows)
```

The `.csproj`/`.sln` are kept for Windows IDE use but are not the maintained path.

## Music folder layout

```
Tricky Madness/                 (or the folder holding TrickyMadness.app on macOS)
├── run_bepinex.sh
├── Maps/                        (LevelHook's custom maps)
└── Music/
    ├── music_config.json        (created on first run)
    └── MyBank.bnk               (optional custom Wwise bank)
```

## JSON schema

`Music/music_config.json`:

| Field       | Type            | Meaning                                                                 |
|-------------|-----------------|-------------------------------------------------------------------------|
| `menuEvent` | string          | Wwise event for the menu, used only when `OverrideMenuMusic` is on. Empty = vanilla. |
| `banks`     | list of string  | `.bnk` files to load (relative to `Music/`, or absolute).               |
| `levels`    | list of objects | Per-level overrides. Each: `{ "level": <name>, "event": <akEventName> }`.|

`level` is matched against the level's name (the label on the level-select card,
case-insensitive). For custom maps that is the map's `.asset` filename, because
the LevelHook registers each map under that name. `event` is a Wwise event name —
either a **built-in** one or a **custom** one from a loaded bank.

### Built-in song events

| Song           | Event name               |
|----------------|--------------------------|
| White Powder   | `Play_01_White_Powder`   |
| APEX           | `Play_03_APEX`           |
| LSD            | `Play_04_LSD`            |
| Shellshock     | `Play_05_Shellshock`     |
| Psychic Damage | `Play_11_Psychic_Damage` |
| Amnesia        | `Play_13_Amnesia`        |
| Back To Life   | `Play_14_Back_To_Life`   |
| Menu           | `Play_00_Menu`           |

### Worked example

```json
{
    "menuEvent": "Play_03_APEX",
    "banks": [
        "MyBank.bnk"
    ],
    "levels": [
        { "level": "Garibaldi Rebuilt", "event": "Play_04_LSD" },
        { "level": "Elysium Alps",      "event": "Play_01_White_Powder" },
        { "level": "SSX3 E-Course",     "event": "Play_MyCustomTrack" }
    ]
}
```

- Garibaldi always plays **LSD**; Elysium Alps always plays **White Powder** —
  both built-in, no bank needed.
- `SSX3 E-Course` plays `Play_MyCustomTrack`, a custom event that must exist in
  `MyBank.bnk`.
- With `OverrideMenuMusic` enabled (see below), the menu plays **APEX**.

### Adding a custom bank

1. Author a Wwise project, create your event(s), and generate a SoundBank
   (`.bnk`). The event names you define are what you put in the JSON.
2. Copy the `.bnk` into the `Music/` folder.
3. Add its filename to `banks`, and reference its event(s) from `levels` /
   `menuEvent`.

## BepInEx config toggles

`BepInEx/config/com.glitcherog.musicplugin.cfg`:

| Section   | Key                 | Default | Meaning                                            |
|-----------|---------------------|---------|----------------------------------------------------|
| General   | `Enabled`           | `true`  | Master switch. Off = no overrides, no bank loading.|
| General   | `VerboseLogging`    | `false` | Log every music decision.                          |
| Menu      | `OverrideMenuMusic` | `false` | Apply `menuEvent` to the main menu.                |

## How it works (for the curious / maintainers)

- Prefix on `MenuManager.LoadScene(LevelEntry)` captures the current level's
  `name` — the earliest reliable point, and it also catches custom mod-map names.
- **Postfix** on `LevelManager.Start()` does the swap: the vanilla `Start` posts
  a random pool track and sets the `"MusicState"` Wwise state group to `Intro`;
  the postfix `StopAll`s that track and `PostEvent`s the mapped event on the same
  `musicPlayer` GameObject, leaving `MusicState` at `Intro` so the game's live
  Intro/Verse/Outro transitions keep working for built-in tracks. A postfix (not
  a false-returning prefix) is used deliberately — `Start` also does racer,
  camera, and HUD setup, so suppressing it would break the level.
- **Menu override** is a prefix on `AkSoundEngine.PostEvent(string, GameObject)`
  that rewrites the vanilla menu event `"Play_00_Menu"` to your `menuEvent` at the
  source. That single event name is posted from both `MenuManager.Start` (cold boot)
  and the `MenuManager.UnloadLevel` coroutine (returning to the menu from a level),
  so one hook covers **every** menu-music entry point — no more return-to-menu gap —
  and the vanilla track never plays even for a frame. The prefix early-outs on a bool
  check when the override is off, so non-menu sound effects are unaffected.

### Fixed from the original

- **Double-play bug:** the old mod used a *void* Harmony prefix that let both the
  original song and the replacement play. This rewrite stops the vanilla track
  before posting.
- **Playlist off-by-one:** the old index-based playlist wrapped with an
  off-by-one (`== Count` reset after use). Selection is now a direct map lookup,
  so there is no wrap to get wrong.

## Status / boot-test pending

The static gate here is a clean compile against the real game DLLs plus
provably-correct use of the current API (verified by disassembly). **All actual
audio playback is boot-pending** — the game could not be run in this environment.

**Compile-verified (static):**
- Builds clean against the shipped `Assembly-CSharp.dll` and `AK.Wwise.Unity.API.dll`.
- Hook targets exist with the expected signatures: `MenuManager.LoadScene(LevelEntry)`,
  `LevelManager.Start()`, `MenuManager.Start()`, `MenuManager.musicPlayer`,
  `LevelEntry.name`, `AkSoundEngine.PostEvent/StopAll/LoadBank`.
- JSON round-trips through `JsonUtility` (Dictionary-free model).
- Cross-platform Music-folder resolution mirrors the working LevelHook.

**Boot-pending (must be tested in-game):**
- That posting the mapped event actually plays the intended song, and that
  `StopAll` cleanly cuts the vanilla random track first.
- That the `"MusicState"` Intro/Verse/Outro transitions still drive a re-posted
  built-in event (expected, since the state group is global — but unverified).
- Custom `.bnk` loading and custom-event playback (entirely dependent on a
  correctly authored bank; the plugin only calls `LoadBank` + `PostEvent`).
- Menu override timing across all entry points (cold-boot menu AND
  return-to-menu-from-a-level, both now covered by the `PostEvent` rewrite —
  verified statically that `"Play_00_Menu"` is the only menu-BGM event and is
  posted from exactly those two sites, but the swap itself is boot-pending).
- Whether a custom event responds to the game's music-state group at all (a
  Wwise-authoring property of the event, not controllable from C#).
