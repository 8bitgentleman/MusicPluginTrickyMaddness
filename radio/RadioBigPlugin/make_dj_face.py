#!/usr/bin/env python3
"""Generate the Radio Big DJ-face HUD icon as two 512x512 PNG masks.

Regenerate with:

    python3 radio/RadioBigPlugin/make_dj_face.py

Writes, next to itself:
    dj_face_dark.png  -- silhouette coverage, DILATED by DARK_RIM. RGB is flat
                         white; only A matters. Tinted at runtime with the badge
                         fill (KnockoutColor) and drawn UNDER the lit layer, so
                         it is (a) what shows through the holes the lit layer
                         leaves for the eyewear and beard, and (b) a dark rim
                         around the whole icon, which is what separates it from
                         the lattice in the reference art.
    dj_face_lit.png   -- everything that takes the accent colour: the skin, the
                         lens sheen, and the outer glow. RGB carries the
                         SHADING as a luminance field, so a flat runtime tint
                         comes out graded (the sheen reads brighter than the
                         skin, the glow reads soft) rather than as a flat blob.

Both are embedded in RadioBigTM.dll by build.sh (mcs -resource:) and loaded with
Texture2D.LoadImage; see RadioHudGraphics.cs DjFaceArt.

GEOMETRY IS TRACED FROM THE REFERENCE, NOT INVENTED.
Source: Gemini_Generated_Image_hplxkphplxkphplx.png, the "DJ Autonomo ID Icon"
in the annotated mock-up. The icon was segmented out of that image by cyan
threshold and its per-row half-widths measured; PROFILE below is that
measurement, in the crop's own pixels, and every other landmark is quoted in
the same coordinates and mapped through CY/CXo. Re-derive rather than nudge:
the reference head is 106px tall with its crown at crop y=16 and cx=55.

What the reference actually is (all of this differs from a plain "bald head
with shades", which is what an earlier pass built from a verbal description):
  * a BIG domed cranium -- widest at 0.34 of the way down, half-width 0.325 of
    head height -- over a distinctly narrow lower face,
  * large protruding ear pads, 0.11 x 0.26 of head height, not small bumps,
  * TWIN large ROUNDED lenses, all but touching at a sliver of a bridge, hung
    off ONE THIN swept brow bar -- not a solid slab across the eyes,
  * a circle beard in three dark shapes -- moustache arc, solid goatee mass,
    thin side straps -- and NO drawn mouth; the lips are just the skin gap,
  * flat fill with a soft outer glow -- NOT an airbrushed 3D gradient.

Two things here are load-bearing and easy to break:

  * RGB is written across the WHOLE canvas, not just inside the mask. The
    runtime texture has mipmaps, and mipmapping non-premultiplied RGBA bleeds
    the RGB of transparent texels into the edge texels of the smaller mips. A
    luminance field defined everywhere has nothing dark to bleed.
  * HEAD_TOP/HEAD_BOT put the head at 0.58 of the texture height, matching the
    `hh = half * 0.58` the old procedural face used, so the icon keeps its size
    and place on the badge. Move those and the badge composition moves.

Rendered at 4x and box-downsampled, which is where the anti-aliasing comes
from -- there is no analytic coverage anywhere in here.
"""

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SS = 4                      # supersample factor
OUT = 512                   # final texture edge
N = OUT * SS                # working edge

CX = 256.0                  # head centre x, in FINAL pixels
HEAD_TOP = 125.0            # crown  (head = 0.50 of texture; was 0.58)
HEAD_BOT = 381.0            # chin
HEAD_H = HEAD_BOT - HEAD_TOP

DARK_RIM = 5.0              # dark-layer dilation, final px

# ---- reference frame ----------------------------------------------------
# The reference crop: cx=55, crown at y=16, chin at y=122 (106px tall).
REF_CX, REF_TOP, REF_H = 55.0, 16.0, 106.0
SCALE = HEAD_H / REF_H      # 2.811


def CY(y):
    """Reference-crop y -> texture y."""
    return HEAD_TOP + (y - REF_TOP) * SCALE


def CXo(x):
    """Reference-crop x -> texture x."""
    return CX + (x - REF_CX) * SCALE


def CW(w):
    """Reference-crop length -> texture length."""
    return w * SCALE


# Measured half-widths of the reference silhouette, (crop y, crop half-width).
# The 60..90 stretch is interpolated: the ear pads occlude the face edge there.
PROFILE = [
    (16.5, 0.0), (18, 8.5), (21, 17.5), (24, 22.0), (27, 25.0), (30, 27.0),
    (33, 29.5), (36, 31.5), (39, 32.5), (42, 33.5), (45, 34.0), (48, 34.5),
    (57, 34.5), (60, 33.5), (75, 31.5), (87, 28.5), (90, 27.5), (93, 26.5),
    (96, 25.5), (99, 24.0), (102, 22.0), (105, 20.0), (108, 18.0), (111, 15.5),
    (114, 13.0), (117, 10.5), (120, 5.5), (122, 0.0),
]


# ---------------------------------------------------------------- primitives

def blank():
    return Image.new("L", (N, N), 0)


def fill(img, pts, grow=0.0):
    """Filled polygon, optionally dilated by `grow` with ROUND corners.

    The dilation is a closed round-jointed stroke of width 2*grow laid over the
    polygon -- a Minkowski sum with a disc, which is how every rounded shape
    here (ears, lens, brow bar, beard ring) gets its corners. Author the
    polygon inset by `grow` and it lands on the intended outer bounds.
    """
    d = ImageDraw.Draw(img)
    p = [(x * SS, y * SS) for (x, y) in pts]
    d.polygon(p, fill=255)
    if grow > 0:
        d.line(p + [p[0]], fill=255, width=int(round(2 * grow * SS)), joint="curve")


def rect(x0, y0, x1, y1, r):
    """Corner points for a rounded box with outer bounds (x0,y0)-(x1,y1)."""
    return ([(x0 + r, y0 + r), (x1 - r, y0 + r), (x1 - r, y1 - r), (x0 + r, y1 - r)], r)


def stamp(img, path, r0, r1):
    """Brush a tapered round-capped stroke along `path` (radius r0 -> r1)."""
    d = ImageDraw.Draw(img)
    n = len(path)
    for i, (x, y) in enumerate(path):
        r = r0 + (r1 - r0) * (i / max(1, n - 1))
        d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=255)


def bez(p0, p1, p2, p3, steps=64):
    out = []
    for i in range(steps):
        t = i / steps
        u = 1.0 - t
        out.append((
            u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
            u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
        ))
    return out


def arr(im):
    return np.asarray(im, dtype=np.float32) / 255.0


def img(a):
    return Image.fromarray(np.clip(a * 255.0, 0, 255).astype(np.uint8))


def blur(a, radius):
    return arr(img(a).filter(ImageFilter.GaussianBlur(radius * SS)))


# ------------------------------------------------------------------- shapes

def head_outline():
    """The traced silhouette: PROFILE resampled to a quarter-pixel grid and
    lightly smoothed, so the crown and chin are round rather than faceted."""
    ty = np.array([p[0] for p in PROFILE], dtype=np.float64)
    th = np.array([p[1] for p in PROFILE], dtype=np.float64)
    ys = np.arange(PROFILE[0][0], PROFILE[-1][0] + 1e-6, 0.25)
    hw = np.interp(ys, ty, th)
    k = 9
    ker = np.ones(k) / k
    hw = np.convolve(np.pad(hw, (k, k), mode="edge"), ker, mode="same")[k:-k]
    hw = np.maximum(hw, 0.0)
    right = [(CX + CW(h), CY(y)) for y, h in zip(ys, hw)]
    left = [(CX - CW(h), CY(y)) for y, h in zip(ys[::-1], hw[::-1])]
    return right + left


# Ear pads: crop x 15.5..25.5, y 63..86. They clear the cranium by ~6 crop px
# -- enough to read as ears, not so much that they read as headphone cups, which
# is what a wider pad plus the dark rim between pad and skull looked like.
EAR_R = 14.0
EAR = (CXo(15.5), CY(63), CXo(25.5), CY(86))


def head_mask(grow=0.0):
    m = blank()
    fill(m, head_outline(), grow)
    x0, y0, x1, y1 = EAR
    for pts, r in (rect(x0, y0, x1, y1, EAR_R), ):
        fill(m, pts, r + grow)
        fill(m, [(2 * CX - x, y) for (x, y) in pts], r + grow)
    return arr(m)


def frame_mask():
    """The shades' frame: a THIN swept brow bar plus a short bridge -- not a
    slab. The reference's eyewear is two lens shapes hung off a top rim, so skin
    shows below and between the lenses; filling the whole eye band solid (an
    earlier pass did) turns it into a bandit mask that welds onto the ear pads.
    The bar dips at the bridge and rises over each brow: that V is the sweep."""
    m = blank()
    brow = bez((CXo(30.5), CY(61.5)), (CXo(37.5), CY(56.4)),
               (CXo(48.0), CY(59.4)), (CXo(55.0), CY(61.2))) \
        + bez((CXo(55.0), CY(61.2)), (CXo(62.0), CY(59.4)),
              (CXo(72.5), CY(56.4)), (CXo(79.5), CY(61.5)))
    stamp(m, brow, CW(2.1), CW(2.1))
    # bridge: a short stub down the centreline. The lenses very nearly meet, so
    # this only has a sliver to close -- widen it and it becomes a nose plug.
    stamp(m, [(CX, CY(y)) for y in (61.5, 63.0, 64.5, 66.0)], CW(2.0), CW(2.0))
    return arr(m)


def lens_mask():
    """Twin lenses: large, ROUNDED, hung off the brow bar and swept -- taller and
    lower at the outer end, meeting the bridge with only a sliver between them.

    These are DARK. In the reference the eyewear is a solid dark mass relieved
    only by a diagonal sheen on the wearer's right lens; filling the lenses with
    the accent colour turns them into glowing eyes and loses the shades. The
    mask stays separate from the frame so the sheen has something to clip to.

    The outer end runs low, to crop y 80.5. That is deliberate: stop it short
    and the skin between the lens and the wide part of the jaw becomes a lit
    triangle that reads as a cartoon cheek.
    """
    m = blank()
    r = 5.5
    pts = [
        (CXo(31.0 + r), CY(65.0 + r)), (CXo(53.5 - r), CY(63.5 + r)),
        (CXo(53.5 - r), CY(77.5 - r)), (CXo(31.0 + r), CY(80.5 - r)),
    ]
    fill(m, pts, CW(r))
    fill(m, [(2 * CX - x, y) for (x, y) in pts], CW(r))
    return arr(m)


def sheen_mask():
    """The diagonal highlight across one lens. The reference draws it as fine
    parallel hatching; a single soft streak survives 80px, hatching does not."""
    m = blank()
    pts = [
        (CXo(35.0), CY(81.0)), (CXo(41.5), CY(62.0)),
        (CXo(45.0), CY(62.0)), (CXo(38.5), CY(81.0)),
    ]
    fill(m, pts)
    return arr(m)


def beard_mask():
    """Circle beard, in exactly THREE dark shapes: a moustache arc with
    downturned ends, a solid goatee mass on the chin, and a thin strap down each
    side joining the two. Between the moustache and the goatee is plain skin.

    An earlier pass drew the goatee as a RING with a lit opening and a dark bar
    inside it. At 80px that stack -- dark ring, lit ring, dark bar -- collapses
    into a gritted-teeth grin. The reference does not draw the mouth at all; it
    is just the skin gap, and that is what reads calm rather than gurning.
    """
    m = blank()

    # moustache: arched over the lip, ends thinning and turning down
    mo = bez((CXo(39.0), CY(98.0)), (CXo(43.0), CY(93.4)),
             (CXo(50.0), CY(93.0)), (CXo(55.0), CY(93.0))) \
        + bez((CXo(55.0), CY(93.0)), (CXo(60.0), CY(93.0)),
              (CXo(67.0), CY(93.4)), (CXo(71.0), CY(98.0))) + [(CXo(71.0), CY(98.0))]
    half = len(mo) // 2
    stamp(m, list(reversed(mo[:half])), CW(2.6), CW(1.5))
    stamp(m, mo[half:], CW(2.6), CW(1.5))

    # goatee: ONE mass, built as a union of round brush stamps -- a wide capsule
    # across the top of the chin plus a vertical taper down to the point.
    # Polygon versions of this (two overlapping boxes, then a trapezoid) both
    # left a visible step or a flat shelf where they met the moustache; a brush
    # union has no corners to step.
    stamp(m, [(CXo(49.0 + 12.0 * t / 12.0), CY(106.5)) for t in range(13)],
          CW(4.5), CW(4.5))
    # The taper runs PAST the chin (to crop y 121) on purpose: beard_mask is
    # multiplied by the head mask, so the overshoot is clipped to the chin
    # outline. Stop it short instead and a lit crescent of chin survives below
    # the goatee, which reads as a drip hanging off it.
    stamp(m, [(CX, CY(107.0 + 11.0 * t / 9.0)) for t in range(10)],
          CW(6.0), CW(5.0))

    # side straps closing the ring, moustache end -> goatee. Keep the curve
    # monotone in BOTH axes: a control net that swings outward first hooks back
    # on itself and reads as a hangnail at 512, never mind at 80.
    for sgn in (-1, 1):
        strap = bez((CXo(55 + sgn * 16.0), CY(97.5)), (CXo(55 + sgn * 14.5), CY(100.0)),
                    (CXo(55 + sgn * 13.0), CY(103.0)), (CXo(55 + sgn * 10.0), CY(106.0)))
        stamp(m, strap, CW(1.6), CW(3.0))
    return arr(m)


# -------------------------------------------------------------------- build

def main():
    head = head_mask()
    head_big = head_mask(DARK_RIM)
    frame = frame_mask()
    lens = np.clip(lens_mask() * head, 0, 1)
    sheen = np.clip(sheen_mask() * lens, 0, 1)
    beard = np.clip(beard_mask() * head, 0, 1)

    # The eyewear is ONE dark mass (frame + lenses); only the lens sheen is
    # punched back out as lit.
    dark_feats = np.clip(np.clip(frame + lens + beard, 0, 1) - sheen, 0, 1)
    skin = np.clip(head - dark_feats - sheen, 0, 1)

    # ---- shading ---------------------------------------------------------
    # FLAT, deliberately. The reference is flat-vector with a glow, not an
    # airbrushed sphere; an earlier pass graded this hard enough that the head
    # read as a chrome egg.
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32) / SS

    vert = 1.0 - 0.07 * np.clip((yy - HEAD_TOP) / HEAD_H, 0, 1.3)
    hx, hy, hr = CX - 46.0, HEAD_TOP + 66.0, 132.0
    spec = np.exp(-(((xx - hx) ** 2 + (yy - hy) ** 2) / (2.0 * hr * hr)))
    inner = np.clip(blur(head, 9.0) * 1.35, 0, 1)

    lum = vert * (0.91 + 0.09 * inner) + 0.07 * spec
    lum = np.clip(lum, 0.0, 1.0)

    # Soft outer glow, outside the dark rim -- the reference's halo. It lands in
    # the lit layer, so it takes the accent colour and fades with the face.
    glow = np.clip(blur(head_big, 22.0) * 1.25, 0, 1) * (1.0 - head_big) * 0.42

    lit_a = np.clip(skin + sheen * 0.55 + glow, 0, 1)
    lit_rgb = np.clip(lum * (1.0 - sheen) + 0.80 * sheen, 0, 1)

    # ---- downsample + write ----------------------------------------------
    def down(a):
        return img(a).resize((OUT, OUT), Image.LANCZOS)

    here = os.path.dirname(os.path.abspath(__file__))

    white = Image.new("L", (OUT, OUT), 255)
    Image.merge("RGBA", (white, white, white, down(head_big))) \
        .save(os.path.join(here, "dj_face_dark.png"))

    l = down(lit_rgb)
    Image.merge("RGBA", (l, l, l, down(lit_a))) \
        .save(os.path.join(here, "dj_face_lit.png"))

    print("wrote dj_face_dark.png / dj_face_lit.png to", here)


if __name__ == "__main__":
    main()
