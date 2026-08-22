# Handoff: Radio Big "now playing" pill widget — still not working

## What this is

Porting an approved HTML/CSS/JS prototype of a "now playing" pill widget into a
real in-game Unity/BepInEx feature for the **Radio Big** mod (Tricky Madness's
external-music-player companion mod). Repo:
`/Users/mtvogel/Downloads/claude_scratch/MusicPluginTrickyMaddness` — **not**
the `tricky_mods` repo, a different checkout. Branch `feat/radio-big-external-player`,
12 commits ahead of `origin/feat/radio-big-external-player`, nothing pushed.
**Nothing from this feature has been committed** — nothing has been staged
either, all of it is uncommitted working-tree changes. Do not discard them.

Scope as approved by the user: **"Full pill, real data"** — a real Unity UI
widget (not a mockup), driven by the actual playback state (song title,
artist, elapsed/duration, DJ-talking), not placeholder data.

## Current status: broken, cause unconfirmed

The user's last message was **"ok this isn't working"** with no further
detail — no screenshot, no description of the actual symptom this time. Two
earlier rounds of bugs were found and fixed (below), both structurally
verified (compiles, deploys, binary flags present) but **neither has been
confirmed working by an actual live playtest** since the second fix went in.

**Your first move should be to ask the user what "not working" means now** —
does the game launch/crash? Does the pill render at all? Does clicking do
anything? Does track info (title/tag/progress) ever populate? A fresh
screenshot would help a lot. Don't guess further blind; get the current
concrete symptom first, then check the logs below before changing code again.

## Architecture (verified from source, not from docs — see gotcha below)

- Tricky Madness is Wwise-only with Unity audio disabled, so custom music/DJ
  voice plays via an **external Python process**, frozen into a standalone
  binary with PyInstaller (`radio/freeze.sh` → `RadioBigPlayer` binary).
- The C# BepInEx/Harmony plugin (`radio/RadioBigPlugin/RadioBig.cs`, class
  `RadioBigTM.Plugin`) launches that binary and talks to it one-way via a
  **shared file** the plugin appends command lines to (`radio.cmd`), which the
  player tails. ⚠️ **`RADIO_BIG.md` and `build.sh`'s header comment both
  describe this as a TCP socket — that's stale/wrong.** Verified by reading
  the actual `RadioClient` C# code and `radio_server.py` — it's file-based.
  Fix the docs if you have a spare minute; not done yet.
- **New this session**: a second, separate shared file, `radio.status.json`,
  written by Python roughly every 220ms (atomic temp+rename) and polled by C#
  every 220ms (`RadioStatusReader`, treats a file mtime older than 3s as
  stale/idle). Contract:
  ```json
  {
    "state": "menu" | "racing" | "finished" | "idle",
    "track": { "title": "...", "artist": "...", "source": "ssx3", "elapsed": 12.4, "duration": 214.0 } | null,
    "dj_talking": false
  }
  ```
- **New this session**: the pill widget itself, built entirely in C# (no
  Unity Editor project for this plugin — it's compiled with plain `mcs`
  against the game's own DLLs, no scene/prefab pipeline) in
  `radio/RadioBigPlugin/RadioHud.cs` (the `RadioBigHud` MonoBehaviour: layout,
  animation, open/collapse state) and `RadioHudGraphics.cs` (`ChamferedPanel`
  — a custom `Graphic` drawing the chamfered-hexagon/circle shapes via
  `OnPopulateMesh`; `TransportIcon` — prev/play/pause/next drawn as triangles/
  bars, not text glyphs; `PillPointerForwarder` — bubbles pointer events up).
  `RadioStatus.cs` has the JSON DTOs + `RadioStatusReader`.

## ⚠️ Deploy is manual and has TWO independent halves — easy to fix one and forget the other

Neither half auto-deploys. Both bit us this session (in order):

1. **C# plugin**: `radio/RadioBigPlugin/build.sh --mac` builds
   `RadioBigTM.dll` in the repo only. Must be manually copied to
   `$GAME/BepInEx/plugins/RadioBigTM.dll`.
2. **Python player**: `radio/freeze.sh` (needs `pip install pyinstaller`,
   already present) builds `radio/dist/RadioBigPlayer/` (binary + `_internal/`)
   in the repo only. Must be manually copied to
   `$GAME/BepInEx/plugins/RadioBig/players/mac-arm64/` (whole dir, binary +
   `_internal/`).

`$GAME` = `~/Library/Application Support/Steam/steamapps/common/Tricky Madness/`

**Verify a deploy actually took** before telling the user to retest:
- C#: `md5 -q` the built DLL and the deployed one, must match.
- Python: `"<deployed path>/RadioBigPlayer" --help 2>&1 | grep statusfile` —
  if that prints nothing, you're looking at a stale binary that predates this
  feature (this is exactly what happened the first time — a July/Aug-5 build
  was still running with no idea `--statusfile` exists).

## Bugs already found and fixed this session (verified structurally, not yet confirmed live)

1. **Pill didn't render at all, first launch.** Cause: stale deployed
   `RadioBigTM.dll` (build.sh doesn't auto-deploy). Fixed by manual copy,
   confirmed via matching md5. This one *was* confirmed fixed — the pill did
   start rendering after this.

2. **Pill rendered but click did nothing, and looked like bare icons + a bar
   with no panel/title/tag.** Two separate causes, both addressed:
   - **Click:** `RadioHud.BuildUi()` only checked for an existing
     `EventSystem` once, at plugin boot (main menu). This exact codebase has
     documented precedent (`RadioBig.cs` Awake's comment, ~line 76) for
     un-pinned objects getting destroyed on the menu→race scene transition —
     it already killed the player process once before `DontDestroyOnLoad` was
     added. Hypothesis: the menu's own `EventSystem` isn't pinned and dies the
     same way, leaving zero working `EventSystem` in the whole game once a
     race starts, which would break all pointer input, not just this widget.
     **Fix applied**: `RadioHud.cs` now re-checks every 1s in `Update()`
     (`EnsureEventSystem()`) and creates its own (parented under the plugin's
     already-`DontDestroyOnLoad` GameObject, so it survives future scene
     changes) if none is active. **Not yet confirmed live.**
   - **No title/tag/progress ever showing:** the actually-running
     `RadioBigPlayer` binary was dated Aug 5 — built *before* the
     `--statusfile` status-channel work existed at all, confirmed via
     `ps aux` showing it launched with no `--statusfile` flag and `--help`
     not listing the flag. Since it never wrote `radio.status.json`, the C#
     reader always saw "file doesn't exist" → empty snapshot → blank pill.
     **Fix applied**: reran `freeze.sh`, redeployed, confirmed the new binary's
     `--help` lists `--statusfile`. **Not yet confirmed live.**

Given the user's "ok this isn't working" came right after both of these
fixes were deployed, with zero detail, **do not assume either fix actually
worked** — re-verify from scratch rather than building on top of them blind.

## Where to look first, in order

1. Ask the user exactly what's broken now (see above).
2. `ps aux | grep -i radiobigplayer` — is a player process running at all
   when the game is up? Is it the freshly-deployed one (check the binary's
   mtime) or an old one?
   - Note: there are (were, as of this handoff) several **orphaned zombie
     player processes** from old debug sessions (PIDs launched Jul 22 and
     Aug 5, with stale `--cmdfile /tmp/nope*.cmd` args) that have been idling
     for weeks. Harmless but should probably be killed — get the user's
     explicit go-ahead first, per this session's own safety rules around
     killing processes.
3. `$GAME/BepInEx/plugins/RadioBig/radio.status.json` — does it exist? Is its
   mtime recent (within the last few seconds, while the game is running)?
   What's actually in it?
4. `$GAME/BepInEx/plugins/RadioBig/radio.cmd` — tail it; should show
   `START <level>` / `FINISH` / `MENU` lines as the plugin forwards game
   events, not just `PING`/`QUIT`.
5. `$GAME/BepInEx/LogOutput.log` — BepInEx/Harmony log; Radio Big logs
   client start/stop here.
6. `~/Library/Logs/NathanDearth/Tricky Madness/Player.log` — **Unity's own
   log, separate from BepInEx's.** Exceptions thrown from `Start`/`Update`/
   `FixedUpdate` (e.g. inside `RadioBigHud`) land ONLY here, never in
   `LogOutput.log`. Check both or a silently-crashing widget reads as
   "nothing happened."
7. If BepInEx logging shows nothing and Player.log shows nothing either,
   suspect the plugin didn't load at all (check `BepInEx/plugins/` for the
   DLL, check for a version-drift issue — see `LevelHook-src/CLAUDE.md` in
   the `tricky_mods` repo for the general pattern, though that's a different
   plugin, the drift mechanism is the same class of bug: game update renamed
   or restructured something the plugin depends on).

## Things NOT to touch

- `.gitignore`'s existing modification (`radio/banner_covers/` ignore rule)
  and untracked `radio/make_banner.py` — pre-existing uncommitted work,
  unrelated to this feature, confirmed untouched so far.
- Repo-root `Plugin.cs`, `PluginInfo.cs`, `MusicConfig.cs`,
  `MusicPluginTrickyMaddness.csproj`, `build.sh` — a different, unrelated mod
  living in the same repo. Don't confuse it with `radio/RadioBigPlugin/`.
- Don't commit anything without being asked. Don't force-push or discard any
  of the 12 unpushed local commits on this branch.

## One more loose end

The approved HTML/CSS prototype that's the literal visual spec for this
widget lives at
`/private/tmp/claude-501/.../scratchpad/radio_big_pill.html` from the
session that authored it — **that's a session-scoped scratchpad path and
will not exist in a new chat.** If visual comparison against the prototype
comes up again, ask the user to re-share the file or a screenshot of it.

## Visual spec, transcribed from the approved prototype (2026-08-20)

The prototype HTML was lost with its session scratchpad. The user re-shared a
render of it; this is that render written down so it survives the next context
loss. **If pixels and this text disagree, ask the user for the render again.**

Layout, left to right, one horizontal pill:

- **Badge** — dark navy (`#0A1220`-ish) circle, ~84px, sitting ON TOP of the
  banner's left edge and overlapping it by roughly a sixth of its width. Fill
  is near-opaque, not the translucent glass the banner uses.
  - Inside: a **glowing cyan waveform** — a dense, irregular vertical-line
    lattice (think an audio waveform / spectrogram slice), bright cyan with a
    soft bloom, NOT a 3-bar equalizer. This is the design's signature element.
- **Banner** — chamfered hexagon: top-right and bottom-left corners cut ~20px,
  top-left and bottom-right left square. Fill is a light steel glass that runs
  a **diagonal gradient** from near-white at the upper-left to a cooler blue-
  steel at the right, with a brighter sheen band running through it. Thin
  light rim.
  - **Tag chip** (upper-left of banner): small frost-grey chamfered chip, dark
    navy bold text, letterspaced, tiny — e.g. `SSX3`.
  - **Title** (right of the chip, same baseline): large bold dark-navy caps,
    e.g. `ELYSIUM ALPS`. Dominant text element.
  - **Transport row** (lower-left of banner): prev / play-pause / next.
    - prev + next: small dark outline glyphs, no backing.
    - play-pause: a **chamfered cyan key** (same corner-cut language as the
      banner, not a plain square) with a dark navy pause glyph on it.
  - **Progress bar** (right of the transport row, vertically centered on it):
    long thin track; filled portion cyan, remainder a muted grey-blue. Filled
    portion in the render is roughly a third.
  - **Time** (far right, after the bar): small muted grey-blue, single value
    e.g. `2:39` — note the current code renders `elapsed / duration` instead.

Deliberate simplifications the code already documents (blur, LED trace,
is-playing/is-paused split, track-change sting) stay dropped. The three that
are NOT acceptable simplifications, because they are the visual identity:
the waveform glyph, the banner gradient, and the chamfered play key.

---

## Session 2026-08-20 (second pass): causes found, fixed, deployed — awaiting playtest

The "Where to look first" checklist above is **spent**. The symptom was
concrete this time ("it shows up, looks incorrect, and cannot be clicked …
it also sometimes overlaps UI elements in the menus"), and all three parts
now have identified causes. Don't re-run that checklist; start from here.

### Ruled out (so don't re-chase)

- Deploy freshness — repo and deployed DLL md5 matched, deployed player
  supports and is launched with `--statusfile`.
- The status channel — `radio.cmd` showed real `MENU`/`START <level>` lines,
  `player.log` showed real DJ track picks, `radio.status.json` was being
  written fresh.
- A silent crash — zero exceptions in `Player.log`.
- The four orphaned `RadioBigPlayer` zombies — their cmdfile/statusfile both
  defaulted to `None`, so they were inert. Killed anyway (SIGTERM was ignored,
  needed `kill -9`), with the user's explicit go-ahead.
- **Cursor lock is NOT why clicks failed.** IL-verified: `Assembly-CSharp`
  never calls `Cursor.set_lockState` (0 hits on `CursorLockMode`); all 7
  `Cursor::` calls are `set_visible`, in `MenuManager`. During a race the
  cursor is invisible but *not* locked, so clicks do register — you just
  can't see where you're aiming. ⚠️ Caveat: `MulticamMod`'s
  `FreecamController.SetCursorLocked` *does* lock it every frame while
  freecam or mouse-look is on, which kills clicks everywhere.
- **The new Input System is not exclusive.** `activeInputHandler = 2` ("Both")
  in `globalgamemanagers`, and all the legacy axes `StandaloneInputModule`
  needs (Horizontal/Vertical/Submit/Cancel) exist.
- **Nothing outranks the HUD canvas.** Max `sortingOrder` in any game scene
  is 2; our canvas is 5000. No full-screen raycast blocker.

### Causes found

1. **"Looks incorrect" — `RectMask2D` cannot clip a bare `Graphic`.**
   `ChamferedPanel` and `TransportIcon` derived from `Graphic`, but
   `RectMask2D` only tracks `HashSet<IClippable>` / `HashSet<MaskableGraphic>`.
   So while the banner sat collapsed at width 0, every `Image`/TMP child
   culled correctly and the two custom graphics **leaked out of the mask** —
   which is exactly the "bare icons and a bar with no panel" the screenshot
   shows. Both now derive from `MaskableGraphic`.

2. **"Cannot be clicked" — most likely the `!hasTrack` early return**, not a
   raycast failure. Proven from the screenshot: the badge measured ~66px
   (≈ `IdleSize` 56, not `OpenSize` 84), the tag chip was still at its
   build-time `sizeDelta (50,16)`, and the chip was **white** — `Graphic`'s
   constructor default, which the old code only ever overwrote *inside* the
   `hasTrack` branch. So `hasTrack` was false and `OnPillClicked` returned
   immediately. The raycast path itself checked out.

3. **Menu overlap — the widget had no visibility gate at all.**

### Fixes applied (all uncommitted, per the no-commit rule)

- `RadioHudGraphics.cs` — rewritten. Both custom graphics rebased onto
  `MaskableGraphic`; zero-size guards; diagonal gradient support on
  `ChamferedPanel`; **new `WaveformGlyph`** restoring the design's signature
  badge art (21 procedural bars, each drawn as a wide dim glow copy behind a
  core bar).
- `RadioBig.cs` — added `Plugin.IsRacing`, set first-hand by the existing
  Harmony patches (`true` in `LevelManagerStart_Postfix`, `false` in
  `LevelManagerFinish_Postfix` and the `PostEvent_Prefix` MENU branch). This
  is deliberately NOT read from the status file's `state` string — the file
  is a display feed, not a state source. It is also why we don't need
  reflection on `LevelManager`'s private `state` enum, which is the only
  other signal (there is no public one; `LevelManager` has no `Instance`).
- `RadioHud.cs` — rewritten. Racing gate on `_canvas.enabled`; **auto-expand
  on track change** with a 6s auto-collapse (the click is kept but demoted to
  a bonus, since the cursor is invisible mid-race); tag chip coloured at
  construction; badge vertically centred and drawn *over* the banner; stale
  layout reset in the no-track branch; the three design elements restored
  (waveform, banner gradient, chamfered cyan play key); and **diagnostic
  logging added** — the file previously had zero log statements in 422 lines.
- **Removed the EventSystem creation entirely — it was a game-wide bug we
  introduced.** IL-verified: `BuildUi` runs in the BepInEx chainloader
  *before the first scene loads*, so `FindObjectOfType<EventSystem>()` was
  always null and the guard could never fire; `EventSystem.current` is
  `m_EventSystems[0]` and `OnEnable` appends, so our `RadioBigEventSystem`
  won permanently; `EventSystem.Update` opens with `if (current != this)
  return;`, so **the game's own `InputSystemUIInputModule` never processed**
  and all game UI was silently running off our `StandaloneInputModule`.
  Witness in `Player.log` right after "Chainloader startup complete":
  `There can be only one active Event System.` The original premise for
  creating one was wrong too — `Menu.unity` loads *additively* and is never
  unloaded, so the game's EventSystem survives the menu→race transition.

### Progress bar: why it's width-driven, not `Image.Type.Filled`

`Image.OnPopulateMesh` null-checks `activeSprite` and falls back to a plain
full quad **before** it ever reads `fillAmount`, and these Images have no
sprite — so `Type.Filled` could never have worked. The fill resizes the rect
instead. Don't "restore" `Type.Filled`.

### State: built, deployed, NOT playtested

DLL built (`build.sh --mac`) and copied to `$GAME/BepInEx/plugins/`,
md5 `1c8d721af890c1f43f3b526638288f37` on both sides. Deployed DLL confirmed
to contain `WaveformGlyph` and to contain **zero** references to
`RadioBigEventSystem` / `StandaloneInputModule`. The Python player was
already fresh (Aug 20 15:38) and is unchanged.

**Nothing here has been confirmed live.** Next session: playtest, and grep
BOTH `BepInEx/LogOutput.log` and `~/Library/Logs/NathanDearth/Tricky Madness/Player.log`
for `[Radio] HUD` lines — shown/hidden, auto-expand, and clicks all log now.

### Still open

- The transport buttons are **inert by design** and have no `Button`
  component: `radio.cmd` is append-only game→player and `radio.status.json`
  is read-only player→game, so there is no reverse channel for prev/next to
  send on. Adding one is a real feature, not a bug fix.
- `JsonUtility`'s handling of `"track": null` is still unverified. The HUD is
  written to be correct either way (it requires a non-empty title, not just a
  non-null object) — see the comment in `RadioStatus.cs`.
- `RADIO_BIG.md` and `build.sh`'s header still describe the transport as a
  TCP socket. Still wrong, still not fixed.

## Session 2026-08-20 (third pass) — the prototype actually exists

**Correction to this doc's earlier claim:** `radio_big_pill.html` was never lost.
It is at the repo root, 1444 lines, untracked. It is the spec, and it was read
in full this pass. Anything below that describes the visuals as "reconstructed
from a transcription" is stale.

**What changed**

- `WaveformGlyph` (21 vertical bars, invented) is **deleted**. Replaced by
  `PulseFieldGlyph` in `RadioBigPlugin/RadioHudGraphics.cs` — a direct port of
  the prototype's `PulseFieldGlyph v2` canvas class: the pinched lattice sheet
  (`pow(cos(xn*PI/2), 1.5)` taper driving both height and z-depth to zero at the
  tips), all rows riding the same oscilloscope trace at `LATTICE_RIDE = 0.34`,
  yaw + pitch + one perspective divide, per-segment depth-driven alpha/width/
  colour. Noise helpers, per-state parameter targets and the envelope maths are
  transcribed from the prototype, not re-derived.
  - Not portable: the canvas' `lighter` (additive) compositing and its three
    blurred-buffer bloom passes. There is no Unity Editor project here, so no
    material or shader asset — a wide dim pass under a narrow hot pass stands in.
  - Dropped: the dj-talking DJ-ID face knockout.
  - Density is lower than the prototype (5 rows / 9 ribs / 34 samples vs 5 / 10 /
    26 segments): ~400 quads per rebuild. **That is a judgment call about uGUI
    per-frame mesh cost, not a measured budget.**
- The glyph now self-drives: its own `Update()` steps the clock and marks itself
  dirty. `RadioHud.Render` sets `_glyphField.State` (Idle / Playing / DjTalking)
  and nothing else. `Paused` exists in the enum but is unreachable — the status
  JSON carries no paused flag.
- Added `CornerBrackets` (the `.rb-bracket` viewfinder corners, 24×2 arms held
  20px clear of each chamfer) and `DashedChamferTrace` (the `.rb-led` crawling
  dashed rim, `15 12` dasharray, −108px over 5.5s, dashes solved analytically
  per edge so it costs ~30 quads a pass rather than ~400). Both are children of
  the banner, so its `RectMask2D` clips them for free while collapsed.
- Both new animated graphics **early-out when their Canvas is disabled**. Canvas
  `enabled = false` does not stop a MonoBehaviour's `Update`; without the guard
  they would queue a full mesh rebuild every frame through the whole menu.

**Logging — why the last playtest produced no evidence**

`VerboseLogging = false` is the default in
`$GAME/BepInEx/config/com.mtv.radiobig.cfg`, and every HUD log was behind
`Plugin.Verbose`. Three logs are now unconditional `Log.LogInfo`, all on-change
only (never per-frame): the racing show/hide transition, the auto-expand, and a
status line reporting `fresh` / `trackObj` / `hasTitle` / `state` / the status
file path. If the banner still never opens, that third line says which of the
three conditions failed.

**Verified this pass**

- Compiles clean (7 pre-existing `CS0649` DTO warnings only).
- Deployed to `$GAME/BepInEx/plugins/RadioBigTM.dll`, md5 matched against the
  build output.
- Deployed binary contains `PulseFieldGlyph` / `CornerBrackets` /
  `DashedChamferTrace` and **zero** references to `WaveformGlyph`.

**Not verified**

Nothing here has been seen running. The whole visual half is unplaytested.

## Session 2026-08-20 (fourth pass) — two separate bugs, one solved

The instrumented run finally produced evidence. The single visible symptom
("nothing is shown") was **two independent faults**.

### 1. The status reader froze — SOLVED, tested

Log line from the race: `HUD status: fresh=True trackObj=False hasTitle=False
state=menu`, emitted **once** and never again, while `radio.status.json` on disk
read `{"state": "racing", "track": {"title": "Rock Star ~ ...", ...}}`.

Cause: `JsonUtility` parsed the menu payload (`"track": null`) fine and then
failed on every payload carrying a real track object. `Poll()` keeps the last
good snapshot on failure — correct, so one bad read can't blank the HUD — but
the *only* log on that path was `Plugin.Verbose`, and `VerboseLogging` defaults
to false. So the HUD sat on "menu, no track" for the entire race with a
completely clean log. Both halves were working; the join was silently dead.

Fix: `JsonUtility` replaced by `RadioJson` in `RadioStatus.cs` — an explicit
extractor for this flat 7-field shape. Also removes the two hazards that file's
own comments already flagged: the undefined JSON-`null`-onto-`float` behavior
(and its `DurationNullRe` regex workaround) and the UNVERIFIED question about
whether a nested `null` maps to a C# null. Both are now decided in code and
tested. Culture-invariant number parsing while we're here.

**Verified, not assumed:** the parser is Unity-free by construction, so it was
compiled with `mcs` and run against 20 cases outside the game — including the
verbatim payload from the live status file, `"track": null`, `"duration": null`,
escaped quotes and a `}` inside a title, truncation, and an absent `track` key.
All pass. Harness: `scratchpad/radiojson_test.cs`.

Also: every silent-return path in `Poll()` now logs unconditionally via
`Problem()`, deduped so a stuck reader costs one line rather than one per poll.

### 2. The glyph draws nothing — NOT solved, instrumented

The badge circle renders; the inside of it is flat `(47,58,67)` with zero
geometry — verified by sampling the screenshot's pixels, not by eyeballing it.
**This is true of the old 21-bar `WaveformGlyph` too**, which was opaque and
~2px wide and would have been unmissable. Two completely different drawing
implementations rendering exactly zero pixels points at the layout or the
render path, not at either one's geometry math.

Ruled out by reading the code: nothing calls `SetActive(false)` or touches
`enabled`/`localScale`; the field is the last-drawn node in the subtree so the
circle is not covering it; no `RectMask2D` is an ancestor (the only one is on
the banner, a sibling); the rect should compute to 46x46 inside a 56x56 badge.

Open suspicion, unproven: `BuildUi` creates the canvas with
`_canvas.enabled = false`, so every Graphic in the pill has its `OnEnable` run
with no active canvas above it — `Graphic.CacheCanvas` only accepts an
active-and-enabled canvas, so these register against nothing. The circle
survives it; a deeper child may not.

Added to answer it in one line, next run:
- `RadioBigHud.ReportLayout()` — one shot in `Awake`, prints the real canvas
  mode/enabled/order and the actual `pill` / `glyph` / `field` rects.
- `PulseFieldGlyph` — one shot from `OnPopulateMesh`, prints the rect it built
  against, `vh.currentVertCount`, the line width, `activeInHierarchy`, the
  resolved canvas and `lossyScale`. **If that line never appears at all,
  `OnPopulateMesh` is not being called, which is itself the answer.**

Speculative fix applied at the same time (judgment call, unverified): line width
floor raised from `max(0.7, W*0.016)` to `max(1.4, W*0.030)`. The prototype's
constant assumes a devicePixelRatio backing store *and* additive compositing
stacking strokes into brightness; here one unit is ~1.25 device pixels at idle
size and uGUI does no antialiasing, so a sub-pixel quad can miss every sample
point and rasterize to nothing. This does not explain the old opaque bars
vanishing, so it is unlikely to be the whole story.

## Session 2026-08-20 (fifth pass) — glyph root-caused, pill made clickable, transport wired

### 1. Status reader — CONFIRMED FIXED in game

The 18:46 run logged `HUD status: fresh=True trackObj=True hasTitle=True
state=racing` and the screenshot shows the banner fully populated: title
"Mirage", the `ssx2012` source tag, transport keys, progress bar, 0:02 elapsed,
the dashed chamfer trace and the corner brackets. `RadioJson` closes bug 1.

### 2. The glyph draws nothing — ROOT-CAUSED, fixed, awaiting a confirming run

The fourth pass's suspicion was right in mechanism and wrong in target. The
instrumented run printed `glyph mesh #1: rect=(0,0,46,46) verts=1616 lw=1.40`
followed by `glyph tick blocked: canvas=<unresolved>` — so the mesh **was**
being built correctly, once, at `Awake`, and then never again.

`Graphic.CacheCanvas()` only ever caches a canvas that is *active and enabled*.
`BuildUi()` creates the hud's canvas with `_canvas.enabled = false`, and the hud
hides itself for the rest of its life by toggling that same flag. So
`Graphic.canvas` reads null the whole time the hud is hidden, and — measured,
not assumed — was still null after it was shown again. `PulseFieldGlyph.Update`
guarded on `canvas != null` and therefore returned early forever, leaving the
sheet frozen on the single Awake-time mesh. A static 1616-vertex hairline sheet
inside a 46px circle is visually indistinguishable from nothing.

Fix: an explicit `public bool Animate` on `PulseFieldGlyph` and
`DashedChamferTrace`, set on the line right beside `_canvas.enabled = visible`
in `RadioBigHud`. Same statement, same truth, no way for the two to drift — and
the animators no longer ask a component that structurally cannot answer while
hidden.

**Why the old `WaveformGlyph` looked equally dead:** same guard, same freeze.
Two implementations, one shared bug — which is exactly what "two different
renderers both draw zero pixels" was pointing at.

### 3. The pill was unclickable — fixed, awaiting the same run

Two causes, both confirmed by reading the game's IL rather than guessing:

- **No EventSystem in a loaded level.** The old `ReportEventSystem()` logged
  behind `Plugin.Verbose`, so its silence proved nothing either way. It is now
  `EnsureEventSystem()`, logging unconditionally: it stands up its own
  `EventSystem` + `StandaloneInputModule` when the scene has none, and
  **deactivates it** the moment the game's own becomes active or the hud hides.
  Two enabled EventSystems is a hard input break for the entire game, so ours
  always yields.
- **The cursor is hidden from level load.** `MenuManager` only ever calls
  `Cursor.set_visible` and never touches `CursorLockMode` (IL-verified), so
  `SetCursorVisible` shows the pointer for exactly as long as the banner is
  open. Closing the hud drops our claim **without** hiding the pointer: racing
  with the menu over a cursor we'd sometimes lose would leave the results screen
  unclickable, which is a far worse failure than a stray cursor.

### 4. Transport keys are live — skip + play/pause

Scope decision (user, 2026-08-20): **skip and play/pause only**.

- **Prev stays inert on purpose.** Going back means the DJ has to remember what
  it already played instead of only drawing forward from its shuffle bag — a
  change to the brain's state, not a command. Out of scope, not forgotten.
- **Real media keys were considered and dropped.** macOS routes them to the
  focused app through a private event tap; Unity's input never sees them, so it
  would take a native helper. User's call: scrapped for now.

Wiring, C# side: a new `TransportButton` MonoBehaviour appends a verb to the
**same append-only `radio.cmd`** the Harmony patches already use for
START/FINISH/MENU. There is still no reverse channel and none is needed — the
player answers by changing what it writes into `radio.status.json`, which the
hud already polls. Deliberately **not** a `UnityEngine.UI.Button`: its ColorTint
transition drives `targetGraphic`, which is the backing panel for the play key
and the icon for the others — the inconsistent half-disabled look this used to
have. `TransportIcon.IconKind` became a property so the runtime Play↔Pause swap
actually marks the mesh dirty; uGUI rebuilds only what something dirties.

Python side: `RadioPlayer` gained real pause bookkeeping (`_paused_at` /
`_paused_total`), because `elapsed()` is wall-clock since `play_music()` and a
pause would otherwise keep advancing the hud's progress bar over silence.
`radio_server._dispatch` gained `SKIP|NEXT`, `PAUSE`, `RESUME`, `TOGGLE`.
`paused` is now in the status JSON, and the C# `StatusDto`/`RadioStatusSnapshot`
carry it.

Two traps paid for, both with tests:
- pygame reports a **paused** stream as not-busy on some backends, so
  `_wait_for_track_end` would have read a pause as "song over" and skipped to
  the next track the instant you hit pause. It now waits on
  `music_busy() or is_paused()`.
- `skip_track` un-pauses before stopping: a paused stream ignores `stop()` on
  some SDL backends, which would strand the wait loop forever.

**Verified, not assumed:** 9/9 assertions on the pause/elapsed clock (real
pygame, mocked mixer); 14/14 through the real `RadioServer._dispatch` with a
stub player — verb case-insensitivity, PAUSE/RESUME idempotency,
skip-clears-pause, unknown verbs survived, QUIT returns False; emitted JSON
confirmed as `{"state": ..., "track": {...}, "dj_talking": false,
"paused": false}`; 23/23 C# parser assertions including three that pin `paused`
absent → false, and two that prove `paused` and `dj_talking` can't read each
other's value.

**Test harness moved.** `scratchpad/radiojson_test.cs` held a hand-pasted
duplicate of the parser, so it could have gone on passing while the shipped code
broke. It is now generated: `scratchpad/gen_rjtest.py` **slices `TrackDto`,
`StatusDto` and `RadioJson` straight out of `RadioStatus.cs`**, appends the
cases, compiles and runs. One command, and it cannot test stale code.

### Still open

- **One confirming run.** The three fixes above (glyph animating, pill and keys
  clickable, TOGGLE/NEXT actually pausing and skipping) are deployed and
  byte-verified but have not been seen working in game.
- **Temporary instrumentation to remove once confirmed:**
  `RadioBigHud.ReportLayout()` and the `_rebuilds` mesh log in
  `PulseFieldGlyph.OnPopulateMesh`.
- `RADIO_BIG.md` and `RadioBigPlugin/build.sh`'s header still describe the
  transport as a TCP socket. It is file-based, and has been for a while.

## Session 2026-08-20 (sixth pass) — the EventSystem was my regression; it is gone for good

**Read this before touching pointer input again.**

The fifth pass "fixed" the unclickable pill by standing up an `EventSystem` +
`StandaloneInputModule` when the scene had none. That broke controller input,
and it was a **re-introduction of a bug an earlier pass had already found,
IL-verified and removed** — the warning was sitting in `RadioHud.cs` directly
above where the new code was added, and I appended a contradicting paragraph to
it instead of reconciling with it. Both paragraphs are now replaced by one.

Why a second EventSystem is never survivable here:

- `EventSystem.get_current` is `m_EventSystems[0]` and `OnEnable` *appends*, so
  whichever registers first wins **permanently**.
- `EventSystem.Update` opens with `if (current != this) return;` — the loser
  never processes another event.
- The game's own EventSystem lives in `Menu.unity` (stock `EventSystem` +
  `InputSystemUIInputModule`). `Menu.unity` is loaded **additively and never
  unloaded**, so during a race that EventSystem is not gone, just **disabled**.
  An "is one active right now?" guard therefore always concludes it should
  create one — and ours then holds slot 0 for the rest of the process. The
  moment the game re-enables its own for a pause or results screen, the game's
  is the loser and its controller navigation is dead.

That last step is the trap: the fifth-pass guard looked careful (it stood down
whenever it saw an active foreign EventSystem) and still lost, because it only
re-checked when the hud's visibility flipped, and the game re-enables its own
*inside* a race.

### What replaced it

`RadioBigHud.PollPointer()` hit-tests the mouse itself, every frame the hud is
visible, with `RectTransformUtility.RectangleContainsScreenPoint` over ~5 rects
(null camera — the canvas is ScreenSpaceOverlay). Transport keys are tested
before the banner, since they sit on it; keys are only live while the banner is
open, because a rect still contains a point after `RectMask2D` has clipped away
everything drawn in it.

Deleted outright: the `GraphicRaycaster` on our canvas, `PillPointerForwarder`,
`TransportButton`, and every `raycastTarget = true`. **Verified in the built
DLL**, not assumed: zero metadata references to `EventSystem`,
`StandaloneInputModule` or `GraphicRaycaster` remain.

⚠️ This needs `UnityEngine.InputLegacyModule.dll` on the compile line —
`UnityEngine.dll` only *type-forwards* `Input`, which fails as `CS1070`, not as
a missing type. Legacy input is confirmed live in this game: its own
`Assembly-CSharp` calls `UnityEngine.Input::get_mousePosition` and
`GetMouseButton` (19 legacy call sites), so "Active Input Handling" is not
New-only and `Input` will not throw.

### The glyph: animation fixed, visibility still unexplained

The fifth-pass `Animate` flag **worked** — log-confirmed, not inferred: mesh
rebuilds #600 / #1200 / #1800 all report `canvas=RadioBigCanvas enabled=True`,
and the rect breathes (46.00 → 63.84 → 46.00) as the badge scales. So the sheet
is now genuinely animating, every frame, against a resolved canvas.

The user still reports nothing visible inside the circle. That is a **different
fault from the freeze**, and the earlier "two unrelated implementations both
draw zero pixels" reasoning now resolves cleanly: both were frozen by the same
`Graphic.canvas` guard, and at that time `canvas` was null — a Graphic with no
canvas is in no batch and genuinely draws nothing. So the old sampling proved
the freeze, not a geometry bug.

Ruled out by reading the code this pass: sibling order is correct (`BuildBanner`
runs before `BuildGlyph` deliberately, so the badge is the later sibling and
draws on top, and the field is a child of the badge so it draws on top of that);
the banner's `RectMask2D` does not cover the badge, which is not its descendant;
the field's rect really is 46x46 centred; `AddQuad` and the circle's own mesh
build use identical `AddVert`/`AddTriangle`/UV patterns, and the circle renders.

What is left is the CanvasRenderer layer, so the mesh log now also prints
`GetAlpha()`, `GetInheritedAlpha()`, `cull`, `materialCount` and the graphic's
colour. Those are the only things that can swallow a populated mesh once the
canvas has resolved. **This is a diagnostic, not a fix — the next run decides
it.**

## Session 2026-08-22 (seventh pass) — glyph root cause is a float32 NaN

The sixth pass's "contradiction" (mesh correct, renderer healthy, nothing drawn)
resolves to one fact: **`TaperAt(±1)` returned NaN.** `Mathf.PI / 2f` rounds
*above* true π/2 in float32, so `Mathf.Cos` of it is `-4.37e-8`, and
`Mathf.Pow(negative, 1.5f)` is NaN. Reproduced outside Unity with `mcs`/`mono`:
`cos(PI/2)=-4.371139E-08  pow=NaN`.

Every guard downstream fails *open* on NaN (all comparisons against NaN are
false): `TaperAt(xn) < 0.02f` doesn't skip the rib, `alpha <= 0.012f` doesn't
skip the segment, `len < 1e-4f` doesn't skip the quad. The NaN vertices reach
the `VertexHelper`, poison the mesh bounds, and the **native** canvas cull drops
the whole renderer — while `canvasRenderer.cull`, alpha, material count etc.
all still read healthy from C#, because those are the managed-side flags, not
the native bounds test. Nothing throws, so `Player.log` is silent too.

Why `scratchpad/glyph_sim.py` showed a full lattice: numpy is float64, where
`cos(π/2)` is `+6e-17`. The sim faithfully reproduced the *algorithm* and could
not reproduce the *precision*.

Fix (already in `RadioHudGraphics.cs` when this pass started, unrun): clamp in
`TaperAt` (`Mathf.Max(0f, c)`) and a NaN skip at the top of `StrokePoly`. This
pass turned the silent skip into a **one-shot `LogWarning`** (`[Radio] glyph: NaN
vertex skipped`) so the failure mode is never invisible again, and removed the
temporaries: `ReportLayout()`, the `_rebuilds` mesh dump, and the `ProbeFill`
magenta probe (the probe never ran — the deployed DLL had already moved past it).

**Awaiting a confirming run.** Expected: cyan lattice in the badge, and *no*
`NaN vertex` line in `LogOutput.log`. If the warning does appear the clamp missed
a path and the printed vertex pair says which.

**Confirmed in game 2026-08-22 09:28 run**: lattice visible ("much better"),
zero `NaN vertex` warnings. Glyph bug closed.

### Same pass, three follow-ups from that run (deployed, unconfirmed)

1. **Badge blue while the DJ speaks the race intro.** `Render` computed
   `dj = hasTrack && snap.DjTalking`, but `dj_brain._race_broadcast` speaks the
   intro *before* `_set_status(track=...)` (deliberately, so elapsed/duration
   line up with the song). No track ⇒ `Idle` ⇒ blue. Now `dj = snap.Fresh &&
   snap.DjTalking`, independent of the track.
2. **DJ face restored.** The prototype's `_knockout` + `_drawFace` (the "dropped"
   item in session 3) are ported: `PulseFieldGlyph.Knockout` repaints the badge
   colour (`KnockoutColor`, handed in from `RadioBigHud.GlyphFillDark`) as a
   radial fade — uGUI has no `destination-out`, but over an opaque badge the
   picture is identical — and `DrawFace` flattens the beziers to polylines
   (`FaceSteps = 8`) through a flat-shaded `StrokeFlat`. Y-flipped for uGUI,
   lens tilt sign flipped with it. `_faceA` lerps like the other params; drawn
   only in `DjTalking`, same hard gate as the prototype. Detail (moustache,
   mouth, glints) above `hh > 13`, i.e. only while the badge is open.
3. **Closed pill unclickable.** *Judgment call, not measured*: the pointer is
   hidden while closed, so aiming at the 56 px badge was blind. Moving the
   mouse > 3 px now reveals the cursor for `CursorRevealSeconds = 2.5` (guess),
   media-player style; `UpdateCursor()` = `_open || reveal window`. If it was
   not the hidden cursor, next suspect is `Over()` on `_pillRects` while closed.

Media keys: user re-opened the question 2026-08-22; an investigation report is
pending (see the session log).

### Same day, design pass on the face + size (user decisions 2026-08-22)

- **Face is FILLED, not line art.** The first port copied the prototype's
  `_drawFace` strokes 1:1; against the inspiration mockup (solid silhouette,
  shades/goatee cut out in badge colour) that was the wrong reading and
  vanishes at 46 px. `DrawFace` now builds filled polygons via a centroid fan
  (`FillPoly`): skull egg (the prototype's bezier outline), ear ellipses, one
  wraparound dark band with a bridge notch, a dark goatee wedge with a skin
  mouth slit. Head is `0.58 × half-size` (prototype 0.44 — too small in the
  circle). Previewed in Python (`scratchpad/face_preview.png`), not yet in game.
- **Decisions:** face shows **only while the DJ speaks** (user chose this over
  the mockup's always-on); **no mic swap, no banner silhouette** — "the DJ
  isn't playing the music, the music is".
- **Whole pill scaled 1.4×** via `_pill.localScale` (`PillScale`) about its
  bottom-left pivot — every child offset is in prototype units, so one scale
  beats retuning thirty constants. *Judgment call*: 56 px read as small next to
  the game's own ~40 px labels; not measured.
- **Media keys — investigated, not built.** Verdict: do it in the Python player
  (it already outlives exactly the game's lifetime and `_dispatch` is
  lock-guarded): macOS `MPRemoteCommandCenter` via pyobjc (no TCC prompt, no
  app bundle — proven by mpd-now-playable), Windows `RegisterHotKey` +
  `VK_MEDIA_*` via ctypes. In-plugin is a dead end: `UnityEngine.KeyCode` has
  no media keys (IL-verified), and a Mac event tap means a keyboard-monitoring
  permission prompt attributed to the game. **PREV does not exist** anywhere —
  no play history in `DJBrain`, no verb — so it's ~2 h of new work whichever
  way the key arrives. 30-min kill-criterion spike first: bare pyobjc script
  on this Mac, then the same thing PyInstaller-frozen with the game fullscreen.

- Goatee thinned per inspo: a thin moustache bar (`cx ± hw*0.30`, `y - hh*0.42..0.50`) and a
  narrow chin strip (`cx ± hw*0.13` tapering to the chin at `y - hh*0.98`), skin gap between.
  Deployed DLL md5 `364558d4f2fda46c1a870f2489efed60`. Preview only — not yet seen in game.

### 2026-08-22 — DJ face is now a texture, not a polygon fan

The mesh face was replaced wholesale. It was an 8-samples-per-bezier centroid
fan, and uGUI anti-aliases nothing, so the skull edge was visibly faceted and
the stair-stepping was worst at exactly the 80–120 px the badge runs at. A
pre-rendered texture gets clean edges, plus shading and visor speculars that a
vertex-colour fan cannot express at all.

**Where the art lives.** `radio/RadioBigPlugin/make_dj_face.py` is the source of
truth; `dj_face_lit.png` / `dj_face_dark.png` beside it are **generated output**
— edit the script, never the PNGs. Regenerate with:

    python3 radio/RadioBigPlugin/make_dj_face.py

Needs PIL + numpy. Draws at 4× and box-downsamples to 512 — that resample *is*
the anti-aliasing, there is no analytic coverage anywhere in it.

**Why two layers.** `dj_face_dark.png` is the head silhouette, tinted at runtime
with `KnockoutColor`; `dj_face_lit.png` is the skin with the visor / moustache /
goatee punched out as holes, tinted with the accent `Shade()`. The dark layer
showing through those holes is what the old `cut` colour used to paint, so the
features stay correct if `KnockoutColor` is ever retuned, and the skin still
tracks the amber/cyan accent lerp. A single baked RGBA would have frozen both
colours at author time. The lit layer's texture RGB is a **luminance field**
(cranium highlight, jaw falloff, edge darkening, rim light), so a flat tint
lands shaded.

**Runtime.** New `DjFaceArt` static class in `RadioHudGraphics.cs` loads both
PNGs once from embedded resources (`Assembly.GetManifestResourceStream`, bare
filenames as logical names) via `Texture2D.LoadImage`. `PulseFieldGlyph` builds
two `RawImage` children in `EnsureFace()` — children of the Graphic, so they
draw above its mesh with no second canvas and no sorting override — stretched to
its rect so they rescale with the badge for free. `PaintFace()` drives tint and
fade from the same `_faceA` and `Shade()` as before. `Knockout()` still runs in
`OnPopulateMesh`; only `DrawFace` and its geometry helpers (`FillPoly`, `Bez`,
`Ellipse`, `P`, `FaceSteps`) are gone.

Three things here are load-bearing and silent if broken:

- **`build.sh` gained `-resource:` for both PNGs and a
  `UnityEngine.ImageConversionModule.dll` ref** (that is what supplies
  `Texture2D.LoadImage`). Logical names are the bare filenames — a path prefix
  and `GetManifestResourceStream` returns null, which degrades to a *faceless
  badge*, not an error.
- **Textures are created with `mipChain: true`.** 512 px drawn at ~100 px
  unmipped shimmers while the badge animates between its idle and open sizes.
- **The art script writes RGB across the whole canvas**, not just inside the
  alpha mask, so mip generation has no transparent-texel colour to bleed into
  the edges.

Asset geometry is pinned to the old layout on purpose: head height is 0.58 of
the texture and the head centre sits 3 px high, matching the mesh face's
`hh = half * 0.58` and `y + hh * 0.02`. The icon did not change size or position
across the swap. Move `HEAD_TOP`/`HEAD_BOT` and the badge composition moves.

**Verified:** builds clean under mcs; `monodis --manifest` shows both resources
embedded under the right logical names; `DrawFace`/`FillPoly`/`Bez` are absent
from the DLL's metadata and `DjFaceArt`/`EnsureFace`/`PaintFace`/`RawImage`/
`LoadImage`/`GetManifestResourceStream`/`Knockout` are present. Deployed md5 was
`826c11c1620638a65dcf88111052eed6` — **superseded, see the next subsection.**

**NOT verified — nobody has launched the game.** The whole Unity-side path is
unexercised: resource stream → `LoadImage` decode → mip build → the two
`RawImage` children actually parenting and stretching → the layers rendering
above the glyph mesh rather than behind it. Preview render of the composite
(80 px / 120 px / mid-fade / raw 512) is in the session scratchpad as
`face_preview_new.png`, generated by `preview_face.py` beside it — that proves
the *art*, not the wiring.

*Judgment calls, not measured:* the whole facial layout (jaw width, ear seating,
visor slimness, moustache-to-goatee ratio) was iterated by eye against the
described inspo across four passes; shading constants (`0.72 + 0.28 * inner`,
`0.30 * spec`, rim `0.42`) were tuned to stop it reading as an airbrushed 3D
ball; the lit tint stayed at `Shade(0.70f)` even though multiplying by the
luminance field makes the face slightly darker on average than the old flat
fill — kept because that is what the preview the user approved was rendered at.

#### Same day, second pass — the geometry is now TRACED from the real inspo

Everything above about the *plumbing* still holds; only `make_dj_face.py`
changed. The first pass built the face from a verbal description of the
inspiration art. The actual image
(`/Users/mtvogel/Downloads/claude_scratch/tricky_mods/Gemini_Generated_Image_hplxkphplxkphplx.png`,
the "DJ Autonomo ID Icon" panel) turned out to disagree with that description on
almost every proportion, so the shapes were re-derived by **measuring** it:
crop `(185,105)-(300,245)`, segment the icon by cyan threshold
(`G>150 & B>150 & R<G-40 & V>170`), dump per-row runs. That gives the reference
frame the script now works in — head cx 55, crown y 16, chin y 122, so 106 px
tall — and the `PROFILE` table of measured half-widths that drives the
silhouette. **Re-derive rather than nudge**: every landmark in the script is
quoted in those crop coordinates and mapped through `CY`/`CXo`/`CW`, so a new
measurement drops straight in.

What was wrong and is now right (each of these was a *correction* the first pass
made away from the reference, so don't reintroduce them):

| | first pass | reference, now |
|---|---|---|
| skull | uniform egg | big domed cranium (half-width 0.325 of head height at 34% down) over a distinctly narrow lower face |
| ears | small subtle bumps | protruding pads, 0.09 × 0.22 of head height, clearing the skull edge |
| eyewear | one solid slab overhanging the temples | thin swept brow bar + a **sliver** bridge, with two large rounded dark lenses hung off it |
| lenses | lit, accent-coloured | **dark**, with one diagonal sheen streak on the wearer's right lens |
| beard | thin moustache + thin chin strip | circle beard in three dark shapes — moustache arc, solid goatee mass, thin side straps — and **no drawn mouth** |
| shading | strong airbrushed 3D gradient | near-flat vector fill (`vert` 0.07, `spec` 0.07) plus a soft outer glow, and a `DARK_RIM = 5` dilation of the dark layer so the icon separates from the lattice |

Two new helpers do most of the work: `fill(pts, grow)` dilates a polygon by a
disc (a round-jointed closed stroke over the fill) — that is where every rounded
corner comes from, so **author polygons inset by `grow`** — and `stamp(path, r0,
r1)` brushes a tapered round-capped stroke for the moustache, brow and
chin-straps.

**Verified:** regenerates clean; builds clean under mcs; `monodis --manifest`
still lists `dj_face_lit.png` / `dj_face_dark.png`. Deployed md5 for this pass
was `1d07a87c64a8c6fdfdf33f1529c0c238` — **superseded, see below.**

**Still NOT verified in game** — same list as above; nothing has launched. The
preview `face_preview_new.png` (scratchpad, from `preview_face.py`) now puts the
**reference crop beside the render with the two head boxes aligned 1:1**, plus
the 120 px / 80 px / mid-fade badges and a native-size reference thumbnail, which
is the comparison to redo after any further shape change.

*Judgment calls, not measured:* the sheen is a single soft streak because the
reference's fine parallel hatching does not survive 80 px; the chin-straps are
kept even though they half-dissolve at 80 px, because they carry a lot of the
character at 120 px; the jaw taper below crop y 87 was narrowed past the raw
measurement, since the beard is dark and the cyan segmentation under-read the
face edge there; the goatee ring was narrowed to `x 45.5..64.5` to stay inside
that narrower chin.

#### Same day, third pass — the two shapes that still read wrong

Structure was right after the trace; two areas still read as clipart at badge
size, and both are now fixed in `make_dj_face.py` (no C# change).

**The mouth was drawing a grin.** The goatee was a dark RING with a lit opening
and a dark bar inside it — three concentric bands, which at 80px collapse into
gritted teeth. The reference does not draw the mouth at all. `mouth_mask` and
`lips_mask` are **deleted**; the beard is now exactly three dark shapes —
a moustache arc with thinned downturned ends, one solid goatee mass, and a thin
strap down each side closing the ring — and the lips are just the skin gap
between the moustache and the goatee. Do not add a mouth back.

Two shape-construction lessons paid for on the way, both visible only at 512:

- **The goatee is a union of round brush stamps** (`stamp`), not a polygon. A
  two-box version left a step in the silhouette and a trapezoid left a flat
  shelf where it met the moustache; a brush union has no corners to step.
- **Its taper deliberately overshoots the chin** (to crop y 118, past the crop
  y 122 chin only after dilation). `beard_mask` is multiplied by `head`, so the
  overshoot clips to the chin outline. Stop it short and a lit crescent survives
  underneath that reads as a drip hanging off the beard.
- **Strap control nets must be monotone in both axes.** The first pair swung
  outward before coming back in, which hooked the curve over itself into a
  visible hangnail.

**The lenses were rectangles with a nose plug.** They are now large rounded
shapes (`fill` with `r = 5.5` crop px, so the outer corners are all but pill
ends), swept — taller and lower at the outer end — and the gap between them is a
sliver the bridge stub closes. The brow bar was thinned to `CW(2.1)`. The lens
outer end now runs down to crop y 80.5, which is what removed the **cheek
wedges**: those lit triangles were simply the skin left between a lens that
stopped too high and the widest part of the jaw, and they read as cartoon
cheeks. Widening the bridge stub brings the nose plug straight back.

**Verified:** regenerates clean; builds clean under mcs; `monodis --manifest`
lists both PNGs; deployed md5 `cfd5bda62ff48e62a75fad339df624e5` matches the
build output byte for byte. Checked in the preview at 512px, 120px, 80px and
mid-fade — the straps do survive 80px, so they were kept.

**Still NOT verified in game.** Nothing has launched; the Unity-side path is
unchanged from the first pass and still unexercised.

- Post-playtest (2026-08-22): clicking confirmed working. Face shrunk (head 0.50 of the
  texture, was 0.58) and the glow widened (blur 22 px, 0.42) in `make_dj_face.py`. The
  "everything went blurry" report is attributed to `_pill.localScale = 1.4` — uGUI/TMP
  rasterise against the *canvas* scale factor, so a transform scale stretches — and fixed by
  removing it and dividing the CanvasScaler reference resolution by `PillScale` instead
  (same on-screen size). Cause is reasoned, not measured; confirm on next run.
  Deployed md5 `d49818e0bc35f9f37f136f63c882db95`.
