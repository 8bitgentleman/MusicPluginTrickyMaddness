# Handoff: the badge glyph builds a correct mesh every frame and draws nothing

## Goal

The Radio Big "now playing" pill has a circular badge at its lower-left. Inside that
badge a custom `Graphic` (`PulseFieldGlyph`) is supposed to draw an animated cyan
waveform lattice. **It draws nothing.** The badge is a flat dark circle.

Everything else in the same widget renders correctly, so this is not "the HUD is
broken" — it is one `Graphic` subclass, in a canvas whose other five `Graphic`
subclasses all work.

Find out why, and fix it. That is the whole task.

## Where

- Repo: `/Users/mtvogel/Downloads/claude_scratch/MusicPluginTrickyMaddness`
  (**not** `tricky_mods`, which is likely your shell's cwd)
- Branch: `feat/radio-big-external-player`
- Plugin source: `radio/RadioBigPlugin/` — `RadioBig.cs`, `RadioHud.cs`,
  `RadioHudGraphics.cs`, `RadioStatus.cs`, `build.sh`
- Build: `cd radio/RadioBigPlugin && ./build.sh` (plain `mcs`, no Unity Editor project)
- Deploy: copy `RadioBigTM.dll` to
  `~/Library/Application Support/Steam/steamapps/common/Tricky Madness/BepInEx/plugins/`
- Logs: `BepInEx/LogOutput.log` **and**
  `~/Library/Logs/NathanDearth/Tricky Madness/Player.log` — exceptions out of Unity
  `Start`/`Update` land only in the second one.
- Prior narrative: `radio/RADIO_PILL_HANDOFF.md` (sessions 1-6). This doc supersedes
  its glyph section.

Game is Unity 2022.3.62, BepInEx 5.4.23.2. There is **no Unity Editor project** for
this mod — every shape is procedural `OnPopulateMesh` geometry. Nothing Unity-side can
be unit-tested locally; verification is a game run or static IL inspection.

## The setup, in one paragraph

`RadioHud.cs:337` makes a `Canvas` (`ScreenSpaceOverlay`, `sortingOrder = 5000`) with a
`CanvasScaler` (ScaleWithScreenSize, 1920x1080 ref). `BuildBanner()` runs **before**
`BuildGlyph()` deliberately, so the badge is the later sibling and draws on top.
`BuildGlyph()` (`RadioHud.cs:427`) creates `RBGlyph` (56x56, anchored bottom-left of the
pill) with a `ChamferedPanel{IsCircle=true}` — **this is the dark circle you can see** —
then creates `RBPulseField` as its child (stretch anchors, 5 px inset -> 46x46) with the
`PulseFieldGlyph` component on it. Parent draws before child in uGUI, and nothing is
built after the badge, so the field is the last thing drawn in the entire canvas.

## What works (so the failure is narrow)

Confirmed on screen in the user's screenshots:

- `ChamferedPanel` — the badge circle **and** the expanded banner. Renders.
- `TransportIcon` — prev / pause / next glyphs. Render.
- `TextMeshProUGUI` — the "SXOT" source tag, the "Big Lost" title, "0:03". Render.
- The progress bar. Renders.
- The pill expands and collapses, driven by real playback state from the Python player.

`ChamferedPanel` is the direct comparison: same base class, same canvas, same
`vh.AddVert`/`AddTriangle` idiom, same `Vector2.zero` UVs, and it is the **parent** of
the broken one. It works.

## What is ruled out, and how

Do not re-tread these. Each was closed with evidence, not reasoning.

1. **"The component is frozen / not rebuilding."** It was, once — `Graphic.CacheCanvas()`
   only caches an *active and enabled* Canvas, and the HUD hides itself by disabling that
   Canvas, so a `canvas != null` guard in `Update()` returned early forever. Fixed with an
   explicit `Animate` flag set in lockstep with `_canvas.enabled`. **Log-confirmed fixed**:
   mesh rebuilds now run continuously and the rect breathes 46.00 -> 63.84 -> 46.00 as the
   badge scales.

2. **Every CanvasRenderer-level suspect.** The diagnostic inside `OnPopulateMesh` prints,
   every 600 rebuilds, right up to #10200:

   ```
   glyph mesh #10200: rect=(x:0.00, y:0.00, width:46.00, height:46.00) verts=1616 lw=1.40
     active=True canvas=RadioBigCanvas enabled=True scale=1.46 order=5000
     lossyScale=(1.46, 1.46, 1.46) crAlpha=1.00 crInherited=1.00 cull=False mats=1
     col=RGBA(255, 255, 255, 255)
   ```

   Active, canvas resolved and enabled, full alpha, full inherited alpha, not culled, one
   material, 1616 vertices submitted. There is no unhealthy field left to find here.

3. **"It's drawing, but too dim or too thin to see."** Dead. `scratchpad/glyph_sim.py`
   re-implements `PulseFieldGlyph.OnPopulateMesh` (Project / Pt / Grid / Trace / Wave /
   TaperAt / Shade / StrokePoly / AddQuad) 1:1 in Python+numpy+PIL, with the same
   source-over alpha blend over the badge's actual fill colour `GlyphFillDark
   (10,18,32)`, at true device resolution (46 x 1.46 = 67 px), 6x supersampled, y-flipped
   for uGUI's y-up. Output:

   ```
   quads=384  device px=67
   max channel delta from fill: 188.0   mean: 21.05   px changed >2: 1278/4489
   ```

   The rendered PNG is an unmistakable bright cyan lattice filling the badge. **28% of the
   badge's pixels would visibly move off the fill colour, peak channel delta 188.** A
   correctly-composited mesh would be impossible to miss. The geometry, colours and alphas
   are correct.

4. **Sibling / draw order.** `BuildBanner()` before `BuildGlyph()` is deliberate and
   verified by `ReportLayout()`; the field is the last-drawn object in the canvas.

5. **The banner's `RectMask2D`.** The badge is a sibling of the banner, not a descendant.
   `MaskUtilities.GetRectMaskForClippable` walks *up* (glyph -> pill -> canvas) and never
   reaches it. There is no `Mask` (stencil) anywhere, only that one `RectMask2D`.

6. **The rect / pivot.** `CreateRect` uses pivot `(0,0)`, so `GetPixelAdjustedRect()`
   returns `(x:0, y:0, w:46, h:46)` and `r.center` is `(23,23)` — the true centre. Matches
   the log exactly.

7. **Shader state that would need a material asset.** `UI/Default` is `Cull Off`, so
   winding is irrelevant (the sim rendered both windings anyway); `ZTest` is Always for
   ScreenSpaceOverlay; nothing sets `ColorMask`.

8. **An EventSystem regression** (separate bug, mentioned only so you don't reintroduce
   it). A previous pass added an `EventSystem` + `StandaloneInputModule`; the game's own
   EventSystem lives in `Menu.unity`, which is additive and never unloaded, so during a
   race it is *disabled*, not destroyed. Ours then permanently held `m_EventSystems[0]`
   and killed controller navigation on pause/results screens. **All of it is gone** — the
   HUD now hit-tests the mouse directly with
   `RectTransformUtility.RectangleContainsScreenPoint`, and there is no `GraphicRaycaster`
   on the canvas at all. Verified: zero metadata references to `EventSystem`,
   `StandaloneInputModule`, `GraphicRaycaster` in the built DLL. **Do not add one back.**

## The contradiction, stated plainly

The mesh is built correctly (3). It is submitted every frame to a CanvasRenderer that is
active, uncalled, full-alpha and has a material (2). It is the last object drawn in the
canvas (4), unmasked (5), correctly positioned (6). Its siblings and its own parent, same
base class, render fine.

And the badge is empty.

One of those statements is false, and I could not find which by reading code.

## The probe currently deployed

The DLL in `BepInEx/plugins/` right now (md5 `35713cdb7321edcc3923047e7f359548`) has a
**temporary diagnostic** in `PulseFieldGlyph.OnPopulateMesh`: `public static bool
ProbeFill = true` makes it draw **one opaque magenta quad over the whole rect and return**,
skipping the lattice entirely. It also now logs the bound material and texture
(`mat=` / `tex=`).

- **Magenta square visible** => the Graphic renders, and the fault is specific to the
  lattice quads (per-vertex alpha, the ~400-quad submission, `StrokePoly`'s vertex
  indexing at `RadioHudGraphics.cs:459`).
- **Badge still empty** => this Graphic never reaches the screen at all, whatever the
  CanvasRenderer reports, and the fault is at the object/compositing level.

**This run had not happened when the handoff was written.** Ask the user for it, or read
`LogOutput.log` for `[Radio] PROBE:` and the `mat=`/`tex=` values. Either way, delete the
probe (`ProbeFill`, the block at the top of `OnPopulateMesh`, and the marked comment
banner) once it has answered.

Also still temporary and due for removal once the glyph is fixed: `RadioBigHud.ReportLayout()`
and the `_rebuilds` mesh log.

## About the Multicam comparison

The user noted that MulticamMod is a similar mod and its UI works. **It is not the same
mechanism** — `tricky_mods/MulticamMod-src/MulticamMod.cs:101` and `:903` draw with
`OnGUI` (IMGUI), bypassing the uGUI Canvas system entirely. So it is not evidence about
`Graphic`/`OnPopulateMesh` at all.

It is, however, proof that **IMGUI renders reliably in this game from a BepInEx plugin**.
If the root cause turns out to be a uGUI limitation that cannot be worked around, drawing
just the glyph via `OnGUI`/`GL` is a live fallback — but it is a fallback, not the first
answer. The rest of the pill is uGUI and should stay uGUI.

## Constraints

- **Do not commit anything.** All of this feature is uncommitted working-tree changes and
  the user has said repeatedly not to commit without being asked. Do not discard the
  working tree. Do not force-push. There are unpushed local commits on this branch — leave
  them alone.
- **Do not touch**: `.gitignore`'s existing modification, untracked `radio/make_banner.py`,
  or the repo-root `Plugin.cs` / `PluginInfo.cs` / `MusicConfig.cs` /
  `MusicPluginTrickyMaddness.csproj` / `build.sh` — that is a *different, unrelated mod*
  sharing the repo. The Radio Big plugin is only ever `radio/RadioBigPlugin/`.
- Transport scope is settled: **skip + play/pause only**. Real media-key support was
  explicitly scrapped by the user. Don't re-propose it.
- `build.sh` needs `-r:UnityEngine.InputLegacyModule.dll` (already added) — `UnityEngine.dll`
  only *forwards* `Input`, which produces a confusing `CS1070` rather than a missing type.

## Known-stale docs (not your task, just don't trust them)

`RADIO_BIG.md` and `radio/RadioBigPlugin/build.sh`'s header still describe the transport
as a TCP socket. It is file-based: `radio.cmd` (C#->Python, append-only) and
`radio.status.json` (Python->C#, atomic temp+rename, ~220 ms, 3 s staleness -> idle).
