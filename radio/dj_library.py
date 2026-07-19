#!/usr/bin/env python3
"""Radio Big asset library + artist-aware song<->DJ-intro matching.

Two pools on disk:
  * DJ voice clips -> RADIO dir, categorised by a filename prefix
    (MusicIntroductions, BigMountainLocalNews, RiderBackstories, ...).
  * Music tracks   -> the SSX 3 and SSX Tricky soundtrack rips.

The one bit of "smarter than random": ~28 of the 35 SSX3 songs have a dedicated
Atomika intro that names the artist ("...up next, Placebo"). We parse the artist
out of both filenames and match them so the DJ can actually introduce the track
that's about to play. Tricky tracks are instrumental and predate this DJ, so they
get no artist intro (generic music-bed intros only).

Pure stdlib, no third-party deps — this module is import-safe with no audio.
"""
import os
import re
import sys
import glob

MUSIC_EXTS = (".mp3", ".ogg", ".wav", ".m4a")


# --- asset locations ------------------------------------------------------
# Three audio pools: the Radio Big DJ voice clips, and the two soundtracks.
# Resolved at import so the same code runs from source (the author's machine)
# AND as a frozen, shipped bundle. Precedence:
#   1. RADIO_BIG_ASSETS  -> <dir>/{dj,ssx3,tricky}   (the shipped layout; the
#      plugin sets this when it auto-launches the frozen player)
#   2. per-pool overrides RADIO_BIG_{DJ,SSX3,TRICKY}
#   3. an `assets/` folder beside a PyInstaller-frozen executable
#   4. the original dev paths (running from source, unfrozen)
_DEV_DJ = "/Users/mtvogel/Downloads/claude_scratch/Radio_Big/Radio_Big_Sections"
_DEV_SSX3 = "/Users/mtvogel/Documents/PythonScripts/youtube-dl/SSX 3 [Soundtrack⧸Gamerip]"
_DEV_TRICKY = "/Users/mtvogel/Documents/PythonScripts/youtube-dl/SSX Tricky (Complete Soundtrack OST)"


def _resolve_assets():
    base = os.environ.get("RADIO_BIG_ASSETS")
    if not base and getattr(sys, "frozen", False):
        # Frozen: look for assets/ next to the executable, then one level up
        # (onedir puts the exe in player/, assets sit in ../assets).
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        for cand in (os.path.join(exe_dir, "assets"),
                     os.path.join(os.path.dirname(exe_dir), "assets")):
            if os.path.isdir(cand):
                base = cand
                break
    dj = os.environ.get("RADIO_BIG_DJ") or (
        os.path.join(base, "dj") if base else _DEV_DJ)
    ssx3 = os.environ.get("RADIO_BIG_SSX3") or (
        os.path.join(base, "ssx3") if base else _DEV_SSX3)
    tricky = os.environ.get("RADIO_BIG_TRICKY") or (
        os.path.join(base, "tricky") if base else _DEV_TRICKY)
    return dj, ssx3, tricky


RADIO, SSX3, TRICKY = _resolve_assets()


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


class Library:
    """Everything the DJ brain needs to know about the assets on disk."""
    def __init__(self):
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
    print(f"\nSongs: {len(lib.songs)} "
          f"({sum(1 for s in lib.songs if s['source']=='ssx3')} SSX3 + "
          f"{sum(1 for s in lib.songs if s['source']=='tricky')} Tricky)")
    matched = [s for s in lib.songs if lib.intros_for(s)]
    print(f"Songs with an artist-matched intro: {len(matched)}\n")
    for s in lib.songs:
        n = len(lib.intros_for(s))
        tag = f"{n} intros" if n else ("(instrumental)" if s['source'] == 'tricky' else "NO INTRO")
        print(f"  [{s['source']:6}] {str(s['title'])[:38]:38}  {tag}")
