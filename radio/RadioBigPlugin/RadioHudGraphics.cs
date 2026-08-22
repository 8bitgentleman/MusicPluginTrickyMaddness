using System;
using System.Reflection;
using UnityEngine;
using UnityEngine.UI;

namespace RadioBigTM
{
    // The DJ ID icon's art, as two 512x512 RGBA PNGs embedded in this assembly
    // by build.sh (mcs -resource:). Authored by radio/RadioBigPlugin/
    // make_dj_face.py -- edit the art THERE and re-run it, the PNGs beside it
    // are generated output.
    //
    // Embedded rather than shipped alongside the DLL because a BepInEx plugin
    // is installed by dropping one file into plugins/; a loose PNG next to it
    // is a second thing to get wrong, and there is no Unity Editor project here
    // to make a real sprite atlas out of.
    //
    // Loaded once, lazily, and cached statically -- the textures outlive the
    // HUD (which is rebuilt on scene changes) and are never unloaded.
    internal static class DjFaceArt
    {
        private static bool _tried;
        private static Texture2D _lit, _dark;

        internal static Texture2D Lit { get { Load(); return _lit; } }
        internal static Texture2D Dark { get { Load(); return _dark; } }

        private static void Load()
        {
            if (_tried) return;
            _tried = true;
            _lit = FromResource("dj_face_lit.png");
            _dark = FromResource("dj_face_dark.png");
        }

        private static Texture2D FromResource(string name)
        {
            try
            {
                Assembly asm = Assembly.GetExecutingAssembly();
                using (var stream = asm.GetManifestResourceStream(name))
                {
                    if (stream == null)
                    {
                        Debug.LogWarning("[RadioBig] DJ face resource missing: " + name);
                        return null;
                    }
                    var bytes = new byte[stream.Length];
                    int off = 0;
                    while (off < bytes.Length)
                    {
                        int n = stream.Read(bytes, off, bytes.Length - off);
                        if (n <= 0) break;
                        off += n;
                    }
                    // mipChain TRUE is load-bearing: the badge draws this 512px
                    // asset at ~80-120px, and unmipped that shimmers as the
                    // badge animates between its idle and open sizes. The art
                    // script writes RGB across the whole canvas (not just
                    // inside the alpha mask) precisely so mip generation has no
                    // transparent-texel colour to bleed into the edges.
                    var t = new Texture2D(4, 4, TextureFormat.RGBA32, true);
                    if (!t.LoadImage(bytes))
                    {
                        Debug.LogWarning("[RadioBig] DJ face decode failed: " + name);
                        UnityEngine.Object.Destroy(t);
                        return null;
                    }
                    t.wrapMode = TextureWrapMode.Clamp;
                    t.filterMode = FilterMode.Trilinear;
                    t.Apply(true, false);       // belt-and-braces mip build
                    return t;
                }
            }
            catch (Exception e)
            {
                // A missing face must not take the HUD down with it.
                Debug.LogWarning("[RadioBig] DJ face load failed (" + name + "): " + e.Message);
                return null;
            }
        }
    }

    // Draws a flat convex polygon filling the RectTransform's rect. Backs both
    // pill shapes from the approved prototype (see RADIO_PILL_HANDOFF.md's
    // transcribed visual spec): the idle circular badge, and the expanded
    // banner's "chamfered hexagon" (a rectangle with the top-right and
    // bottom-left corners cut at 45 degrees). This project builds via plain mcs
    // with no Unity Editor project, so there's no sprite/shader import pipeline
    // to draw an arbitrary polygon any other way -- a custom Graphic overriding
    // OnPopulateMesh is the idiomatic uGUI answer.
    //
    // MUST extend MaskableGraphic, NOT Graphic. RectMask2D only tracks
    // HashSet<IClippable> and HashSet<MaskableGraphic>, and IClippable is
    // implemented by MaskableGraphic -- a bare Graphic is in neither set, so it
    // is never given a clip rect and never culled by ANY mask. That is exactly
    // how the collapsed (zero-width) banner used to leak its chip and transport
    // glyphs onto the screen as free-floating geometry while every Image/TMP
    // child correctly vanished.
    internal class ChamferedPanel : MaskableGraphic
    {
        public float ChamferSize = 0f;
        public bool IsCircle = false;

        // Optional second colour for the prototype's diagonal steel-glass
        // falloff. Applied as vertex colours (free -- no shader, no material),
        // lerped along the rect's x+y diagonal so the sheen runs upper-left to
        // lower-right the way the render does.
        public bool UseGradient = false;
        public Color GradientTo = Color.white;

        private Color32 Sample(Rect r, Vector2 p)
        {
            if (!UseGradient) return color;
            float dx = r.width <= 0f ? 0f : (p.x - r.xMin) / r.width;
            float dy = r.height <= 0f ? 0f : (r.yMax - p.y) / r.height;
            return Color.Lerp(color, GradientTo, Mathf.Clamp01((dx * 0.75f) + (dy * 0.25f)));
        }

        protected override void OnPopulateMesh(VertexHelper vh)
        {
            vh.Clear();
            Rect r = GetPixelAdjustedRect();
            if (r.width <= 0f || r.height <= 0f) return;

            if (IsCircle)
            {
                const int segments = 40;
                Vector2 center = r.center;
                float rx = r.width / 2f, ry = r.height / 2f;
                vh.AddVert(center, Sample(r, center), Vector2.zero);
                for (int i = 0; i <= segments; i++)
                {
                    float ang = (i / (float)segments) * Mathf.PI * 2f;
                    Vector2 p = center + new Vector2(Mathf.Cos(ang) * rx, Mathf.Sin(ang) * ry);
                    vh.AddVert(p, Sample(r, p), Vector2.zero);
                }
                for (int i = 1; i <= segments; i++)
                    vh.AddTriangle(0, i, i + 1);
                return;
            }

            // Chamfered hexagon: top-left and bottom-right stay square corners;
            // top-right and bottom-left are each cut by `ch`.
            float ch = Mathf.Min(ChamferSize, Mathf.Min(r.width, r.height) * 0.5f);
            float xMin = r.xMin, xMax = r.xMax, yMin = r.yMin, yMax = r.yMax;
            if (ch <= 0f)
            {
                var q = new[]
                {
                    new Vector2(xMin, yMin), new Vector2(xMin, yMax),
                    new Vector2(xMax, yMax), new Vector2(xMax, yMin),
                };
                for (int i = 0; i < 4; i++) vh.AddVert(q[i], Sample(r, q[i]), Vector2.zero);
                vh.AddTriangle(0, 1, 2);
                vh.AddTriangle(0, 2, 3);
                return;
            }

            Vector2[] pts =
            {
                new Vector2(xMin, yMax),              // top-left
                new Vector2(xMax - ch, yMax),         // start of top-right chamfer
                new Vector2(xMax, yMax - ch),         // end of top-right chamfer
                new Vector2(xMax, yMin),              // bottom-right
                new Vector2(xMin + ch, yMin),         // start of bottom-left chamfer
                new Vector2(xMin, yMin + ch),         // end of bottom-left chamfer
            };
            Vector2 c0 = r.center;
            vh.AddVert(c0, Sample(r, c0), Vector2.zero);
            for (int i = 0; i < pts.Length; i++)
                vh.AddVert(pts[i], Sample(r, pts[i]), Vector2.zero);
            for (int i = 1; i <= pts.Length; i++)
                vh.AddTriangle(0, i, i % pts.Length + 1);
        }
    }

    // The badge's signature element, ported from the prototype's PulseFieldGlyph
    // v2 class in radio_big_pill.html rather than re-invented: a WIDE, PINCHED
    // lattice sheet. A rectangular grid in normalised (xn, yn) space is
    // displaced by a taper -- pow(cos(xn*PI/2), TaperExp) -- that drives both
    // the vertical extent AND the z-depth to zero at the left and right ends,
    // so the sheet is fat through the middle and pinched to a point at each
    // tip. Every lattice row rides the SAME oscilloscope trace the bright
    // centreline draws (damped by LatticeRide); that shared ride is what makes
    // the whole sheet read as one waveform instead of a grid with a line drawn
    // on top of it. The fake 3D is a yaw + pitch rotation followed by a single
    // perspective divide.
    //
    // Two things from the prototype could not come across, and are faked:
    //   - It composites with globalCompositeOperation 'lighter' (additive) and
    //     blooms via three blurred drawImage passes off an offscreen buffer.
    //     There is no Unity Editor project here, so there is no material or
    //     shader asset to import -- this alpha-blends, and stands in for the
    //     bloom with a wide dim pass under a narrow hot pass. Same trick, one
    //     layer instead of three.
    //   - The dj-talking state's DJ-ID face knockout is dropped entirely.
    //
    // Line counts are lower than the prototype's (26 segments / 5 rows / 10
    // cols): this rebuilds its whole mesh every frame on the UI thread, so it
    // runs ~400 quads per rebuild rather than ~550. That is a judgment call
    // about uGUI cost, not a measured budget.
    internal class PulseFieldGlyph : MaskableGraphic
    {
        internal enum Mode { Idle, Playing, DjTalking, Paused }

        private const int Rows = 5;     // lattice rows, top to bottom
        private const int Cols = 9;     // ribs, left to right
        private const int Nx = 34;      // samples along one row
        private const int Ny = 10;      // samples along one rib
        private const int WaveN = 48;   // samples along the bright trace

        private const float TaperExp = 1.5f;
        private const float LatticeRide = 0.34f;

        private static readonly Vector3 CyDim = new Vector3(11f, 143f, 174f);
        private static readonly Vector3 CyHot = new Vector3(190f, 250f, 255f);
        private static readonly Vector3 AmDim = new Vector3(184f, 123f, 18f);
        private static readonly Vector3 AmHot = new Vector3(255f, 214f, 138f);

        public Mode State = Mode.Idle;
        // The badge's fill, painted back over the lattice behind the DJ face.
        // Canvas 2D punched a hole with destination-out; uGUI has no such
        // blend, but the field sits on an opaque badge of this colour, so
        // repainting it is the same picture.
        public Color32 KnockoutColor = new Color32(10, 18, 32, 240);
        // Set by RadioBigHud in lockstep with its Canvas.enabled.
        public bool Animate;

        // The prototype's `this.p` -- every one of these is lerped toward its
        // per-state target rather than snapped, which is why a state change
        // reads as the sheet re-forming instead of popping.
        private float _warp = 0.16f, _spike = 0.55f, _speed = 0.6f, _spin = 0.22f;
        private float _erratic = 0.16f, _glow = 0.78f, _dim = 0.82f, _amber = 0f;
        // The prototype's faceA: fade weight of the DJ ID icon, only ever
        // non-zero in DjTalking (and hard-gated at draw time as well).
        private float _faceA = 0f;

        private float _t, _rot, _level = 0.2f;
        // Set once per rebuild in OnPopulateMesh, read by Pt/Project.
        private float _halfW, _halfH, _depthAmp, _yaw, _pitch;

        private void Update()
        {
            // Driven by RadioBigHud, NOT by Graphic.canvas. The hud hides itself
            // by disabling its Canvas, and Graphic.CacheCanvas only ever caches
            // an *active and enabled* Canvas -- so `canvas` reads null the whole
            // time the hud is hidden, and (measured 2026-08-20) was still null
            // once it was shown again, which left this Update returning early
            // forever and the sheet frozen on the single mesh built at Awake.
            // An explicit flag set beside `_canvas.enabled` can't drift from it.
            EnsureFace();
            if (!Animate) return;
            // Unscaled: the HUD must keep moving while the game is paused.
            Step(Mathf.Min(0.05f, Time.unscaledDeltaTime));
            PaintFace();            // after Step: reads the _faceA it just moved
            SetVerticesDirty();
        }

        private void Targets(out float warp, out float spike, out float speed, out float spin,
                             out float erratic, out float glow, out float dim, out float amber)
        {
            switch (State)
            {
                case Mode.Playing:
                    warp = 0.220f; spike = 0.95f; speed = 1.45f; spin = 0.55f;
                    erratic = 0.26f; glow = 1.00f; dim = 1.00f; amber = 0f; return;
                case Mode.DjTalking:
                    warp = 0.140f; spike = 0.70f; speed = 1.70f; spin = 0.30f;
                    erratic = 1.00f; glow = 0.92f; dim = 0.85f; amber = 1f; return;
                case Mode.Paused:
                    warp = 0.060f; spike = 0.16f; speed = 0.10f; spin = 0.06f;
                    erratic = 0.00f; glow = 0.45f; dim = 0.45f; amber = 0f; return;
                default:
                    warp = 0.160f; spike = 0.55f; speed = 0.60f; spin = 0.22f;
                    erratic = 0.16f; glow = 0.78f; dim = 0.82f; amber = 0f; return;
            }
        }

        private void Step(float dt)
        {
            float wT, sT, spT, snT, eT, gT, dT, aT;
            Targets(out wT, out sT, out spT, out snT, out eT, out gT, out dT, out aT);
            float k = Mathf.Min(1f, dt * 3.2f);
            _warp += (wT - _warp) * k;
            _spike += (sT - _spike) * k;
            _speed += (spT - _speed) * k;
            _spin += (snT - _spin) * k;
            _erratic += (eT - _erratic) * k;
            _glow += (gT - _glow) * k;
            _dim += (dT - _dim) * k;
            _amber += (aT - _amber) * k;
            _faceA += ((State == Mode.DjTalking ? 1f : 0f) - _faceA) * k;

            _t += dt * (0.35f + _speed);
            _rot += dt * (0.10f + _spin * 0.55f);

            // Envelope. Playing pumps on a fake beat; dj-talking is a gated
            // syllable stutter (fast attack, hence the higher follow rate);
            // idle breathes.
            float target;
            if (State == Mode.Playing)
            {
                float beat = Mathf.Pow(Mathf.Max(0f, Mathf.Sin(_t * 3.4f)), 6f);
                target = 0.30f + 0.55f * beat + 0.22f * Fbm1(_t * 2.2f);
            }
            else if (State == Mode.DjTalking)
            {
                float gate = Smoothstep(0.34f, 0.52f, Fbm1(_t * 0.55f + 11.3f));
                float syllable = Fbm1(_t * 7.5f) * Fbm1(_t * 3.1f + 4.2f) * 1.6f;
                target = 0.10f + gate * (0.22f + syllable);
            }
            else if (State == Mode.Paused)
            {
                target = 0.05f;
            }
            else
            {
                target = 0.24f + 0.14f * Mathf.Sin(_t * 1.15f) + 0.08f * Fbm1(_t * 0.8f);
            }
            _level += (target - _level) * Mathf.Min(1f, dt * (State == Mode.DjTalking ? 16f : 9f));
        }

        // Value noise, matching the prototype's hash/noise/fbm. Deterministic
        // in _t, so nothing flickers between rebuilds.
        private static float Hash1(float n)
        {
            float s = Mathf.Sin(n * 127.1f) * 43758.5453f;
            return s - Mathf.Floor(s);
        }

        private static float Noise1(float x)
        {
            float i = Mathf.Floor(x), f = x - i;
            float u = f * f * (3f - 2f * f);
            return Hash1(i) * (1f - u) + Hash1(i + 1f) * u;
        }

        private static float Fbm1(float x)
        {
            return Noise1(x) * 0.55f
                 + Noise1(x * 2.13f + 7.7f) * 0.30f
                 + Noise1(x * 4.71f + 3.1f) * 0.15f;
        }

        private static float Smoothstep(float e0, float e1, float x)
        {
            float t = Mathf.Clamp01((x - e0) / (e1 - e0));
            return t * t * (3f - 2f * t);
        }

        // The pinch. Also gates the ribs -- past the point where the taper is
        // effectively zero there is nothing left to draw.
        private static float TaperAt(float xn)
        {
            // Float32 Mathf.PI/2 rounds ABOVE true pi/2, so Cos() at xn = +/-1 is
            // ~-4.4e-8 -- and Pow(negative, 1.5) is NaN. One NaN vertex poisons the
            // mesh bounds and the native canvas cull drops the whole renderer, which
            // is how this graphic drew nothing while every C#-side field read healthy.
            // Clamp to zero: that is the taper's intent at the tips anyway.
            float c = Mathf.Cos(Mathf.Clamp(xn, -1f, 1f) * Mathf.PI / 2f);
            return Mathf.Pow(Mathf.Max(0f, c), TaperExp);
        }

        // Surface displacement: two crossing sines plus, when erratic, a noise
        // term. Feeds both the sheet's thickness and its depth.
        private float Grid(float xn, float yn)
        {
            float amp = Mathf.Clamp(_warp * 1.7f, 0f, 0.44f) * (0.45f + _level * 0.95f);
            float n = Mathf.Sin(xn * 10.5f - _t * 2.6f) * 0.5f
                    + Mathf.Sin(yn * 7.5f + _t * 2.0f) * 0.5f;
            if (_erratic > 0.01f)
                n += (Fbm1(xn * 4.0f + _t * 4.5f) * 2f - 1f) * 0.55f * _erratic;
            return n * amp;
        }

        // The raw oscilloscope signal, before taper and soft clip.
        private float Wave(float q)
        {
            float e = _erratic;
            float x = q * 3.2f;
            float n = Fbm1(x * 2.4f + _t * 3.6f) * 2f - 1f;
            n += (Fbm1(x * 6.3f - _t * 5.6f) * 2f - 1f) * (0.55f + e * 0.55f);
            n = Mathf.Sign(n) * Mathf.Pow(Mathf.Abs(n) / 1.45f, 0.55f);
            if (e > 0.01f)
            {
                float burst = Fbm1(x * 11.7f + _t * 9.4f);
                n *= 1f + e * 1.5f * Mathf.Pow(burst, 3f);
                float gate = 0.30f + 0.70f * Smoothstep(0.22f, 0.58f, Fbm1(x * 0.85f + _t * 2.4f));
                n *= 1f - e + e * gate;
            }
            return n * _spike * (0.30f + _level * 1.25f);
        }

        private float Trace(float xn)
        {
            float tp = Mathf.Pow(TaperAt(xn), 0.55f);
            float v = Wave(xn) * 0.62f * tp;
            return 1.05f * (float)System.Math.Tanh(v / 1.05f);   // soft clip, no hard corners
        }

        // Yaw, then pitch, then one perspective divide. Returns x/y in local
        // rect space plus a 0..1 depth in z, which drives per-segment alpha,
        // width and colour so nearer geometry reads as nearer.
        private Vector3 Project(Vector2 c, float X, float Y, float Z)
        {
            float xp = X * _halfW, yp = Y * _halfH, zp = Z * _halfH;
            float cw = Mathf.Cos(_yaw), sw = Mathf.Sin(_yaw);
            float x1 = xp * cw + zp * sw;
            float z1 = -xp * sw + zp * cw;
            float cp = Mathf.Cos(_pitch), sp = Mathf.Sin(_pitch);
            float y1 = yp * cp - z1 * sp;
            float z2 = yp * sp + z1 * cp;
            float f = 3.1f * _halfW;
            float s = f / (f - z2);
            // +y1 rather than the canvas's -y1: uGUI's local y axis points up.
            return new Vector3(c.x + x1 * s, c.y + y1 * s,
                               Mathf.Clamp01(0.5f + z2 / (1.25f * _halfW)));
        }

        private Vector3 Pt(Vector2 c, float xn, float yn)
        {
            float tp = TaperAt(xn);
            float gn = Grid(xn, yn);
            float y = Trace(xn) * LatticeRide + yn * tp * (1f + gn);
            float z = Mathf.Cos(yn * Mathf.PI / 2f) * tp * (1f + gn) * _depthAmp;
            return Project(c, xn, y, z);
        }

        private Color32 Shade(float shade, float alpha)
        {
            Vector3 cy = Vector3.Lerp(CyDim, CyHot, Mathf.Clamp01(shade));
            Vector3 am = Vector3.Lerp(AmDim, AmHot, Mathf.Clamp01(shade));
            Vector3 c = Vector3.Lerp(cy, am, Mathf.Clamp01(_amber));
            return new Color32((byte)Mathf.Clamp(c.x, 0f, 255f),
                               (byte)Mathf.Clamp(c.y, 0f, 255f),
                               (byte)Mathf.Clamp(c.z, 0f, 255f),
                               (byte)(Mathf.Clamp01(alpha) * 255f));
        }

        protected override void OnPopulateMesh(VertexHelper vh)
        {
            vh.Clear();
            Rect r = GetPixelAdjustedRect();
            if (r.width <= 0f || r.height <= 0f) return;

            Vector2 c = r.center;
            const float pad = 2f;
            _halfW = r.width / 2f - pad;
            // 0.62 is the prototype's sheet aspect: wide and shallow, not square.
            _halfH = (r.height / 2f - pad) * 0.62f * (1f + _level * 0.06f);
            if (_halfW <= 0f || _halfH <= 0f) return;
            _depthAmp = 0.85f;
            _yaw = Mathf.Sin(_rot * 1.7f) * (0.16f + _spin * 0.42f);
            _pitch = 0.26f + Mathf.Sin(_t * 0.31f) * 0.05f;

            // The prototype's 0.016*W assumes a canvas backing store at
            // devicePixelRatio AND additive compositing stacking overlapping
            // strokes into brightness. Here one unit is barely one device pixel
            // at idle size, and uGUI does no antialiasing -- a sub-pixel quad
            // can miss every sample point and rasterize to nothing. Floor it
            // well above 1.
            float lw = Mathf.Max(1.4f, r.width * 0.030f);

            var row = new Vector3[Nx + 1];
            for (int i = 0; i < Rows; i++)
            {
                float yn = -1f + 2f * (i / (float)(Rows - 1));
                // The centre row is deliberately faint -- the bright trace sits
                // on it, and two hot lines on the same path just read as one
                // fat one.
                float weight = Mathf.Abs(yn) < 1e-3f ? 0.35f : 1f;
                for (int s = 0; s <= Nx; s++) row[s] = Pt(c, -1f + 2f * s / Nx, yn);
                StrokePoly(vh, row, row.Length, lw, _dim * weight);
            }

            var rib = new Vector3[Ny + 1];
            for (int j = 0; j < Cols; j++)
            {
                float xn = -1f + 2f * (j / (float)(Cols - 1));
                if (TaperAt(xn) < 0.02f) continue;      // pinched to nothing at the tips
                for (int s = 0; s <= Ny; s++) rib[s] = Pt(c, xn, -1f + 2f * s / Ny);
                StrokePoly(vh, rib, rib.Length, lw * 0.85f, _dim * 0.78f);
            }

            var wave = new Vector3[WaveN + 1];
            var axis = new Vector3[WaveN + 1];
            for (int i = 0; i <= WaveN; i++)
            {
                float xn = -1f + 2f * (i / (float)WaveN);
                float z = TaperAt(xn) * _depthAmp;
                wave[i] = Project(c, xn, Trace(xn), z);
                axis[i] = Project(c, xn, 0f, z);
            }
            StrokePoly(vh, axis, axis.Length, lw * 0.55f, _dim * 0.30f);
            // Bloom stand-in: wide + dim underneath, narrow + hot on top.
            StrokePoly(vh, wave, wave.Length, lw * 2.6f, _dim * 0.30f * _glow);
            StrokePoly(vh, wave, wave.Length, lw * 1.05f, _dim * 0.95f * _glow);

            // The DJ ID icon sits on top of everything, on a knocked-out patch
            // of badge so the trace reads as passing BEHIND the head.
            if (State == Mode.DjTalking && _faceA > 0.02f)
            {
                float k = Mathf.Clamp01(_faceA);
                // 0.58 of the half-size, not the prototype's 0.44: its head was
                // sized against a page-scale canvas, and at 46 px the mockup's
                // "fills most of the circle" proportion is what reads.
                float half = Mathf.Min(r.width, r.height) / 2f;
                float hh = half * 0.58f;
                Knockout(vh, c, Mathf.Min(hh * 1.75f, half), k);
                // The face itself is no longer mesh: it is two RawImage
                // children (see EnsureFace), which render above this graphic
                // because they are children of it. Only the knockout that
                // seats it is still drawn here.
            }
        }

        // Radial fade of the badge colour: 0.94 at the centre, 0.74 at 45%,
        // 0 at the rim -- the prototype's gradient stops, as two ring bands.
        private void Knockout(VertexHelper vh, Vector2 c, float radius, float k)
        {
            const int segs = 28;
            Color32 fill = KnockoutColor;
            Color32 c0 = new Color32(fill.r, fill.g, fill.b, (byte)(0.94f * k * 255f));
            Color32 c1 = new Color32(fill.r, fill.g, fill.b, (byte)(0.74f * k * 255f));
            Color32 c2 = new Color32(fill.r, fill.g, fill.b, 0);
            int centre = vh.currentVertCount;
            vh.AddVert(c, c0, Vector2.zero);
            for (int i = 0; i <= segs; i++)
            {
                float a = i / (float)segs * Mathf.PI * 2f;
                Vector2 d = new Vector2(Mathf.Cos(a), Mathf.Sin(a));
                vh.AddVert(c + d * radius * 0.45f, c1, Vector2.zero);
                vh.AddVert(c + d * radius, c2, Vector2.zero);
            }
            for (int i = 0; i < segs; i++)
            {
                int a = centre + 1 + i * 2, b = a + 2;
                vh.AddTriangle(centre, a, b);
                vh.AddTriangle(a, a + 1, b + 1);
                vh.AddTriangle(a, b + 1, b);
            }
        }

        // ---- DJ ID icon -------------------------------------------------
        //
        // Two RawImage children stacked on a pre-rendered 512px asset pair,
        // replacing the centroid-fan polygon mesh this used to draw. That mesh
        // was 8 bezier samples a curve with no anti-aliasing anywhere in uGUI
        // to soften it, so the skull edge was visibly faceted and the stair-
        // stepping was worst at exactly the 80-120px the badge actually runs
        // at. A texture gets analytic-quality edges for free, plus shading and
        // visor speculars a vertex-colour fan cannot express at all.
        //
        // Why TWO layers rather than one baked RGBA:
        //   _faceDark is the head silhouette, tinted with KnockoutColor. It is
        //     the badge fill, so the visor and facial hair are HOLES in the lit
        //     layer that let it through -- exactly what the old `cut` colour
        //     did, and it stays correct if KnockoutColor is ever retuned.
        //   _faceLit is the skin, tinted with the accent Shade(). Its texture
        //     RGB is a luminance field, so the flat tint lands shaded.
        // A single baked texture would have frozen both colours at author time
        // and stopped the face tracking the amber/cyan accent lerp.
        //
        // These are children of this Graphic, so they draw ON TOP of its mesh
        // (including the Knockout) without needing a second canvas or any
        // sorting override.
        private RawImage _faceLit, _faceDark;
        private bool _faceBuilt;

        private void EnsureFace()
        {
            if (_faceBuilt) return;
            _faceBuilt = true;      // set FIRST: a failed load must not retry every frame
            Texture2D lit = DjFaceArt.Lit, dark = DjFaceArt.Dark;
            if (lit == null || dark == null) return;   // degrades to a faceless badge
            _faceDark = FaceLayer("RBFaceDark", dark);
            _faceLit = FaceLayer("RBFaceLit", lit);    // added second == drawn second
        }

        private RawImage FaceLayer(string name, Texture2D tex)
        {
            var go = new GameObject(name, typeof(RectTransform));
            var rt = (RectTransform)go.transform;
            rt.SetParent(transform, false);
            // Stretched to this graphic's rect, so the face rescales with the
            // badge (56px idle -> 84px open) with no per-frame sizing. The
            // asset is authored with the head at 0.58 of the texture height to
            // match the `hh = half * 0.58` the mesh face used, and centred 3px
            // high to match its `y + hh * 0.02` -- that is what keeps the icon
            // the same size and place as before across this swap.
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = Vector2.zero;
            rt.offsetMax = Vector2.zero;
            var ri = go.AddComponent<RawImage>();
            ri.texture = tex;
            ri.raycastTarget = false;
            ri.color = new Color(1f, 1f, 1f, 0f);
            ri.enabled = false;
            return ri;
        }

        // Tint + fade, driven by the same _faceA and Shade() the mesh face used.
        private void PaintFace()
        {
            if (_faceLit == null) return;
            float k = Mathf.Clamp01(_faceA);
            // Same gate as OnPopulateMesh's, deliberately: the face and the
            // Knockout that seats it must appear and vanish together, or the
            // head briefly draws over an undimmed lattice.
            bool on = State == Mode.DjTalking && k > 0.02f;
            if (_faceLit.enabled != on)
            {
                _faceLit.enabled = on;
                _faceDark.enabled = on;
            }
            if (!on) return;
            // Lit texture RGB is the shading, so this flat accent comes out
            // graded; alphas match the mesh face's 0.95 / 0.96.
            _faceLit.color = Shade(0.70f, 0.95f * k);
            Color32 ko = KnockoutColor;
            _faceDark.color = new Color32(ko.r, ko.g, ko.b, (byte)(0.96f * k * 255f));
        }

        // Fired at most once. A NaN vertex never throws: it poisons the mesh
        // bounds, the native canvas cull drops the renderer, and every C#-side
        // field still reads healthy -- so the only trace is this line.
        private bool _nanReported;

        // One quad per segment. Segments overlap slightly at the joins so the
        // polyline doesn't show gaps on tight curves -- cheaper and steadier
        // than mitring, at this line width.
        private void StrokePoly(VertexHelper vh, Vector3[] pts, int count, float lineWidth, float dimK)
        {
            for (int i = 1; i < count; i++)
            {
                Vector3 a3 = pts[i - 1], b3 = pts[i];
                // A single NaN vertex silently kills the whole graphic (it poisons
                // the mesh bounds and the native canvas cull drops the renderer),
                // and every guard below fails OPEN on NaN since all comparisons
                // against NaN are false. Catch it here before it reaches vh.
                if (float.IsNaN(a3.x + a3.y + a3.z + b3.x + b3.y + b3.z))
                {
                    if (!_nanReported)
                    {
                        _nanReported = true;
                        Plugin.Log.LogWarning("[Radio] glyph: NaN vertex skipped (" + a3 + " -> " + b3 + ")");
                    }
                    continue;
                }
                float depth = (a3.z + b3.z) * 0.5f;
                float alpha = (0.075f + depth * depth * 0.78f) * dimK;
                if (alpha <= 0.012f) continue;

                Vector2 a = new Vector2(a3.x, a3.y), b = new Vector2(b3.x, b3.y);
                Vector2 d = b - a;
                float len = d.magnitude;
                if (len < 1e-4f) continue;
                d /= len;

                Vector2 ext = d * (len * 0.02f);
                Vector2 n = new Vector2(-d.y, d.x) * (lineWidth * (0.70f + depth * 0.55f) * 0.5f);
                Color32 col = Shade(0.18f + depth * 0.52f, alpha);
                AddQuad(vh, a - ext - n, a - ext + n, b + ext + n, b + ext - n, col);
            }
        }

        private static void AddQuad(VertexHelper vh, Vector2 p0, Vector2 p1, Vector2 p2, Vector2 p3, Color32 c)
        {
            int i = vh.currentVertCount;
            vh.AddVert(p0, c, Vector2.zero);
            vh.AddVert(p1, c, Vector2.zero);
            vh.AddVert(p2, c, Vector2.zero);
            vh.AddVert(p3, c, Vector2.zero);
            vh.AddTriangle(i, i + 1, i + 2);
            vh.AddTriangle(i, i + 2, i + 3);
        }
    }

    // The prototype's .rb-bracket pair: viewfinder corners at the banner's two
    // chamfers. Each is two 24x2 arms held `Inset` clear of the corner itself,
    // so the chamfer cut shows through the gap.
    internal class CornerBrackets : MaskableGraphic
    {
        public float Arm = 24f;
        public float Thickness = 2f;
        public float Inset = 20f;      // must match the panel's ChamferSize

        protected override void OnPopulateMesh(VertexHelper vh)
        {
            vh.Clear();
            Rect r = GetPixelAdjustedRect();
            if (r.width <= 0f || r.height <= 0f) return;
            if (r.width < Inset + Arm + 4f) return;    // mid-animation: too narrow to read
            Color32 c = color;

            // top-right
            AddRect(vh, c, r.xMax - Inset - Arm, r.yMax - Thickness, Arm, Thickness);
            AddRect(vh, c, r.xMax - Thickness, r.yMax - Inset - Arm, Thickness, Arm);
            // bottom-left
            AddRect(vh, c, r.xMin + Inset, r.yMin, Arm, Thickness);
            AddRect(vh, c, r.xMin, r.yMin + Inset, Thickness, Arm);
        }

        private static void AddRect(VertexHelper vh, Color32 c, float x, float y, float w, float h)
        {
            int i = vh.currentVertCount;
            vh.AddVert(new Vector2(x, y), c, Vector2.zero);
            vh.AddVert(new Vector2(x, y + h), c, Vector2.zero);
            vh.AddVert(new Vector2(x + w, y + h), c, Vector2.zero);
            vh.AddVert(new Vector2(x + w, y), c, Vector2.zero);
            vh.AddTriangle(i, i + 1, i + 2);
            vh.AddTriangle(i, i + 2, i + 3);
        }
    }

    // The prototype's .rb-led: a dashed outline crawling around the banner's
    // chamfered perimeter (SVG stroke-dasharray 15 12, dashoffset animated to
    // -108 over 5.5s). Dashes are solved analytically per edge rather than by
    // sampling the perimeter, so the whole thing costs ~30 quads a pass instead
    // of ~400.
    internal class DashedChamferTrace : MaskableGraphic
    {
        public float ChamferSize = 20f;
        public float Dash = 15f;
        public float Gap = 12f;
        public float CrawlDistance = 108f;   // matches the keyframe
        public float CrawlPeriod = 5.5f;
        public float Width = 1.6f;
        // Set by RadioBigHud in lockstep with its Canvas.enabled.
        public bool Animate;

        private void Update()
        {
            if (!Animate) return;   // see PulseFieldGlyph.Update
            SetVerticesDirty();
        }

        protected override void OnPopulateMesh(VertexHelper vh)
        {
            vh.Clear();
            Rect r = GetPixelAdjustedRect();
            if (r.width <= 4f || r.height <= 4f) return;

            float ch = Mathf.Min(ChamferSize, Mathf.Min(r.width, r.height) * 0.5f);
            float inset = Width * 0.5f;
            float x0 = r.xMin + inset, x1 = r.xMax - inset;
            float y0 = r.yMin + inset, y1 = r.yMax - inset;
            if (x1 <= x0 || y1 <= y0) return;

            Vector2[] loop =
            {
                new Vector2(x0, y1), new Vector2(x1 - ch, y1), new Vector2(x1, y1 - ch),
                new Vector2(x1, y0), new Vector2(x0 + ch, y0), new Vector2(x0, y0 + ch),
            };

            // Negative offset == the dashes travel forward along the path.
            float offset = -(Time.unscaledTime / CrawlPeriod) * CrawlDistance;
            Color32 core = color;
            Color32 halo = new Color(color.r, color.g, color.b, color.a * 0.30f);
            EmitDashes(vh, loop, Width * 3.2f, halo, offset);   // glow stand-in
            EmitDashes(vh, loop, Width, core, offset);
        }

        private void EmitDashes(VertexHelper vh, Vector2[] loop, float w, Color32 c, float offset)
        {
            float period = Dash + Gap;
            if (period <= 0.01f) return;
            float s = 0f;
            for (int i = 0; i < loop.Length; i++)
            {
                Vector2 a = loop[i], b = loop[(i + 1) % loop.Length];
                Vector2 d = b - a;
                float len = d.magnitude;
                if (len < 1e-4f) continue;
                d /= len;
                Vector2 n = new Vector2(-d.y, d.x) * (w * 0.5f);

                // Start one period early so a dash straddling this edge's start
                // still gets its tail drawn.
                float k = Mathf.Floor((s + offset) / period) - 1f;
                while (true)
                {
                    float dashStart = k * period - offset;
                    if (dashStart >= s + len) break;
                    float t0 = Mathf.Max(dashStart, s) - s;
                    float t1 = Mathf.Min(dashStart + Dash, s + len) - s;
                    if (t1 > t0)
                    {
                        Vector2 p0 = a + d * t0, p1 = a + d * t1;
                        int v = vh.currentVertCount;
                        vh.AddVert(p0 - n, c, Vector2.zero);
                        vh.AddVert(p0 + n, c, Vector2.zero);
                        vh.AddVert(p1 + n, c, Vector2.zero);
                        vh.AddVert(p1 - n, c, Vector2.zero);
                        vh.AddTriangle(v, v + 1, v + 2);
                        vh.AddTriangle(v, v + 2, v + 3);
                    }
                    k += 1f;
                }
                s += len;
            }
        }
    }

    // Transport row glyphs (prev/play/pause/next), drawn as flat triangles/bars
    // via OnPopulateMesh rather than TMP unicode glyphs -- a shipped build's
    // font atlas is commonly baked latin-only and is not guaranteed to carry
    // media symbols. Same MaskableGraphic requirement as ChamferedPanel above.
    internal class TransportIcon : MaskableGraphic
    {
        public enum Kind { Prev, Play, Pause, Next }
        // A property, not a field: the play key swaps between Play and Pause
        // at runtime, and a plain field assignment would leave the old mesh on
        // screen -- uGUI only rebuilds what something marks dirty.
        public Kind IconKind
        {
            get { return _kind; }
            set { if (_kind == value) return; _kind = value; SetVerticesDirty(); }
        }
        private Kind _kind = Kind.Play;

        protected override void OnPopulateMesh(VertexHelper vh)
        {
            vh.Clear();
            Rect r = GetPixelAdjustedRect();
            if (r.width <= 0f || r.height <= 0f) return;
            Color32 c = color;
            float w = r.width, h = r.height, cx = r.center.x, cy = r.center.y;

            switch (_kind)
            {
                case Kind.Play:
                    AddTri(vh, c,
                        new Vector2(cx - w * 0.28f, cy + h * 0.36f),
                        new Vector2(cx - w * 0.28f, cy - h * 0.36f),
                        new Vector2(cx + w * 0.34f, cy));
                    break;
                case Kind.Pause:
                    AddBar(vh, c, cx - w * 0.20f, cy, w * 0.16f, h * 0.62f);
                    AddBar(vh, c, cx + w * 0.20f, cy, w * 0.16f, h * 0.62f);
                    break;
                case Kind.Next:
                    AddTri(vh, c,
                        new Vector2(cx - w * 0.30f, cy + h * 0.34f),
                        new Vector2(cx - w * 0.30f, cy - h * 0.34f),
                        new Vector2(cx + w * 0.14f, cy));
                    AddBar(vh, c, cx + w * 0.30f, cy, w * 0.14f, h * 0.60f);
                    break;
                case Kind.Prev:
                    AddTri(vh, c,
                        new Vector2(cx + w * 0.30f, cy + h * 0.34f),
                        new Vector2(cx + w * 0.30f, cy - h * 0.34f),
                        new Vector2(cx - w * 0.14f, cy));
                    AddBar(vh, c, cx - w * 0.30f, cy, w * 0.14f, h * 0.60f);
                    break;
            }
        }

        private static void AddTri(VertexHelper vh, Color32 c, Vector2 a, Vector2 b, Vector2 p)
        {
            int i = vh.currentVertCount;
            vh.AddVert(a, c, Vector2.zero);
            vh.AddVert(b, c, Vector2.zero);
            vh.AddVert(p, c, Vector2.zero);
            vh.AddTriangle(i, i + 1, i + 2);
        }

        private static void AddBar(VertexHelper vh, Color32 c, float cx, float cy, float w, float h)
        {
            int i = vh.currentVertCount;
            vh.AddVert(new Vector2(cx - w / 2, cy - h / 2), c, Vector2.zero);
            vh.AddVert(new Vector2(cx - w / 2, cy + h / 2), c, Vector2.zero);
            vh.AddVert(new Vector2(cx + w / 2, cy + h / 2), c, Vector2.zero);
            vh.AddVert(new Vector2(cx + w / 2, cy - h / 2), c, Vector2.zero);
            vh.AddTriangle(i, i + 1, i + 2);
            vh.AddTriangle(i, i + 2, i + 3);
        }
    }
}
