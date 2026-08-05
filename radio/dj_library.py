#!/usr/bin/env python3
"""Radio Big asset library + artist-aware song<->DJ-intro matching.

Two pools on disk:
  * DJ voice clips -> RADIO dir, categorised by a filename prefix
    (MusicIntroductions, BigMountainLocalNews, RiderBackstories, ...).
  * Music tracks   -> the SSX 3, SSX Tricky, SSX On Tour and SSX (2012)
    soundtrack rips.

The one bit of "smarter than random": ~28 of the 35 SSX3 songs have a dedicated
Atomika intro that names the artist ("...up next, Placebo"). We parse the artist
out of both filenames and match them so the DJ can actually introduce the track
that's about to play. Tricky tracks are instrumental and predate this DJ, so they
get no artist intro (generic music-bed intros only).

On Tour has no DJ of its own — it dropped Atomika's station for a plain shuffle —
so its 41 licensed tracks ride under the generic intros the same way Tricky's do.
One match falls out for free: Queens Of The Stone Age are on BOTH soundtracks, so
On Tour's "Medication" resolves to the real Atomika intro naming them. That is a
true match rather than a collision to defend against, and it is why On Tour goes
through the same artist parse as SSX3 instead of being pinned to artist_id=None.

SSX (2012) is the same story a decade later: it has its own in-game DJ, not
Atomika, so its 36 licensed tracks also ride the generic intros — and it goes
through the artist parse for the same reason On Tour does, in case a name ever
lines up. Its filenames come out of `MBSI`, the disc's own song table, so they
already carry real artists rather than the stream ids the bank is keyed by.

Pure stdlib, no third-party deps — this module is import-safe with no audio.
"""
import os
import re
import sys
import glob

MUSIC_EXTS = (".mp3", ".ogg", ".wav", ".m4a")


# --- asset locations ------------------------------------------------------
# Five audio pools: the Radio Big DJ voice clips, and the four soundtracks.
# Resolved at import so the same code runs from source (the author's machine)
# AND as a frozen, shipped bundle. Precedence:
#   1. RADIO_BIG_ASSETS  -> <dir>/{dj,ssx3,tricky,sxot,ssx2012}   (the shipped
#      layout; the plugin sets this when it auto-launches the frozen player)
#   2. per-pool overrides RADIO_BIG_{DJ,SSX3,TRICKY,SXOT,SSX2012}
#   3. an `assets/` folder beside a PyInstaller-frozen executable
#   4. the original dev paths (running from source, unfrozen)
#
# ⚠️ A missing pool is NOT an error — On Tour and SSX 2012 both ship as optional
# extras (each needs a disc the player may not own), and an install without them
# must degrade to what is there rather than break. The bags in dj_brain
# renormalise over whichever sources actually loaded.
_DEV_DJ = "/Users/mtvogel/Downloads/claude_scratch/Radio_Big/Radio_Big_Sections"
_DEV_SSX3 = "/Users/mtvogel/Documents/PythonScripts/youtube-dl/SSX 3 [Soundtrack⧸Gamerip]"
_DEV_TRICKY = "/Users/mtvogel/Documents/PythonScripts/youtube-dl/SSX Tricky (Complete Soundtrack OST)"
# On Tour comes off the user's own UMD via ssx/audio_rip_music.py in the
# tricky_mods repo, so its dev path is that ripper's default output.
_DEV_SXOT = os.path.expanduser("~/Downloads/SSX_Audio/ssx_on_tour/music")
# SSX (2012) comes off the user's own PS3 dump via the same ripper, which names
# the files from the disc's MBSI table (tricky_mods: ssx/ssx2012_musicbox.py).
_DEV_SSX2012 = os.path.expanduser("~/Downloads/SSX_Audio/ssx2012/music")


def _resolve_assets():
    base = os.environ.get("RADIO_BIG_ASSETS")
    if not base and getattr(sys, "frozen", False):
        # Frozen: look for assets/ relative to the executable. The shipped layout
        # is RadioBig/players/<os>/RadioBigPlayer(.exe) with assets at
        # RadioBig/assets — i.e. TWO levels up from the exe dir. We also probe
        # next-to-exe and one-up for the legacy flat layout. This position-based
        # search is what makes the player self-locating when RADIO_BIG_ASSETS
        # doesn't reach the child (env vars don't reliably propagate to a
        # wine-spawned process — the CrossOver "muted but silent" bug).
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        up1 = os.path.dirname(exe_dir)
        up2 = os.path.dirname(up1)
        for cand in (os.path.join(exe_dir, "assets"),
                     os.path.join(up1, "assets"),
                     os.path.join(up2, "assets")):
            if os.path.isdir(cand):
                base = cand
                break
    dj = os.environ.get("RADIO_BIG_DJ") or (
        os.path.join(base, "dj") if base else _DEV_DJ)
    ssx3 = os.environ.get("RADIO_BIG_SSX3") or (
        os.path.join(base, "ssx3") if base else _DEV_SSX3)
    tricky = os.environ.get("RADIO_BIG_TRICKY") or (
        os.path.join(base, "tricky") if base else _DEV_TRICKY)
    sxot = os.environ.get("RADIO_BIG_SXOT") or (
        os.path.join(base, "sxot") if base else _DEV_SXOT)
    ssx2012 = os.environ.get("RADIO_BIG_SSX2012") or (
        os.path.join(base, "ssx2012") if base else _DEV_SSX2012)
    return dj, ssx3, tricky, sxot, ssx2012


RADIO, SSX3, TRICKY, SXOT, SSX2012 = _resolve_assets()


def _log_asset_diag():
    """Print where the player resolved its audio and how much it found. This is
    the single most useful line when the radio is silent: an empty count means
    the library never loaded (bad/missing assets path) — the DJ then draws None
    and every broadcast exits before it can log a track."""
    src = os.environ.get("RADIO_BIG_ASSETS") or ("(frozen search)"
          if getattr(sys, "frozen", False) else "(dev paths)")
    print(f"[library] RADIO_BIG_ASSETS={src}", flush=True)
    # `optional` marks pools whose absence is a legitimate install, so a missing
    # dir there reads as "not installed" instead of sending someone hunting for
    # a broken assets path.
    for label, d, optional in (("dj", RADIO, False), ("ssx3", SSX3, False),
                               ("tricky", TRICKY, False), ("sxot", SXOT, True),
                               ("ssx2012", SSX2012, True)):
        n = len(glob.glob(os.path.join(d, "*.mp3"))) if os.path.isdir(d) else -1
        state = f"{n} mp3" if n >= 0 else ("not installed" if optional
                                           else "MISSING DIR")
        print(f"[library]   {label:7} -> {d}  [{state}]", flush=True)


_log_asset_diag()


# --- DJ voice clips -------------------------------------------------------
def _clip_category(fname):
    """The prefix before the first underscore, minus the leading NNN_ index.
    e.g. '295_MusicIntroductions_Placebo-...' -> 'MusicIntroductions'."""
    m = re.match(r"^\d+_([A-Za-z0-9-]+?)_", fname)
    return m.group(1) if m else None


def load_clips():
    """category -> [absolute paths], for every DJ clip in RADIO."""
    bags = {}
    for p in sorted(glob.glob(os.path.join(RADIO, "*.mp3"))):
        cat = _clip_category(os.path.basename(p))
        if cat:
            bags.setdefault(cat, []).append(p)
    return bags


# --- artist matching ------------------------------------------------------
# Ordered most-specific-first: a clip is assigned to the FIRST artist whose token
# appears after 'MusicIntroductions_'. RHCP-vs-Executioners must beat the bare
# X-Ecutioners entry, hence the ordering. Aliases live here, not in a fuzzy match.
INTRO_ARTISTS = [
    ("rhcp_executioners", ["Chili-Peppers-Executioners", "Red-Hot-Chili-Peppers-Executioners"]),
    ("executioners",      ["Executioners"]),
    ("alpinestars",       ["Alpine-Stars"]),
    ("andy_hunter",       ["Andy-Hunter"]),
    ("aphrodite",         ["Aphrodite"]),
    ("audio_bullys",      ["Audio-Bullies"]),
    ("autopilot_off",     ["Autopilot-Off"]),
    ("basement_jaxx",     ["Basement-Jaxx"]),
    ("black_eyed_peas",   ["Black-Eyed-Peas"]),
    ("caesars",           ["Caesars"]),
    ("chemical_brothers", ["Chemical-Brothers"]),
    ("dan_automator",     ["Dan-the-Automator"]),
    ("deepsky",           ["Deep-Sky"]),
    ("dilated_peoples",   ["Dilated-Peoples"]),
    ("fatboy_slim",       ["Fatboy-Slim"]),
    ("felix_housecat",    ["Felix-the-Housecat"]),
    ("finger_eleven",     ["Finger-11"]),
    ("fischerspooner",    ["Fischerspooner"]),
    ("ima_robot",         ["I-Am-Robot"]),
    ("janes_addiction",   ["Janes-Addiction"]),
    ("john_morgan",       ["Johnny-Morgan", "Lil-Johnny-Morgan", "Little-Johnny-Morgan"]),
    ("kos",               ["Chaos"]),
    ("kinky",             ["Kinky"]),
    ("nerd",              ["NERD"]),
    ("overseer",          ["Overseer"]),
    ("placebo",           ["Placebo"]),
    ("queens_stone_age",  ["Queens-of-the-Stone-Age"]),
    ("swollen_members",   ["Swollen-Members"]),
    ("thrice",            ["Thrice"]),
    ("yellowcard",        ["Yellowcard"]),
]

# SSX3 song artist (as it appears in the "(...)" of the rip filename, normalised
# to lowercase-alnum) -> the canonical artist id above.
SONG_ARTIST = {
    "alpinestars": "alpinestars",
    "andyhunter": "andy_hunter",
    "aphrodite": "aphrodite",
    "audiobullys": "audio_bullys",
    "autopilotoff": "autopilot_off",
    "basementjaxx": "basement_jaxx",
    "blackeyedpeas": "black_eyed_peas",
    "caesars": "caesars",
    "thechemicalbrothers": "chemical_brothers",
    "dantheautomatorfeatqbert": "dan_automator",
    "deepsky": "deepsky",
    "dilatedpeoples": "dilated_peoples",
    # the faint (Glass Danse) -> no dedicated intro
    "fatboyslim": "fatboy_slim",
    "felixdahousecat": "felix_housecat",
    "fingereleven": "finger_eleven",
    "fischerspooner": "fischerspooner",
    "imarobot": "ima_robot",
    "janesaddiction": "janes_addiction",
    "johnmorgan": "john_morgan",
    "kos": "kos",
    "kinky": "kinky",
    # mxpx (Play it Loud) -> no dedicated intro
    "nerd": "nerd",
    "overseer": "overseer",
    "placebo": "placebo",
    # powerplant (Avalanche) -> no dedicated intro
    "queensofthestoneage": "queens_stone_age",
    "redhotchilipeppersvsxecutioners": "rhcp_executioners",
    # royksopp (Poor Leno) -> no dedicated intro
    "swollenmembers": "swollen_members",
    "thrice": "thrice",
    "xecutionersfeatanikkecoleman": "executioners",
    "yellowcard": "yellowcard",
}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def intro_artist_of(fname):
    """Which canonical artist (if any) a MusicIntroductions clip belongs to."""
    tail = re.sub(r"^\d+_MusicIntroductions_", "", fname)
    for artist_id, tokens in INTRO_ARTISTS:
        for tok in tokens:
            if tail.startswith(tok):
                return artist_id
    return None  # generic "here's some tunes" intro


def parse_song(path):
    """(track_num, title, artist_id_or_None) from a soundtrack filename."""
    fname = os.path.basename(path)
    num = None
    m = re.match(r"^(\d+)\s*-\s*", fname)
    if m:
        num = int(m.group(1))
    # Drop the extension, then the SSX3-specific " - SSX 3 [Soundtrack]" tail
    # (NOT a bare "SSX" — Tricky filenames carry "SSX Tricky" mid-title). The
    # artist is then the LAST parenthetical (some titles have a decoy first one,
    # e.g. Labor Day "(It's a Holiday) (Black Eyed Peas)"). Tolerate a missing
    # close paren — the Higher Ground rip is literally unclosed.
    base = re.sub(r"\.(mp3|ogg|wav|m4a)$", "", fname, flags=re.I)
    base = re.sub(r"\s*-\s*SSX\s*3\s*\[Soundtrack\]\s*$", "", base, flags=re.I)
    artist_id = None
    parens = re.findall(r"\(([^()]+)\)?", base)
    if parens:
        artist_id = SONG_ARTIST.get(_norm(parens[-1]))
    title = re.sub(r"^\d+\s*-\s*", "", base)
    title = re.sub(r"\s*\([^()]*\)?\s*$", "", title).strip()
    return num, title, artist_id


def _list_music(d):
    if not os.path.isdir(d):
        return []
    return sorted(
        os.path.join(d, f) for f in os.listdir(d)
        if f.lower().endswith(MUSIC_EXTS)
    )


ALL_SOURCES = ("ssx3", "tricky", "sxot", "ssx2012")


class Library:
    """Everything the DJ brain needs to know about the assets on disk.

    `sources` is the set of soundtracks the user left switched on (see the
    plugin's [Sources] config section).  None means "everything installed".
    Filtering happens HERE rather than in DJBrain because the brain already
    builds its shuffle bags and renormalises its weights from whatever the
    library actually handed it — so a source dropped here disappears cleanly
    all the way through, with no second table to keep in sync.

    The DJ voice pool is deliberately NOT filtered: Atomika is SSX 3's
    announcer but he fronts the whole station, and muting him along with the
    SSX 3 songs would turn "I'd rather not hear SSX 3's music" into "the radio
    has no presenter".
    """
    def __init__(self, sources=None):
        self.sources = None if sources is None else set(sources)
        self.clips = load_clips()  # category -> [paths]

        # MusicIntroductions split by artist.
        self.intros_by_artist = {}   # artist_id -> [paths]
        self.generic_intros = []     # artist-less "here's some tunes"
        for p in self.clips.get("MusicIntroductions", []):
            a = intro_artist_of(os.path.basename(p))
            if a:
                self.intros_by_artist.setdefault(a, []).append(p)
            else:
                self.generic_intros.append(p)

        # Song pools + a separate MENU pool. The SSX3 Hub Themes (36-38) and the
        # Tricky Menu track aren't race songs — they're the lobby loops, so they
        # feed the menu broadcast instead of the race shuffle.
        self.songs = []       # race tracks: path, num, title, artist_id, source
        self.menu_tracks = []  # lobby loops (Hub Themes + Tricky Menu)
        for p in _list_music(SSX3):
            num, title, artist = parse_song(p)
            if num is not None and num >= 36:
                self.menu_tracks.append(dict(path=p, num=num, title=title,
                                             artist_id=None, source="ssx3"))
                continue
            self.songs.append(dict(path=p, num=num, title=title,
                                   artist_id=artist, source="ssx3"))
        for p in _list_music(TRICKY):
            num, title, _ = parse_song(p)
            if "menu" in title.lower():
                self.menu_tracks.append(dict(path=p, num=num, title=title,
                                             artist_id=None, source="tricky"))
                continue
            self.songs.append(dict(path=p, num=num, title=title,
                                   artist_id=None, source="tricky"))
        # On Tour: all 41 are licensed race tracks — the game has no lobby loop
        # of its own to feed menu_tracks, so nothing is split off here.
        for p in _list_music(SXOT):
            num, title, artist = parse_song(p)
            self.songs.append(dict(path=p, num=num, title=title,
                                   artist_id=artist, source="sxot"))
        # SSX (2012): 36 licensed race tracks, no lobby loop of its own either.
        for p in _list_music(SSX2012):
            num, title, artist = parse_song(p)
            self.songs.append(dict(path=p, num=num, title=title,
                                   artist_id=artist, source="ssx2012"))

        if self.sources is not None:
            dropped = sorted({s["source"] for s in self.songs} - self.sources)
            self.songs = [s for s in self.songs if s["source"] in self.sources]
            self.menu_tracks = [s for s in self.menu_tracks
                                if s["source"] in self.sources]
            if dropped:
                print(f"[library] sources disabled by config: "
                      f"{', '.join(dropped)}", flush=True)
            unknown = sorted(self.sources - set(ALL_SOURCES))
            if unknown:
                # A typo'd source name would otherwise silently filter to
                # nothing and read as "the radio is broken".
                print(f"!! [library] --sources named {', '.join(unknown)}, which "
                      f"is not a known soundtrack ({', '.join(ALL_SOURCES)}) — "
                      f"check the plugin's [Sources] config", flush=True)
            if not self.songs:
                print("!! [library] every soundtrack is switched off — the DJ "
                      "will talk but no music will play. Re-enable one under "
                      "[Sources] in com.mtv.radiobig.cfg.", flush=True)
            elif not self.menu_tracks:
                # SSX 3's Hub Themes and Tricky's Menu track are the only lobby
                # loops there are; with both off the menu is silent even though
                # races still have music, which looks like a different bug.
                print("!! [library] no menu/lobby music left (that comes from "
                      "SSX 3's Hub Themes and Tricky's Menu track) — menus will "
                      "be silent, races still play.", flush=True)

    def intros_for(self, song):
        """The artist-matched intro clips for a song, or [] if none."""
        a = song.get("artist_id")
        return list(self.intros_by_artist.get(a, [])) if a else []


if __name__ == "__main__":
    lib = Library()
    print(f"DJ clip categories: {len(lib.clips)}")
    for cat in sorted(lib.clips):
        print(f"  {len(lib.clips[cat]):3d}  {cat}")
    print(f"\nMusicIntroductions: {len(lib.intros_by_artist)} artists matched, "
          f"{len(lib.generic_intros)} generic")
    # Counted off ALL_SOURCES rather than a hand-listed set, so a soundtrack
    # added to the library can never quietly go unreported here.
    _labels = {"ssx3": "SSX3", "tricky": "Tricky", "sxot": "On Tour",
               "ssx2012": "SSX 2012"}
    print(f"\nSongs: {len(lib.songs)} (" + " + ".join(
        f"{sum(1 for s in lib.songs if s['source'] == src)} "
        f"{_labels.get(src, src)}" for src in ALL_SOURCES) + ")")
    matched = [s for s in lib.songs if lib.intros_for(s)]
    print(f"Songs with an artist-matched intro: {len(matched)}\n")
    for s in lib.songs:
        n = len(lib.intros_for(s))
        tag = (f"{n} intros" if n else
               "(instrumental)" if s['source'] == 'tricky' else
               "(no On Tour DJ)" if s['source'] == 'sxot' else
               "(2012 has its own DJ)" if s['source'] == 'ssx2012' else
               "NO INTRO")
        print(f"  [{s['source']:7}] {str(s['title'])[:38]:38}  {tag}")
