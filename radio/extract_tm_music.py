#!/usr/bin/env python3
"""Build the `tm` pool — Tricky Madness' own soundtrack — from an install.

⚠️ **This is a RELEASE-TIME tool, not something a player runs.** The pool it
builds is staged into the pack by package.sh like every other soundtrack, so run
this before packaging a release and check the `tm=` count in package.sh's summary.

It was briefly the other way round — shipped as a script players ran themselves —
which is worth not re-proposing: bundling the decoders it shells out to measured
~108 MB for macOS alone (ffmpeg 57.7 + vgmstream 49.8, libraries included)
against 63 MB for the finished audio, and asking a non-technical audience to
install Python, ffmpeg and vgmstream to hear 17 songs is not a feature.
See RADIO_BIG.md § The `tm` pool.

    python3 extract_tm_music.py                  # auto-locate, default out dir
    python3 extract_tm_music.py --install <dir>  # explicit game dir
    python3 extract_tm_music.py --out <dir> --force

Needs `vgmstream-cli` and `ffmpeg` on PATH. macOS: `brew install vgmstream
ffmpeg`. Windows: `winget install ffmpeg`, plus vgmstream-cli.exe from
vgmstream.org on your PATH.

How it works, and why it isn't a hardcoded table
------------------------------------------------
Tricky Madness ships its Wwise `GeneratedSoundBanks/` with `SoundbanksInfo.xml`
and the per-bank `.txt` intact, so every track is already named and ID'd — there
is no bank format to reverse. We read `Music_Bank.txt` and take the song's
identity from its **Wwise object path**, e.g.

    \\Interactive Music Hierarchy\\...\\Music\\JordanMusic\\01 White Powder\\02 Verse\\...
                                                 ^^^^^^^^^^^^^^^^^ this segment

which gives both the track number and the display title, rather than the media
`Name` field (which is a working title like "[-24LUFS] Back to Life - Cmin
135BPM"). A game update that adds a track is then picked up for free.

⚠️ Audio lives in TWO places and both are needed: seven songs are streamed as
loose `Media/<id>.wem`, the other seven are embedded in `Music_Bank.bnk` as
subsongs. An extractor that only walks `Media/` silently gets half the pool.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

# Every track on the soundtrack is by the same composer, so the artist is a
# constant rather than something recovered per-track. dj_library.parse_song()
# reads it from the LAST parenthetical of the filename.
ARTIST = "Jordan Schor"

# Lobby loops are numbered from here so dj_library can split them off into
# Library.menu_tracks with an explicit range test.
# ⚠️ Do NOT switch that split to a `"menu" in title` heuristic (the way the
# Tricky pool does it): only one of the three loops has "Menu" in its title, so
# Log Cabin and Sunset Slopes would leak into the race shuffle.
MENU_BASE = 90

# Stingers share a song's folder (e.g. a 1-second KSHMR impact under
# "09 Bringin' Tha Noize\SwipeImp"). Nothing marks them as non-music in the
# metadata, so length is the discriminator: real tracks here run 1:44 and up.
MIN_TRACK_SECONDS = 30

_MAC_REL = ("TrickyMadness.app/Contents/Resources/Data/StreamingAssets/"
            "Audio/GeneratedSoundBanks/Mac")
_WIN_REL = ("Tricky Madness_Data/StreamingAssets/Audio/"
            "GeneratedSoundBanks/Windows")

_INSTALL_GUESSES = (
    "~/Library/Application Support/Steam/steamapps/common/Tricky Madness",
    "~/Library/Application Support/CrossOver/Bottles/Steam/drive_c/"
    "Program Files (x86)/Steam/steamapps/common/Tricky Madness",
    "C:/Program Files (x86)/Steam/steamapps/common/Tricky Madness",
    "~/.steam/steam/steamapps/common/Tricky Madness",
)

# Where the plugin keeps its pools, relative to the game dir. Writing straight
# in there is what makes the common case zero-config: dj_library resolves every
# pool as <assets>/<slug>, so an extract into assets/tm is picked up with no
# path to set anywhere.
_ASSETS_REL = os.path.join("BepInEx", "plugins", "RadioBig", "assets")
# Fallback when RadioBig isn't installed yet (running from source, or extracting
# before installing the mod). Mirrors the other rips' dev paths in dj_library.
_FALLBACK_OUT = "~/Downloads/SSX_Audio/tricky_madness/music"


def _tool_hint(missing):
    per_os = {"darwin": "brew install vgmstream ffmpeg",
              "win32": "winget install ffmpeg, and put vgmstream-cli.exe from "
                       "vgmstream.org on your PATH"}
    return (f"not found on PATH: {', '.join(missing)}\n   "
            + per_os.get(sys.platform, "install them with your package manager"))


def _die(msg):
    print(f"!! {msg}", file=sys.stderr)
    sys.exit(1)


def find_bank_dir(install=None):
    """The platform's GeneratedSoundBanks dir. Mac and Windows ship identical
    media — same ids, same Custom Vorbis encoding, same .txt — so only the base
    path differs and one extractor covers both."""
    roots = [install] if install else [os.path.expanduser(p)
                                       for p in _INSTALL_GUESSES]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for rel in (_MAC_REL, _WIN_REL):
            cand = os.path.join(root, rel)
            if os.path.isfile(os.path.join(cand, "Music_Bank.txt")):
                return cand, root
    _die("could not find a Tricky Madness install with Wwise banks.\n"
         "   Pass --install <game dir> (the folder holding TrickyMadness.app "
         "or Tricky Madness_Data).")


def assets_tm_dir(install_root):
    """Where an installed RadioBig would keep this pool, or None if not installed."""
    assets = os.path.join(install_root, _ASSETS_REL)
    if os.path.isdir(os.path.dirname(assets)):   # .../plugins/RadioBig exists
        return os.path.join(assets, "tm")
    return None


def default_out(install_root):
    """assets/tm inside an installed RadioBig, else the standalone fallback.

    Only used when the mod is actually installed — extracting into a RadioBig
    that isn't there would create a directory tree the plugin never reads.
    """
    return assets_tm_dir(install_root) or os.path.expanduser(_FALLBACK_OUT)


def parse_bank_txt(path):
    """Rows of (media_id, name, object_path, streamed) for the music hierarchy.

    Music_Bank.txt is tab-separated with named sections; we want "In Memory
    Audio" (bank subsongs) and "Streamed Audio" (loose .wem). Both carry the
    id in column 1, the name in column 2 and the Wwise object path in the last
    populated column, but they have DIFFERENT column counts — so index from the
    header of the section actually being read rather than assuming a layout.
    """
    rows, section, cols = [], None, {}
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if not line.startswith("\t"):
                # Section header: "In Memory Audio\tID\tName\t..."
                parts = [p.strip() for p in line.split("\t")]
                section = parts[0]
                cols = {name: i for i, name in enumerate(parts) if name}
                continue
            if section not in ("In Memory Audio", "Streamed Audio"):
                continue
            parts = line.split("\t")

            def col(name):
                i = cols.get(name)
                return parts[i].strip() if i is not None and i < len(parts) else ""

            mid, obj = col("ID"), col("Wwise Object Path")
            if not mid.isdigit() or "\\Music\\" not in obj:
                # Ambience and SFX live under the Actor-Mixer Hierarchy, so the
                # Music filter also drops the four non-music loose .wem files.
                continue
            rows.append((int(mid), col("Name"), obj,
                         section == "Streamed Audio"))
    return rows


def song_key(obj_path):
    """The song folder out of a Wwise object path, e.g. '01 White Powder'.

    That is the segment directly after the composer's work-unit folder. Some
    tracks sit under 'JordanMusic' and some under 'JordanMusic_old setup', so
    match either.
    """
    segs = [s for s in obj_path.split("\\") if s]
    for i, seg in enumerate(segs):
        if seg.startswith("JordanMusic") and i + 1 < len(segs):
            return segs[i + 1]
    return None


def vgm_probe(args):
    """`vgmstream-cli -m ...` -> dict of its metadata lines."""
    try:
        out = subprocess.run(["vgmstream-cli", "-m"] + args, check=True,
                             capture_output=True, text=True).stdout
    except FileNotFoundError:
        _die(_tool_hint(["vgmstream-cli"]))
    except subprocess.CalledProcessError as e:
        return {"_error": (e.stderr or "").strip()}
    meta = {}
    for line in out.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def _seconds(meta):
    m = re.search(r"\(([\d:.]+) seconds\)", meta.get("stream total samples", ""))
    if not m:
        return 0.0
    mins, _, secs = m.group(1).rpartition(":")
    return int(mins or 0) * 60 + float(secs)


def bank_subsong_index(bank):
    """media id -> subsong index for Music_Bank.bnk.

    ⚠️ `-s` takes a subsong INDEX, not a media id. vgmstream reports the id as
    the subsong's `stream name`, which is the join — the same one used for the
    PS2/PS3 rips in tricky_mods: ssx/AUDIO_EXTRACTION.md. Derived every run, so
    a game update that reorders the bank can't silently shift every track.
    """
    count = int(vgm_probe([bank]).get("stream count", "1"))
    index = {}
    for i in range(1, count + 1):
        meta = vgm_probe(["-s", str(i), bank])
        name = meta.get("stream name", "")
        if name.isdigit():
            index[int(name)] = (i, _seconds(meta))
    return index


def decode(src_args, dest, quality):
    """vgmstream -> ffmpeg -> mp3, streamed through a pipe (no temp WAV).

    ⚠️ `-i` is load-bearing. Every one of these tracks carries loop points, and
    vgmstream renders the loop by DEFAULT — without -i each track comes out
    played twice with a fade (White Powder decodes 5:58 instead of 2:54).
    Nothing errors; the whole pool is just silently double length.
    """
    vgm = subprocess.Popen(["vgmstream-cli", "-i", "-p"] + src_args,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-b:a", quality, dest],
        stdin=vgm.stdout, stderr=subprocess.PIPE)
    vgm.stdout.close()
    err = ff.communicate()[1]
    vgm.wait()
    if ff.returncode != 0 or not os.path.isfile(dest):
        return (err or b"").decode(errors="replace").strip() or "ffmpeg failed"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install", help="Tricky Madness game directory")
    ap.add_argument("--out", help="output dir (default: assets/tm inside an "
                                  "installed RadioBig, else "
                                  f"{_FALLBACK_OUT})")
    ap.add_argument("--quality", default="192k", help="mp3 bitrate (default 192k)")
    ap.add_argument("--force", action="store_true", help="re-encode existing files")
    ap.add_argument("--dry-run", action="store_true", help="list what would be written")
    args = ap.parse_args()

    # vgmstream is needed even for --dry-run: durations and the subsong join both
    # come from probing. ffmpeg is only needed to actually encode.
    need = ["vgmstream-cli"] if args.dry_run else ["vgmstream-cli", "ffmpeg"]
    missing = [t for t in need if not shutil.which(t)]
    if missing:
        _die(_tool_hint(missing))

    bank_dir, install_root = find_bank_dir(
        os.path.expanduser(args.install) if args.install else None)
    out_dir = (os.path.expanduser(args.out) if args.out
               else default_out(install_root))
    print(f"[tm] banks : {os.path.normpath(bank_dir)}")
    print(f"[tm] output: {os.path.normpath(out_dir)}")

    rows = parse_bank_txt(os.path.join(bank_dir, "Music_Bank.txt"))
    if not rows:
        _die("Music_Bank.txt held no music entries — is this really a TM install?")

    bank_path = os.path.join(bank_dir, "Music_Bank.bnk")
    subsongs = bank_subsong_index(bank_path) if any(not s for *_, s in rows) else {}

    # Resolve every row to a source + duration, dropping stingers by length.
    tracks = {}   # song folder -> best (duration, source args, name)
    skipped = []
    for mid, name, obj, streamed in rows:
        key = song_key(obj)
        if not key:
            continue
        if streamed:
            wem = os.path.join(bank_dir, "Media", f"{mid}.wem")
            if not os.path.isfile(wem):
                skipped.append(f"{key}: Media/{mid}.wem missing")
                continue
            src, dur = [wem], _seconds(vgm_probe([wem]))
        else:
            hit = subsongs.get(mid)
            if not hit:
                skipped.append(f"{key}: id {mid} not in Music_Bank.bnk")
                continue
            idx, dur = hit
            src = ["-s", str(idx), bank_path]
        if dur < MIN_TRACK_SECONDS:
            continue  # stinger, not a track
        prev = tracks.get(key)
        if prev and prev[0] >= dur:
            # A song with two long segments would land here. Take the longest
            # so the pool still gets a usable track, but say so — silently
            # dropping half a song is exactly the failure this pool can't see.
            print(f"!! [tm] {key} has multiple long segments; keeping the "
                  f"{prev[0]:.0f}s one, ignoring {dur:.0f}s")
            continue
        if prev:
            print(f"!! [tm] {key} has multiple long segments; switching to the "
                  f"{dur:.0f}s one, ignoring {prev[0]:.0f}s")
        tracks[key] = (dur, src, name)

    # Number the lobby loops from MENU_BASE, in stable alphabetical order, and
    # keep the songs on their own authored numbers.
    menu_keys = sorted(k for k in tracks if k.lower().startswith("menu"))
    plan = []
    for key, (dur, src, name) in tracks.items():
        if key in menu_keys:
            num = MENU_BASE + menu_keys.index(key)
            # "Menu Log Cabin" -> "Log Cabin"; a bare "Menu" folder has its real
            # title only on the media itself ("Main Menu Music").
            title = key[5:].strip() if len(key) > 4 else name.strip()
        else:
            m = re.match(r"^(\d+)\s+(.*)$", key)
            if not m:
                skipped.append(f"{key}: no track number in the object path")
                continue
            num, title = int(m.group(1)), m.group(2).strip()
        plan.append((num, title, dur, src))
    plan.sort(key=lambda r: r[0])

    if not plan:
        _die("resolved no tracks — the bank layout may have changed.")

    os.makedirs(out_dir, exist_ok=True)
    written = existing = failed = 0
    for num, title, dur, src in plan:
        # Slashes are the only character that can't survive as a filename here;
        # the titles are otherwise plain words.
        safe = title.replace("/", "-").replace(":", "-")
        dest = os.path.join(out_dir, f"{num:02d} - {safe} ({ARTIST}).mp3")
        tag = "menu" if num >= MENU_BASE else "song"
        if args.dry_run:
            print(f"[tm] {tag} {num:02d}  {dur:6.1f}s  {os.path.basename(dest)}")
            continue
        if os.path.isfile(dest) and not args.force:
            existing += 1
            continue
        err = decode(src, dest, args.quality)
        if err:
            failed += 1
            print(f"!! [tm] {title}: {err}", file=sys.stderr)
        else:
            written += 1
            print(f"[tm] {tag} {num:02d}  {dur:6.1f}s  {os.path.basename(dest)}")

    for s in skipped:
        print(f"!! [tm] skipped {s}", file=sys.stderr)

    if args.dry_run:
        print(f"\n[tm] {len(plan)} tracks would be written "
              f"({sum(1 for p in plan if p[0] < MENU_BASE)} songs + "
              f"{sum(1 for p in plan if p[0] >= MENU_BASE)} lobby loops)")
        return 0

    print(f"\n[tm] {written} written, {existing} already present, {failed} failed")
    if existing and not args.force:
        print("[tm] (re-encode them with --force)")
    if not (written or existing):
        return
    installed = assets_tm_dir(install_root)
    if installed and os.path.normcase(os.path.abspath(installed)) == \
            os.path.normcase(os.path.abspath(out_dir)):
        print("\n[tm] that is RadioBig's own assets dir — the player will pick "
              "it up on next launch, nothing to configure.")
    else:
        # `export` is wrong on cmd/PowerShell, and this script is shipped at the
        # pack root for Windows players to run, so give them their own syntax.
        setter = (f"set RADIO_BIG_TM={out_dir}" if sys.platform == "win32"
                  else f"export RADIO_BIG_TM={out_dir}")
        print(f"\n[tm] point the player at it with:\n"
              f"    {setter}\n"
              f"or copy it into <game>{os.sep}{_ASSETS_REL}{os.sep}tm "
              f"for zero config.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
