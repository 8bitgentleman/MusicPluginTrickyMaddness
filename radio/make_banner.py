#!/usr/bin/env python3
"""Render the Radio Big release banner (the image that goes with the Discord post).

    python3 make_banner.py                     # 1280x720, installed pools, game-art plate
    python3 make_banner.py --size 1920x1080
    python3 make_banner.py --plate designed    # no game art, procedural night plate

Sibling of `tricky_mods/CharacterHook-src/make_banner.py` and deliberately built on
the same rule: the banner is driven by what is actually INSTALLED, so it cannot
advertise something the player will not get. There the roster came from rider
folders; here the soundtrack cards, the track counts, the song total and the DJ
clip count all come from `plugins/RadioBig/assets/`. Next release says the new
number without anyone editing this file.

⚠️ The drawing helpers below are COPIED from that script, not imported. Radio Big
is its own repo and ships standalone (source/ goes inside the release zip), so an
import across repos would make the banner unbuildable from the zip. Port fixes by
hand, in both directions.

⚠️ Pool order is fixed chronological (Tricky -> 3 -> On Tour -> 2012), NOT the
filesystem's — the four covers read as a timeline of the games. A pool that isn't
installed is dropped from the strip entirely, matching the player, whose library
treats a missing pool as "not installed" and reweights the DJ over what loaded.

⚠️ The covers are third-party publisher art and are NOT in git — same stance as the
audio (see .gitignore). `--covers` defaults to `banner_covers/` beside this file;
if it is empty the script prints the exact fetch commands and exits.

Deps: Pillow + numpy (`pip3 install pillow numpy`). Display type is Arial Black from
the macOS system fonts — Tricky Madness' own typeface is not distributable, so this
is a lookalike, not the real thing.
"""
import argparse, io, os, re, sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GAME = os.path.expanduser("~/Library/Application Support/Steam/steamapps/common/Tricky Madness")
ASSETS = os.environ.get("RADIO_BIG_ASSETS") or os.path.join(GAME, "BepInEx/plugins/RadioBig/assets")
MAPS = os.path.join(GAME, "Maps")
COVERS = os.path.join(HERE, "banner_covers")

# Where the finished PNG goes. `Discord Releases/` lives in the tricky_mods repo
# beside every other mod's pack and banner, and is gitignored there.
DROP = os.path.expanduser("~/Downloads/claude_scratch/tricky_mods/Discord Releases")

# The plate. Any Maps/*.png works (they are all real 1024x576 game art). SSX 3's Metro
# City is picked because it is a genuine lit-windows night shot: the covers sit on dark
# blue instead of the grey daylight every other course thumbnail gives you, and it is
# nothing like the ice the CharacterHook banner uses, so the two mods' posts don't read
# as the same poster twice. Merqury City Meltdown is the obvious guess and the wrong
# one — despite the name it is a pale daytime shot the veil flattens to nothing.
# `--plate designed` is the equivalent look with no game install needed.
DEFAULT_PLATE = os.path.join(MAPS, "SSX3 - Peak 1 Metro-City.png")

BLACK_F = "/System/Library/Fonts/Supplemental/Arial Black.ttf"

INK = (10, 41, 82)        # logo outline / TM-ish deep blue
INK_D = (6, 20, 44)       # hard drop shadow
GOLD = [(255, 226, 138), (255, 178, 0), (255, 132, 20)]
NIGHT = [(74, 40, 120), (36, 26, 86), (14, 18, 52), (7, 10, 30)]

# Asset-folder slug -> (cover file stem, how the card names the game). The ORDER of
# this tuple is the order of the strip; `dj` is not here because it is not a
# soundtrack — it is counted into the subline instead.
POOLS = (
    ("tricky",  "tricky",  "SSX TRICKY"),
    ("ssx3",    "ssx3",    "SSX 3"),
    ("sxot",    "sxot",    "SSX ON TOUR"),
    ("ssx2012", "ssx2012", "SSX 2012"),
)
DJ_POOL = "dj"
COVER_EXT = (".png", ".jpg", ".jpeg", ".webp")

FETCH_HELP = """no covers found in %s

They are publisher art and are deliberately not committed. Fetch them once:

  mkdir -p %s
  curl -sL -o %s/tricky.jpg  https://upload.wikimedia.org/wikipedia/en/6/6a/SSX_Tricky.jpg
  curl -sL -o %s/ssx3.png    https://upload.wikimedia.org/wikipedia/en/4/43/SSX_3_Coverart.png
  curl -sL -o %s/sxot.jpg    https://upload.wikimedia.org/wikipedia/en/d/d6/SSX_on_Tour.jpg
  curl -sL -o %s/ssx2012.jpg https://upload.wikimedia.org/wikipedia/en/b/b1/SSX2012VIDEOGAME.jpg

or point --covers at your own files, named <slug>.<png|jpg>."""


# ---------------------------------------------------------------- content

def audio_count(folder):
    """Playable files in one pool folder. Extension list matches dj_library.py."""
    return sum(1 for f in os.listdir(folder)
               if not f.startswith(".") and f.lower().endswith((".mp3", ".ogg", ".wav", ".flac")))


def pools(assets=ASSETS, covers=COVERS):
    """Installed soundtracks (chronological) + the DJ clip count. Refuses before rendering."""
    if not os.path.isdir(assets):
        sys.exit("no asset pools at %s — is Radio Big installed? (or set RADIO_BIG_ASSETS)"
                 % assets)
    found, missing = [], []
    for slug, stem, label in POOLS:
        folder = os.path.join(assets, slug)
        if not os.path.isdir(folder):
            print("  skip %s (not installed)" % slug, file=sys.stderr)
            continue
        n = audio_count(folder)
        if not n:
            print("  skip %s (installed but empty)" % slug, file=sys.stderr)
            continue
        art = next((p for e in COVER_EXT
                    for p in [os.path.join(covers, stem + e)] if os.path.isfile(p)), None)
        if art is None:
            missing.append("%s (%s/%s.%s)" % (label, covers, stem, "|".join(e[1:] for e in COVER_EXT)))
            continue
        found.append({"slug": slug, "label": label, "tracks": n, "cover": art})
    if missing:
        # Same stance as the CharacterHook banner's portraits: refuse rather than
        # quietly render a short strip, because a gap is harder to spot than an error.
        sys.exit("installed pools with no cover art, refusing to render:\n  "
                 + "\n  ".join(missing))
    if not found:
        sys.exit("no soundtrack pools found under %s" % assets)

    dj_dir = os.path.join(assets, DJ_POOL)
    dj = audio_count(dj_dir) if os.path.isdir(dj_dir) else 0
    if not dj:
        # The DJ is the mod. A pack without him is a shuffle button, so say so loudly
        # rather than printing "0 DJ CLIPS" on a banner.
        print("warning: no DJ clips under %s — the subline will not mention the DJ"
              % dj_dir, file=sys.stderr)
    return found, dj


def plugin_version():
    """Version out of RadioBig.cs, cross-checked against radio_server.py.

    The two are separately declared and RadioBig.cs' own comment says to keep them in
    sync; a banner is exactly where a drifted pair would get published, so it refuses.
    """
    cs = os.path.join(HERE, "RadioBigPlugin", "RadioBig.cs")
    py = os.path.join(HERE, "radio_server.py")
    m = re.search(r'\[BepInPlugin\("[^"]+",\s*"[^"]+",\s*"([^"]+)"\)\]',
                  io.open(cs, encoding="utf-8").read())
    if not m:
        sys.exit("could not read the BepInPlugin version from %s" % cs)
    n = re.search(r'^VERSION\s*=\s*"([^"]+)"', io.open(py, encoding="utf-8").read(), re.M)
    if n and n.group(1) != m.group(1):
        sys.exit("version drift: RadioBig.cs says %s, radio_server.py says %s — fix one"
                 % (m.group(1), n.group(1)))
    return m.group(1)


# ---------------------------------------------------------------- drawing
# (copied from CharacterHook-src/make_banner.py — see the module docstring)

def vgrad(size, stops):
    """Vertical gradient from evenly spaced RGB stops."""
    w, h = size
    pos = np.linspace(0, 1, len(stops))
    t = np.linspace(0, 1, h)
    cols = np.stack([np.interp(t, pos, [s[i] for s in stops]) for i in range(3)], -1)
    return Image.fromarray(np.repeat(cols[:, None, :], w, 1).astype(np.uint8))


def word(text, px, fill, stroke_w, shear=0.16, grad=None):
    """Outlined display word on a transparent layer, sheared into italic."""
    font = ImageFont.truetype(BLACK_F, px)
    pad = stroke_w * 2 + 26
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    x0, y0, x1, y1 = probe.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    W, H = x1 - x0 + pad * 2, y1 - y0 + pad * 2
    org = (pad - x0, pad - y0)

    sil = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sil).text(org, text, font=font, fill=255,
                             stroke_width=stroke_w, stroke_fill=255)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for dy, a in ((14, 150), (9, 255)):                      # soft then hard shadow
        sh = Image.new("RGBA", (W, H), INK_D + (0,))
        sh.putalpha(sil.point(lambda v, a=a: v * a // 255))
        if dy == 14:
            sh = sh.filter(ImageFilter.GaussianBlur(7))
        layer.alpha_composite(sh, (0, dy))
    stroke = Image.new("RGBA", (W, H), INK + (0,))
    stroke.putalpha(sil)
    layer.alpha_composite(stroke)

    face = Image.new("L", (W, H), 0)
    ImageDraw.Draw(face).text(org, text, font=font, fill=255)
    body = (vgrad((W, H), grad).convert("RGBA") if grad
            else Image.new("RGBA", (W, H), fill + (255,)))
    body.putalpha(face)
    layer.alpha_composite(body)

    return layer.transform((W + int(shear * H), H), Image.AFFINE,
                           (1, shear, -shear * H, 0, 1, 0), resample=Image.BICUBIC)


def fit_px(text, target_w, stroke_w, start=160):
    """Font size at which `text` renders `target_w` wide (incl. stroke)."""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    px = start
    for _ in range(40):
        f = ImageFont.truetype(BLACK_F, px)
        x0, _, x1, _ = probe.textbbox((0, 0), text, font=f, stroke_width=stroke_w)
        w = x1 - x0
        if abs(w - target_w) <= 2:
            break
        px = max(10, round(px * target_w / max(w, 1)))
    return px


def fit_track_px(draw, text, px, track, maxw, font_path=BLACK_F):
    """Largest size <= px at which `text` fits `maxw` including letter-spacing.

    Split out of plain() so the layout can MEASURE a line before drawing it and get
    the same answer — a second copy of this loop would drift the moment one is tuned.
    """
    while maxw and px > 8:
        font = ImageFont.truetype(font_path, px)
        if draw.textlength(text, font=font) + px * track * (len(text) - 1) <= maxw:
            break
        px -= 1
    return px


def ink_v(draw, text, px, y, track=0.0, font_path=BLACK_F):
    """(top, bottom) of the ink plain() would lay down centered on `y`."""
    font = ImageFont.truetype(font_path, px)
    _, y0, _, y1 = draw.textbbox((0, y), text, font=font, anchor="lm" if track else "mm")
    return y0, y1


def word_ink(text, px, stroke_w):
    """(top, bottom) of the glyph+stroke ink INSIDE the layer word() returns.

    Not the layer's own bounds: word() adds `pad` all round and a drop shadow that
    hangs below the letters, so centering the bitmap sits the lockup visibly low.
    """
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    font = ImageFont.truetype(BLACK_F, px)
    pad = stroke_w * 2 + 26
    _, y0, _, y1 = probe.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    return pad, pad + (y1 - y0)


def plain(draw, xy, text, px, fill, track=0.0, font_path=BLACK_F, anchor="mm", maxw=None):
    """Centered text with optional letter-spacing, shrunk to fit maxw."""
    px = fit_track_px(draw, text, px, track, maxw, font_path)
    font = ImageFont.truetype(font_path, px)
    if not track:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)
        return
    gap = px * track
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + gap * (len(text) - 1)
    x = xy[0] - total / 2
    for c, w in zip(text, widths):
        draw.text((x, xy[1]), c, font=font, fill=fill, anchor="lm")
        x += w + gap


# ---------------------------------------------------------------- plates

def designed_plate(size):
    """Procedural night-city plate: skyline, window lights, a broadcast glow."""
    w, h = size
    img = vgrad(size, NIGHT).convert("RGBA")
    rng = np.random.default_rng(11)

    # broadcast glow behind where the lockup lands
    yy, xx = np.mgrid[0:h, 0:w]
    g = np.exp(-((((xx - w * 0.5) / (w * 0.42)) ** 2) + (((yy - h * 0.24) / (h * 0.30)) ** 2)))
    halo = Image.new("RGBA", size, (255, 168, 64, 0))
    halo.putalpha(Image.fromarray((g * 92).astype(np.uint8)))
    img.alpha_composite(halo)

    # three skyline bands, near-to-far reversed: far ones are lighter and hazier
    for band, (body, base, hmin, hmax, wmin, wmax, lit) in enumerate((
        ((30, 34, 74), 0.86, 0.10, 0.30, 0.022, 0.055, 30),
        ((18, 20, 52), 0.92, 0.08, 0.24, 0.028, 0.062, 55),
        ((8, 9, 28),   1.00, 0.06, 0.20, 0.034, 0.075, 80),
    )):
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        x = -w * 0.05
        while x < w:
            bw = rng.uniform(wmin, wmax) * w
            bh = rng.uniform(hmin, hmax) * h
            top = h * base - bh
            d.rectangle((x, top, x + bw, h), fill=body + (255,))
            # window grid — the only thing that says "city" rather than "bar chart"
            cols = max(1, int(bw / (w * 0.011)))
            rows = max(1, int(bh / (h * 0.030)))
            for cx in range(cols):
                for cy in range(rows):
                    if rng.random() > 0.42:
                        continue
                    wx = x + (cx + 0.30) * bw / cols
                    wy = top + (cy + 0.30) * bh / rows
                    d.rectangle((wx, wy, wx + bw / cols * 0.40, wy + bh / rows * 0.36),
                                fill=(255, 214, 140, lit + int(rng.uniform(0, 70))))
            x += bw + rng.uniform(0.004, 0.014) * w
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.6 * (2 - band))))

    # falling snow, lit from below by the city
    flakes = Image.new("RGBA", size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(flakes)
    for _ in range(190):
        fx, fy = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.uniform(0.8, 2.8) * (w / 1280)
        fd.ellipse((fx - r, fy - r, fx + r, fy + r),
                   fill=(255, 246, 228, int(rng.uniform(30, 130))))
    img.alpha_composite(flakes.filter(ImageFilter.GaussianBlur(0.6)))
    return img


def photo_plate(size, path):
    """Cover-fit a game screenshot/thumbnail and blur it back into a backdrop."""
    if not os.path.isfile(path):
        sys.exit("no plate image at %s (try --plate designed)" % path)
    src = Image.open(path).convert("RGB")
    sw, sh = src.size
    scale = max(size[0] / sw, size[1] / sh)
    src = src.resize((round(sw * scale), round(sh * scale)), Image.LANCZOS)
    left, top = (src.width - size[0]) // 2, (src.height - size[1]) // 2
    src = src.crop((left, top, left + size[0], top + size[1]))
    return src.filter(ImageFilter.GaussianBlur(4)).convert("RGBA")


# ---------------------------------------------------------------- cover strip

BAND_TOP = 0.545          # where the covers start, as a fraction of height
KICKER_Y = 0.043          # kicker centre; the lockup is centred between these two
SUB_Y = 0.445             # first subline centre


def cover_strip(size, items, top_frac=BAND_TOP):
    """The four covers in a row, each captioned with its own track count.

    ⚠️ Cell size is derived from len(items), not fixed — a fifth soundtrack should
    make the covers narrower, never push one off the frame.
    """
    w, h = size
    s = w / 1280.0
    n = len(items)
    gap = round(30 * s)
    ch = round(h * 0.315)                               # cover height
    cw = min(round(ch * 0.783),                         # PS2-case-ish aspect
             int((w * 0.90 - (n - 1) * gap) / max(n, 1)))
    ch = round(cw / 0.783)

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pad = round(26 * s)
    shade = Image.new("RGBA", (cw + pad * 2, ch + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle((pad, pad + round(8 * s), pad + cw, pad + ch + round(8 * s)),
                                    fill=(0, 0, 0, 165))
    shade = shade.filter(ImageFilter.GaussianBlur(11 * s))

    y = round(h * top_frac)
    x0 = (w - (n * cw + (n - 1) * gap)) / 2
    for i, it in enumerate(items):
        src = Image.open(it["cover"]).convert("RGBA")
        sw, sh = src.size
        sc = max(cw / sw, ch / sh)                      # cover-fit, never letterbox
        src = src.resize((round(sw * sc), round(sh * sc)), Image.LANCZOS)
        src = src.crop(((src.width - cw) // 2, (src.height - ch) // 2,
                        (src.width - cw) // 2 + cw, (src.height - ch) // 2 + ch))
        x = round(x0 + i * (cw + gap))
        layer.alpha_composite(shade, (x - pad, y - pad))
        layer.alpha_composite(src, (x, y))
        d.rectangle((x, y, x + cw - 1, y + ch - 1), outline=(236, 244, 255, 190),
                    width=max(1, round(2 * s)))
        cx = x + cw / 2
        plain(d, (cx, y + ch + round(24 * s)), it["label"], round(19 * s),
              (255, 255, 255), track=0.12, maxw=cw + gap * 0.8)
        plain(d, (cx, y + ch + round(48 * s)), "%d TRACKS" % it["tracks"], round(16 * s),
              (255, 196, 74), track=0.10, maxw=cw + gap * 0.8)
    return layer


def band_veil(size, top_frac=BAND_TOP):
    """Darken behind the strip + a top scrim, so the plate stays visible between."""
    w, h = size
    yy = np.mgrid[0:h, 0:w][0]
    band = np.clip((yy - h * (top_frac - 0.14)) / (h * 0.16), 0, 1) ** 1.2 * 200
    top = np.clip((h * 0.30 - yy) / (h * 0.30), 0, 1) ** 1.6 * 120
    mid = np.exp(-(((yy - h * 0.26) / (h * 0.17)) ** 2)) * 84        # pool behind the logo
    a = np.clip(band + top + mid, 0, 240).astype(np.uint8)
    v = Image.new("RGBA", size, (4, 8, 22, 0))
    v.putalpha(Image.fromarray(a))
    return v


# ---------------------------------------------------------------- compose

def build(items, plate, size, *, kicker, line1, line2, subline, subline2, version):
    w, h = size
    s = w / 1280.0                                  # every offset below is authored at 1280x720
    img = designed_plate(size) if plate == "designed" else photo_plate(size, plate)

    img.alpha_composite(band_veil(size))
    img.alpha_composite(cover_strip(size, items))

    cx = w / 2
    d = ImageDraw.Draw(img)

    # The kicker and the subline are the FIXED anchors; the RADIO/BIG lockup is then
    # centered in the gap between them. Authoring it the other way round (lockup at a
    # fixed y, sublines hung off it) is what left 69px of air above the logo and 31
    # below at 720p — the offsets were tuned for CHARACTER/MOD, whose two words have
    # different heights to these.
    ky = h * KICKER_Y
    sy = h * (SUB_Y if subline2 else SUB_Y + 0.023)
    kpx = fit_track_px(d, kicker, round(24 * s), 0.34, w * 0.80)
    spx = fit_track_px(d, subline, round(28 * s), 0.15, w * 0.88)
    kick_bot = ink_v(d, kicker, kpx, ky, track=0.34)[1]
    sub_top = ink_v(d, subline, spx, sy, track=0.15)[0]

    sw1, sw2 = round(9 * s), round(10 * s)
    px1 = round(96 * s)
    w1 = word(line1, px1, (255, 255, 255), sw1)
    # ⚠️ line 2 rides at a FIXED height ratio and is only shrunk if it would out-run
    # line 1. Matching its width to line 1 instead makes a short word ("BIG") tall
    # enough to crash into the cover strip.
    px2 = min(round(150 * s), fit_px(line2, w1.width - round(24 * s), sw2))
    w2 = word(line2, px2, None, sw2, grad=GOLD)

    dy = round(82 * s)                              # line 2's drop below line 1
    t1 = word_ink(line1, px1, sw1)[0]
    b2 = word_ink(line2, px2, sw2)[1]
    top = round((kick_bot + sub_top - t1 - (dy + b2)) / 2)
    img.alpha_composite(w1, (round(cx - w1.width / 2), top))
    img.alpha_composite(w2, (round(cx - w2.width / 2), top + dy))

    plain(d, (cx, ky), kicker, kpx, (255, 214, 150), track=0.34, maxw=w * 0.80)
    plain(d, (cx, sy), subline, spx, (255, 255, 255), track=0.15, maxw=w * 0.88)
    if subline2:
        plain(d, (cx, sy + 33 * s), subline2, round(19 * s), (188, 206, 248),
              track=0.20, maxw=w * 0.84)
    small = ImageFont.truetype(BLACK_F, round(17 * s))
    d.text((30 * s, h - 26 * s), "v" + version, font=small, fill=(158, 176, 226), anchor="lm")
    return img.convert("RGB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", nargs="?", help="defaults to the version in RadioBig.cs")
    ap.add_argument("--plate", default=DEFAULT_PLATE,
                    help="'designed' for the procedural night plate, or a path to any "
                         "image (Maps/*.png are real game art)")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--assets", default=ASSETS,
                    help="pool folders to read counts from; point it at an extracted "
                         "pack to render a banner for a build you did not install")
    ap.add_argument("--covers", default=COVERS, help="folder of <slug>.png|jpg box art")
    ap.add_argument("-o", "--out", help="defaults into 'Discord Releases/' beside the packs")
    ap.add_argument("--kicker", default="FOR TRICKY MADNESS")
    ap.add_argument("--line1", default="RADIO")
    ap.add_argument("--line2", default="BIG")
    ap.add_argument("--subline", help="defaults to the song + Atomika-clip totals")
    # ⚠️ Keep this TRUE of every pool, not just SSX 3. The DJ only names the artist when
    # the next track is an SSX 3 song with a dedicated Atomika intro (radio/README.md),
    # so a line promising that outright over-sells three of the four covers below it.
    ap.add_argument("--subline2", default="STATION IDS, BANTER AND ARTIST INTROS BETWEEN TRACKS",
                    help="pass '' to drop the second line")
    a = ap.parse_args()

    if not os.path.isfile(BLACK_F):
        sys.exit("display font missing: %s" % BLACK_F)
    if not os.path.isdir(a.covers) or not any(f.lower().endswith(COVER_EXT)
                                              for f in os.listdir(a.covers)):
        sys.exit(FETCH_HELP % ((a.covers,) * 6))
    W, H = (int(v) for v in a.size.lower().split("x"))

    version = a.version or plugin_version()
    items, dj = pools(a.assets, a.covers)
    songs = sum(i["tracks"] for i in items)
    # Name Atomika — he is SSX's own DJ and the reason this is a radio station rather
    # than a shuffle button. The `if dj` branch exists because a pack with no voice
    # clips must not claim him.
    subline = a.subline or ("%d SONGS, %d DJ ATOMIKA CLIPS, NEVER THE SAME TWICE"
                            % (songs, dj) if dj else
                            "%d SONGS, NEVER THE SAME TWICE" % songs)

    out = a.out or os.path.join(
        DROP, "Radio Big v%s - Tricky Madness Mod %dx%d.png" % (version, W, H))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    build(items, a.plate, (W, H), kicker=a.kicker, line1=a.line1, line2=a.line2,
          subline=subline, subline2=a.subline2, version=version).save(out)
    print("%d soundtracks / %d songs / %d DJ clips -> %s" % (len(items), songs, dj, out))


if __name__ == "__main__":
    main()
