using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

namespace RadioBigTM
{
    // The "now playing" HUD pill: an idle circular badge, bottom-left, that
    // expands rightward into a wider glass panel. Built entirely in code from
    // the user-approved prototype -- the visual spec is transcribed in
    // radio/RADIO_PILL_HANDOFF.md (the original HTML lived in a session
    // scratchpad and is gone).
    //
    // Deliberate simplifications vs. the prototype (there is no Unity Editor
    // project for this plugin -- it's built by plain mcs against the game's own
    // DLLs -- so anything needing a shader/asset/scene pipeline had to be
    // re-approximated in plain uGUI):
    //   - No backdrop-filter blur. The glass panel is a vertex-coloured
    //     gradient fill instead, which gets the steel-glass falloff for free
    //     without a render-texture blur pass.
    //   - The badge art (PulseFieldGlyph) is a direct port of the prototype's
    //     canvas class, as real uGUI geometry. What could not come across is
    //     the additive compositing and the blurred-buffer bloom, which are
    //     faked with a wide dim pass under a narrow hot pass; see the class.
    //   - Play/pause and next are live (2026-08-20): they append a verb to the
    //     same radio.cmd the Harmony patches use, and the player answers by
    //     changing radio.status.json, which this already reads. Prev stays
    //     inert -- see AddTransportButton for why that one is different.
    internal class RadioBigHud : MonoBehaviour
    {
        // Judgment call (2026-08-22): 1.4x read as "small" at 56 px on a
        // 1080p-reference canvas; not measured against anything. Applied by
        // shrinking the CanvasScaler reference resolution, NOT by scaling the
        // pill's RectTransform: uGUI/TMP rasterise against the canvas scale
        // factor, so a localScale on the pill stretched text and edges and
        // the whole HUD went soft (playtest 2026-08-22).
        private const float PillScale = 1.4f;
        private const float IdleSize = 56f;
        private const float OpenSize = 84f;
        private const float BannerHeight = 84f;
        private const float BannerOpenWidth = 340f;
        private const float BannerGap = -14f;         // badge overlaps the banner's left edge
        private const float ContentLeft = 24f;        // clear of the badge at OpenSize (badge
                                                       // right edge lands at banner-local 14)
        private const float ContentRight = 14f;
        private const float AutoCollapseSeconds = 6f;
        private const float EaseRate = 9f;

        // Colours from the prototype.
        private static readonly Color32 GlyphFillDark = new Color32(10, 18, 32, 240);
        private static readonly Color32 PanelLight    = new Color32(240, 247, 251, 235); // upper-left
        private static readonly Color32 PanelSteel    = new Color32(176, 205, 224, 232); // lower-right
        private static readonly Color32 FrostChip     = new Color32(0x8F, 0xAD, 0xC2, 0xFF);
        private static readonly Color32 MagentaChip   = new Color32(0xFF, 0x3F, 0xB4, 0xFF);
        private static readonly Color32 NightText     = new Color32(0x0A, 0x12, 0x20, 0xFF);
        private static readonly Color32 InkDark       = new Color32(0x0A, 0x1A, 0x24, 0xFF);
        private static readonly Color32 InkMuted      = new Color32(0x33, 0x50, 0x5F, 0xFF);
        private static readonly Color32 CyanAccent    = new Color32(0x34, 0xE7, 0xFF, 0xFF);
        private static readonly Color32 CyanBright    = new Color32(0x7F, 0xF2, 0xFF, 0xFF);
        private static readonly Color32 AmberAccent   = new Color32(0xFF, 0xB9, 0x32, 0xFF);
        private static readonly Color32 ProgressTrack = new Color32(10, 26, 40, 46);

        private Canvas _canvas;
        private RectTransform _pill, _glyph, _banner, _tagBg, _titleRt, _progressFillRt;
        private ChamferedPanel _glyphPanel, _bannerPanel, _tagBgPanel;
        private Image _progressBg, _progressFill;
        private TextMeshProUGUI _tagText, _titleText, _timeText;
        private PulseFieldGlyph _glyphField;
        private CornerBrackets _brackets;
        private DashedChamferTrace _led;

        private bool _open;
        private bool _pointerInside;
        private float _hoverTimer;
        private float _glyphSizeCurrent = IdleSize;
        private float _bannerWidthCurrent;
        private string _lastDiag = "";
        private TransportIcon _playIcon;
        private string _lastTitle = "";
        private bool _lastVisible;

        private void Awake()
        {
            BuildUi();
            SetOpen(false, instant: true);
        }

        private void Update()
        {
            // ---- visibility: racing only ----------------------------------
            // Plugin.IsRacing is set first-hand by the Harmony patches on
            // LevelManager.Start / LevelManager.Finish / the menu music post,
            // so it does not depend on the status file round-tripping a state
            // string. The status file is a display feed, not a state source.
            bool visible = Plugin.IsRacing;
            if (visible != _lastVisible)
            {
                _lastVisible = visible;
                if (_canvas != null) _canvas.enabled = visible;
                // These two animate themselves from Update, and Update keeps
                // running while the Canvas is off. Gate them here rather than
                // letting them ask the Canvas: a Graphic can't see a disabled
                // Canvas at all, so asking gets a null it may never recover
                // from. Same line, same truth, no drift.
                if (_glyphField != null) _glyphField.Animate = visible;
                if (_led != null) _led.Animate = visible;
                // Drop the cursor claim WITHOUT hiding the pointer. Leaving a
                // race with the banner open lands you in a menu, and the menu
                // wants a cursor -- racing the game to set it back would be a
                // coin flip we'd sometimes lose, leaving the results screen
                // unclickable. Inside a race, SetOpen(false) still hides it.
                if (!visible) _cursorForced = false;
                Plugin.Log.LogInfo("[Radio] HUD " + (visible ? "shown (racing)" : "hidden (not racing)"));
                if (!visible)
                {
                    // Reset so the next race doesn't inherit the last one's
                    // open banner or stale title.
                    SetOpen(false, instant: true);
                    _lastTitle = "";
                }
            }
            if (!visible) return;

            PollPointer();

            var snap = RadioStatusReader.Latest;
            bool hasTrack = snap.Fresh && snap.Track != null
                            && !string.IsNullOrEmpty(snap.Track.title);

            // On-change only, and at Info: if the banner never opens, this is
            // the line that says which of the three conditions failed. A silent
            // HUD with VerboseLogging off is exactly what made the last
            // playtest undiagnosable.
            string diag = snap.Fresh + "/" + (snap.Track != null) + "/" + hasTrack;
            if (diag != _lastDiag)
            {
                _lastDiag = diag;
                Plugin.Log.LogInfo("[Radio] HUD status: fresh=" + snap.Fresh
                    + " trackObj=" + (snap.Track != null)
                    + " hasTitle=" + hasTrack
                    + " state=" + (snap.State ?? "<null>")
                    + " file=" + Plugin.StatusFile);
            }

            // ---- auto-expand on track change ------------------------------
            // The pill has to be able to show itself without a click. The
            // cursor is not locked during a race (MenuManager only ever calls
            // Cursor.set_visible -- Assembly-CSharp never touches
            // CursorLockMode, IL-verified), so a click WOULD still register --
            // but the cursor is invisible from the moment a level loads, so
            // aiming at a corner widget is blind guesswork. A new track pops
            // the banner open on its own, then it collapses.
            string title = hasTrack ? (snap.Track.title ?? "") : "";
            if (title != _lastTitle)
            {
                _lastTitle = title;
                if (hasTrack)
                {
                    SetOpen(true);
                    Plugin.Log.LogInfo("[Radio] HUD auto-expand for track: " + title);
                }
            }

            if (!hasTrack && _open) SetOpen(false);
            else if (_open && !_pointerInside)
            {
                _hoverTimer += Time.unscaledDeltaTime;
                if (_hoverTimer >= AutoCollapseSeconds) SetOpen(false);
            }

            AnimateSizes();
            Render(snap, hasTrack);
        }

        // ---- pointer, driven by PollPointer above ----
        // Clicking is a bonus, not the primary path: auto-expand is what
        // actually drives the widget during a race.
        public void OnPillClicked()
        {
            Plugin.Verbose("[Radio] HUD pill clicked (open=" + _open + ")");
            if (!_open) SetOpen(true);
            else _hoverTimer = 0f;
        }

        // The game hides the cursor the moment a level loads (MenuManager only
        // ever calls Cursor.set_visible; it never touches CursorLockMode, so
        // the pointer still MOVES and still raycasts -- you just can't see where
        // it is). That was survivable while the transport keys were inert. Now
        // that they send real commands, aiming at a 24px key blind is not a
        // control scheme, so show the pointer for exactly as long as the banner
        // is open and put it back the moment it closes.
        private bool _cursorForced;
        // While the pill is closed the pointer is invisible, so clicking the
        // badge to open it was blind. Moving the mouse reveals the pointer for
        // a few seconds, media-player style, then it hides again.
        private const float CursorRevealSeconds = 2.5f;
        private float _cursorRevealUntil = -1f;
        private Vector2 _lastMouse;

        private void SetCursorVisible(bool want)
        {
            if (want == _cursorForced) return;
            _cursorForced = want;
            Cursor.visible = want;
        }

        private void UpdateCursor()
        {
            SetCursorVisible(_open || Time.unscaledTime < _cursorRevealUntil);
        }

        private void SetOpen(bool open, bool instant = false)
        {
            _open = open;
            // Only while the hud is actually up: Awake calls SetOpen(false)
            // before anything is visible, and that must not hide the menu's
            // cursor on the way past.
            if (_lastVisible) UpdateCursor();
            _hoverTimer = 0f;
            if (instant)
            {
                _glyphSizeCurrent = open ? OpenSize : IdleSize;
                _bannerWidthCurrent = open ? BannerOpenWidth : 0f;
            }
        }

        private void AnimateSizes()
        {
            float targetGlyph = _open ? OpenSize : IdleSize;
            float targetBanner = _open ? BannerOpenWidth : 0f;
            float t = 1f - Mathf.Exp(-EaseRate * Time.unscaledDeltaTime);
            _glyphSizeCurrent = Mathf.Lerp(_glyphSizeCurrent, targetGlyph, t);
            _bannerWidthCurrent = Mathf.Lerp(_bannerWidthCurrent, targetBanner, t);
            if (Mathf.Abs(_glyphSizeCurrent - targetGlyph) < 0.05f) _glyphSizeCurrent = targetGlyph;
            if (Mathf.Abs(_bannerWidthCurrent - targetBanner) < 0.05f) _bannerWidthCurrent = targetBanner;

            // Badge stays vertically centred on the banner and grows about its
            // own centre instead of climbing out of a bottom-left pivot.
            _glyph.sizeDelta = new Vector2(_glyphSizeCurrent, _glyphSizeCurrent);
            _glyph.anchoredPosition = new Vector2(0f, (BannerHeight - _glyphSizeCurrent) * 0.5f);

            _banner.sizeDelta = new Vector2(_bannerWidthCurrent, BannerHeight);
            _banner.anchoredPosition = new Vector2(_glyphSizeCurrent + BannerGap, 0f);
        }

        private void Render(RadioStatusSnapshot snap, bool hasTrack)
        {
            // NOT gated on hasTrack: dj_brain only sets `track` after the song
            // starts (so elapsed/duration line up), and the race intro is
            // spoken BEFORE that -- gating here left the badge blue through
            // the whole intro, which is exactly the moment it should be amber.
            bool dj = snap.Fresh && snap.DjTalking;

            // The glyph runs its own clock and rebuilds itself; all it needs
            // from here is which state to lerp toward.
            bool paused = hasTrack && snap.Paused;
            _glyphField.State = paused ? PulseFieldGlyph.Mode.Paused
                                       : dj ? PulseFieldGlyph.Mode.DjTalking
                                       : hasTrack ? PulseFieldGlyph.Mode.Playing
                                                  : PulseFieldGlyph.Mode.Idle;
            // The key shows the action it performs, so it reads Play while
            // paused -- the same way every transport control does.
            if (_playIcon != null)
                _playIcon.IconKind = paused ? TransportIcon.Kind.Play : TransportIcon.Kind.Pause;

            if (!hasTrack)
            {
                _tagText.text = "";
                _titleText.text = "";
                _timeText.text = "";
                _tagBg.sizeDelta = new Vector2(46f, 16f);
                _tagBgPanel.color = FrostChip;
                _progressFillRt.sizeDelta = new Vector2(0f, 4f);
                return;
            }

            var track = snap.Track;
            string sourceUpper = string.IsNullOrEmpty(track.source) ? "" : track.source.ToUpperInvariant();
            _tagText.text = dj ? "DJ" : sourceUpper;
            bool custom = !dj && string.Equals(track.source, "custom", StringComparison.OrdinalIgnoreCase);
            _tagBgPanel.color = custom ? MagentaChip : FrostChip;

            float tagW = Mathf.Clamp(20f + _tagText.text.Length * 7f, 34f, 96f);
            _tagBg.sizeDelta = new Vector2(tagW, 16f);
            float titleX = ContentLeft + tagW + 8f;
            _titleRt.anchoredPosition = new Vector2(titleX, 42f);
            _titleRt.sizeDelta = new Vector2(
                Mathf.Max(40f, BannerOpenWidth - titleX - ContentRight), 28f);
            _titleText.text = track.title ?? "";

            // Progress. NOTE: Image.Type.Filled is useless here -- Image's
            // OnPopulateMesh null-checks activeSprite and falls back to a plain
            // full quad BEFORE it ever reads fillAmount, and these Images have
            // no sprite. So the fill is done by resizing the rect instead.
            float trackW = ProgressWidth();
            Color32 accent = dj ? AmberAccent : CyanAccent;
            bool durationKnown = track.duration > 0f;
            float elapsed = Mathf.Max(0f, track.elapsed);
            if (durationKnown)
            {
                float frac = Mathf.Clamp01(elapsed / track.duration);
                _progressFillRt.sizeDelta = new Vector2(trackW * frac, 4f);
                _progressFill.color = accent;
                _timeText.text = FormatTime(elapsed);
            }
            else
            {
                // Indeterminate: full-width bar breathing in alpha, since
                // there's nothing to divide by.
                float pulse = 0.35f + 0.25f * Mathf.Sin(Time.unscaledTime * 2f);
                _progressFillRt.sizeDelta = new Vector2(trackW, 4f);
                _progressFill.color = new Color32(accent.r, accent.g, accent.b, (byte)(pulse * 255f));
                _timeText.text = FormatTime(elapsed);
            }
        }

        private static float ProgressWidth()
        {
            // transport row ends at ContentLeft + 96; time label reserves 46 on
            // the right.
            return BannerOpenWidth - (ContentLeft + 96f) - 46f - ContentRight;
        }

        private static string FormatTime(float seconds)
        {
            int s = Mathf.Max(0, Mathf.RoundToInt(seconds));
            int m = s / 60, sec = s % 60;
            return m + ":" + sec.ToString("00");
        }

        // ------------------------------------------------------------------
        // UI construction. No scene/prefab pipeline, so the whole tree is built
        // by hand. The banner clips its contents with RectMask2D as it grows --
        // which only works because every child is a MaskableGraphic (see the
        // header comment in RadioHudGraphics.cs; a bare Graphic is invisible to
        // RectMask2D and leaks outside the collapsed banner).
        // ------------------------------------------------------------------
        private void BuildUi()
        {
            var canvasGo = new GameObject("RadioBigCanvas", typeof(RectTransform));
            canvasGo.transform.SetParent(transform, false);
            _canvas = canvasGo.AddComponent<Canvas>();
            _canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            _canvas.sortingOrder = 5000;
            _canvas.enabled = false;          // racing-only; Update turns it on
            var scaler = canvasGo.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f / PillScale, 1080f / PillScale);
            scaler.matchWidthOrHeight = 0.5f;
            _pill = CreateRect("RBPill", canvasGo.transform, Vector2.zero, Vector2.zero, Vector2.zero);
            _pill.anchoredPosition = new Vector2(18f, 18f);
            _pill.sizeDelta = new Vector2(BannerOpenWidth + OpenSize, BannerHeight);

            // Banner FIRST so the badge is the later sibling and draws on top --
            // the two deliberately overlap by BannerGap, and the prototype has
            // the badge over the panel, not under it.
            BuildBanner();
            BuildGlyph();
        }

        // ---- pointer input, deliberately WITHOUT an EventSystem ----------
        //
        // The pill hit-tests the mouse itself rather than going through uGUI's
        // EventSystem + GraphicRaycaster. That is not a style preference; a
        // second EventSystem is a game-wide input bug, IL-verified in an
        // earlier pass and then re-introduced and re-observed on 2026-08-20:
        //
        //   - EventSystem.get_current is m_EventSystems[0] and OnEnable
        //     appends, so whichever registers first wins PERMANENTLY.
        //   - EventSystem.Update opens with `if (current != this) return;`, so
        //     the loser never processes anything again.
        //   - The game's own EventSystem (Menu.unity, stock EventSystem +
        //     InputSystemUIInputModule) is disabled during a race, so a guard
        //     that only checks "is one active right now" always concludes it
        //     should create one -- and then OUR StandaloneInputModule is
        //     m_EventSystems[0] for the rest of the process. When the game
        //     re-enables its own for a pause or results screen, that one is
        //     now the loser and its controller navigation is dead.
        //
        // Menu.unity is loaded ADDITIVELY and never unloaded (only the level
        // scene is, via UnloadSceneAsync), so the game's EventSystem is not
        // gone during a race, just switched off -- which is precisely the
        // state that fools an is-it-active check.
        //
        // Hit-testing here costs one matrix inverse per rect per frame across
        // ~5 rects, only while the hud is on screen, and touches no global
        // state whatsoever. Note the hit area is the RectTransform's rect, not
        // the drawn triangles -- which is what we want for a 24px key.
        private readonly List<RectTransform> _pillRects = new List<RectTransform>();
        private readonly List<RectTransform> _keyRects = new List<RectTransform>();
        private readonly List<string> _keyCommands = new List<string>();

        private static bool Over(RectTransform rt, Vector2 screen)
        {
            // null camera: ScreenSpaceOverlay, where screen space and canvas
            // space are the same thing.
            return rt != null && rt.gameObject.activeInHierarchy
                && RectTransformUtility.RectangleContainsScreenPoint(rt, screen, null);
        }

        private void PollPointer()
        {
            Vector2 p = Input.mousePosition;
            // Sloppy mouse bumps don't count; deliberate movement does.
            if ((p - _lastMouse).sqrMagnitude > 9f)
            {
                _lastMouse = p;
                _cursorRevealUntil = Time.unscaledTime + CursorRevealSeconds;
            }
            UpdateCursor();

            bool inside = false;
            for (int i = 0; i < _pillRects.Count && !inside; i++) inside = Over(_pillRects[i], p);
            if (inside && !_pointerInside) _hoverTimer = 0f;
            _pointerInside = inside;

            if (!Input.GetMouseButtonDown(0)) return;

            // Keys before the pill: they sit ON the banner, so the banner would
            // otherwise swallow every one of them. Only while open, because a
            // rect still contains a point when the RectMask2D has clipped away
            // everything that was drawn in it.
            if (_open)
            {
                for (int i = 0; i < _keyRects.Count; i++)
                {
                    if (!Over(_keyRects[i], p)) continue;
                    var c = Plugin.Client;
                    if (c != null) c.Send(_keyCommands[i]);
                    Plugin.Log.LogInfo("[Radio] transport -> " + _keyCommands[i]
                        + (c == null ? " (DROPPED: no client)" : ""));
                    _hoverTimer = 0f;
                    return;
                }
            }
            if (inside) OnPillClicked();
        }

        private void BuildGlyph()
        {
            var glyphRt = CreateRect("RBGlyph", _pill, Vector2.zero, Vector2.zero, Vector2.zero);
            _glyph = glyphRt;
            _glyph.sizeDelta = new Vector2(IdleSize, IdleSize);
            _glyphPanel = glyphRt.gameObject.AddComponent<ChamferedPanel>();
            _glyphPanel.IsCircle = true;
            _glyphPanel.color = GlyphFillDark;
            _pillRects.Add(glyphRt);

            // The badge's signature lattice. Inset only slightly: the sheet
            // wants the circle's full width, and squashes itself vertically.
            var waveRt = CreateRect("RBPulseField", glyphRt, Vector2.zero, Vector2.one, Vector2.zero);
            waveRt.offsetMin = new Vector2(5f, 5f);
            waveRt.offsetMax = new Vector2(-5f, -5f);
            _glyphField = waveRt.gameObject.AddComponent<PulseFieldGlyph>();
            _glyphField.KnockoutColor = GlyphFillDark;
            _glyphField.raycastTarget = false;
        }

        private void BuildBanner()
        {
            var bannerRt = CreateRect("RBBanner", _pill, Vector2.zero, Vector2.zero, Vector2.zero);
            _banner = bannerRt;
            _banner.sizeDelta = new Vector2(0f, BannerHeight);
            _bannerPanel = bannerRt.gameObject.AddComponent<ChamferedPanel>();
            _bannerPanel.ChamferSize = 20f;
            _bannerPanel.color = PanelLight;
            _bannerPanel.UseGradient = true;
            _bannerPanel.GradientTo = PanelSteel;
            bannerRt.gameObject.AddComponent<RectMask2D>();
            _pillRects.Add(bannerRt);

            // Rim details. Both are children of the banner, so the RectMask2D
            // above clips them away for free while it's collapsed.
            var ledRt = CreateRect("RBLed", bannerRt, Vector2.zero, Vector2.one, Vector2.zero);
            ledRt.offsetMin = Vector2.zero;
            ledRt.offsetMax = Vector2.zero;
            _led = ledRt.gameObject.AddComponent<DashedChamferTrace>();
            _led.ChamferSize = 20f;
            _led.color = new Color(CyanBright.r, CyanBright.g, CyanBright.b, 0.55f);
            _led.raycastTarget = false;

            var brRt = CreateRect("RBBrackets", bannerRt, Vector2.zero, Vector2.one, Vector2.zero);
            brRt.offsetMin = Vector2.zero;
            brRt.offsetMax = Vector2.zero;
            _brackets = brRt.gameObject.AddComponent<CornerBrackets>();
            _brackets.Inset = 20f;      // must track _bannerPanel.ChamferSize
            _brackets.color = new Color(CyanBright.r, CyanBright.g, CyanBright.b, 0.85f);
            _brackets.raycastTarget = false;

            // Tag chip + text
            _tagBg = CreateRect("RBTag", bannerRt, Vector2.zero, Vector2.zero, Vector2.zero);
            _tagBg.anchoredPosition = new Vector2(ContentLeft, 48f);
            _tagBg.sizeDelta = new Vector2(46f, 16f);
            _tagBgPanel = _tagBg.gameObject.AddComponent<ChamferedPanel>();
            _tagBgPanel.ChamferSize = 4f;
            _tagBgPanel.color = FrostChip;      // set at construction, not only in
                                                 // the has-track branch (the ctor
                                                 // default is opaque white)
            _tagBgPanel.raycastTarget = false;
            _tagText = AddTmp(_tagBg, "", 9f, FontStyles.Bold, TextAlignmentOptions.Center, NightText);
            _tagText.characterSpacing = 6f;

            // Title
            _titleRt = CreateRect("RBTitle", bannerRt, Vector2.zero, Vector2.zero, Vector2.zero);
            _titleRt.anchoredPosition = new Vector2(ContentLeft + 54f, 42f);
            _titleRt.sizeDelta = new Vector2(240f, 28f);
            _titleText = AddTmp(_titleRt, "", 19f, FontStyles.Bold, TextAlignmentOptions.MidlineLeft, InkDark);
            _titleText.enableWordWrapping = false;
            _titleText.overflowMode = TextOverflowModes.Ellipsis;

            // Transport row. Prev is still inert: going BACK means the DJ has to
            // remember what it already played rather than only drawing forward
            // from its shuffle bag, which is a change to the brain's state, not
            // a command -- deliberately out of scope (2026-08-20).
            AddTransportButton(bannerRt, "RBPrev", new Vector2(ContentLeft, 10f), 24f,
                TransportIcon.Kind.Prev, false, null);
            _playIcon = AddTransportButton(bannerRt, "RBPlay", new Vector2(ContentLeft + 30f, 8f),
                28f, TransportIcon.Kind.Pause, true, "TOGGLE");
            AddTransportButton(bannerRt, "RBNext", new Vector2(ContentLeft + 66f, 10f), 24f,
                TransportIcon.Kind.Next, false, "NEXT");

            // Progress bar
            float progX = ContentLeft + 96f;
            float progW = ProgressWidth();
            var progBgRt = CreateRect("RBProgressBg", bannerRt, Vector2.zero, Vector2.zero, Vector2.zero);
            progBgRt.anchoredPosition = new Vector2(progX, 19f);
            progBgRt.sizeDelta = new Vector2(progW, 4f);
            _progressBg = progBgRt.gameObject.AddComponent<Image>();
            _progressBg.color = ProgressTrack;
            _progressBg.raycastTarget = false;

            _progressFillRt = CreateRect("RBProgressFill", bannerRt, Vector2.zero, Vector2.zero, Vector2.zero);
            _progressFillRt.anchoredPosition = new Vector2(progX, 19f);
            _progressFillRt.sizeDelta = new Vector2(0f, 4f);
            _progressFill = _progressFillRt.gameObject.AddComponent<Image>();
            _progressFill.color = CyanAccent;
            _progressFill.raycastTarget = false;

            // Time label
            var timeRt = CreateRect("RBTime", bannerRt, Vector2.zero, Vector2.zero, Vector2.zero);
            timeRt.anchoredPosition = new Vector2(progX + progW + 8f, 8f);
            timeRt.sizeDelta = new Vector2(44f, 22f);
            _timeText = AddTmp(timeRt, "", 11f, FontStyles.Normal, TextAlignmentOptions.MidlineLeft, InkMuted);
        }

        private TransportIcon AddTransportButton(Transform parent, string name, Vector2 pos,
            float size, TransportIcon.Kind kind, bool primary, string command)
        {
            var rt = CreateRect(name, parent, Vector2.zero, Vector2.zero, Vector2.zero);
            rt.anchoredPosition = pos;
            rt.sizeDelta = new Vector2(size, size);

            ChamferedPanel bg = null;
            if (primary)
            {
                // The prototype's play control is a chamfered cyan key in the
                // same corner-cut language as the banner, not a plain square.
                bg = rt.gameObject.AddComponent<ChamferedPanel>();
                bg.ChamferSize = 7f;
                bg.color = CyanAccent;
                bg.raycastTarget = false;
            }

            var iconRt = CreateRect("Icon", rt, Vector2.zero, Vector2.one, Vector2.zero);
            iconRt.offsetMin = Vector2.zero;
            iconRt.offsetMax = Vector2.zero;
            var icon = iconRt.gameObject.AddComponent<TransportIcon>();
            icon.IconKind = kind;
            icon.color = primary ? NightText : InkMuted;
            // Nothing in this hud is a raycast target: there is no
            // GraphicRaycaster on the canvas at all any more (see PollPointer).
            icon.raycastTarget = false;
            if (bg != null) bg.raycastTarget = false;
            // A live key is a rect plus a verb. Dead keys register nothing, so
            // they can't swallow the click that would expand the pill.
            if (!string.IsNullOrEmpty(command))
            {
                _keyRects.Add(rt);
                _keyCommands.Add(command);
            }
            // Still NO UnityEngine.UI.Button: its ColorTint transition drives
            // targetGraphic, which for the play key is the backing panel and
            // for the others is the icon -- the inconsistent "half-disabled"
            // look this used to have. PollPointer is the click, the icon colour
            // is set from status, and nothing tints behind our back.
            return icon;
        }

        private static RectTransform CreateRect(string name, Transform parent, Vector2 anchorMin,
            Vector2 anchorMax, Vector2 pivot)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            var rt = (RectTransform)go.transform;
            rt.anchorMin = anchorMin;
            rt.anchorMax = anchorMax;
            rt.pivot = pivot;
            rt.anchoredPosition = Vector2.zero;
            rt.sizeDelta = Vector2.zero;
            return rt;
        }

        private static TextMeshProUGUI AddTmp(Transform parent, string text, float size, FontStyles style,
            TextAlignmentOptions align, Color32 color)
        {
            var rt = CreateRect("Text", parent, Vector2.zero, Vector2.one, Vector2.zero);
            rt.offsetMin = Vector2.zero;
            rt.offsetMax = Vector2.zero;
            var tmp = rt.gameObject.AddComponent<TextMeshProUGUI>();
            tmp.text = text;
            tmp.fontSize = size;
            tmp.fontStyle = style;
            tmp.alignment = align;
            tmp.color = color;
            tmp.raycastTarget = false;
            return tmp;
        }
    }
}
