#!/usr/bin/env python3
"""Radio Big DJ brain — the scheduler that makes it feel like a station.

The BepInEx plugin only forwards game events (course start/end, combo, knockdown,
finish). ALL the pacing and song/clip selection lives here so it can be retuned by
editing Python, no DLL rebuild. A "broadcast" runs on its own thread the moment a
course starts:

    RACE:  artist-matched intro  ->  SONG  ->  (rides under gameplay)
                                 ->  intro -> SONG ...   course end -> outro -> fade
    MENU:  lobby loop  +  banter spliced in every ~16s

"Smarter than random": when the next song is an SSX3 track with a dedicated
Atomika intro, the DJ actually names the artist about to play (dj_library). Every
category is drawn from a no-repeat shuffle bag, so two loads never sound the same.
The menu banter is also session-aware — post-race recap clips only enter the pool
once you've actually raced, so a cold boot never recaps a race that never happened.

There are no in-the-moment reactive barks: the voice pack is all 12-20s broadcast
segments, nothing short enough to punch in on a single trick (see react()).
"""
import os
import sys
import time
import random
import threading

from radio_player import RadioPlayer
from dj_library import Library


def _display_artist(artist_id):
    """Human-readable artist name for the status feed. dj_library.py has no
    canonical display-name table (artist_id is an internal matching key, e.g.
    "queens_stone_age", "rhcp_executioners") -- checked, there's INTRO_ARTISTS
    and SONG_ARTIST but both only map INTO artist_id, never back out to prose.
    So this is a plain fallback: underscores to spaces, title-cased. Good
    enough for a HUD ("Queens Stone Age"), not meant to be publication-quality."""
    if not artist_id:
        return None
    return artist_id.replace("_", " ").title()


class ShuffleBag:
    """Draw without replacement; reshuffle only once exhausted (no repeats until
    every item has been used). The anti-repetition that makes it feel curated."""
    def __init__(self, items, rng):
        self._items = list(items)
        self._rng = rng
        self._pool = []

    def __bool__(self):
        return bool(self._items)

    def draw(self):
        if not self._items:
            return None
        if not self._pool:
            self._pool = list(self._items)
            self._rng.shuffle(self._pool)
        return self._pool.pop()


class DJBrain:
    # Chatter for the MENU broadcast — the lobby is where the banter lives now
    # (in-race it was too much dead air, so race mode is intro/outro only). These
    # are all timeless or forward-looking ("competitors WILL be racing...") so
    # they're safe on a cold boot; nothing here references a race as past tense.
    MENU_BANTER_CATS = [
        ("BigMountainLocalNews", 5),
        ("EventIntroductions", 4),      # forward promos, launch-safe
        ("RiderBackstories", 4),
        ("RiderCircuitProgressio", 3),
        ("CurrentWeatherConditio", 2),
        ("CurrentTerrainConditio", 2),
        ("BigMountainHistory", 2),
        ("PeakRivalQuotes", 1),
        ("FreeRideQuotes", 1),
        ("BackcountryQuotes", 1),
        ("EnteringAStation", 1),
        ("TextMessageReminders", 1),
    ]
    # Past-tense event RECAPS ("did anyone catch what went down today?"). They only
    # make sense once a race has happened, so they fold into the menu pool AFTER the
    # first course starts this session — never on a cold boot, where they'd recap a
    # race that never occurred.
    POSTRACE_BANTER_CATS = [
        ("FreestyleHigh-Score", 4),
        ("AggressionDuringEvents", 2),
    ]

    # How often each soundtrack comes up. SSX3 leads because it is the only one
    # Atomika can name the artist of — every SSX3 draw is a shot at the
    # artist-matched intro, the others can only ever land a generic one.
    # ⚠️ Feel numbers, not measured. Each new soundtrack is carved out of SSX3's
    # share rather than the others', so nothing that was already playing gets
    # quieter when one is added: 0.78/0.22 before On Tour, 0.66/0.19/0.15 after,
    # SSX 2012 takes its 0.15 from SSX3 the same way, and Tricky Madness' own
    # soundtrack takes 0.10 from it again. SSX3 keeps the lead — still more than
    # double the next — which is the point of the ordering.
    # `tm` sits lowest deliberately: it is the music Radio Big replaces, so it
    # belongs in the rotation as a nod rather than as a headliner.
    SOURCE_WEIGHTS = {"ssx3": 0.41, "tricky": 0.19, "sxot": 0.15,
                      "ssx2012": 0.15, "tm": 0.10}
    # What an installed-but-unweighted soundtrack plays at until someone gives
    # it a real share — enough to be obviously present, not enough to take over.
    UNWEIGHTED_SHARE = 0.10

    def __init__(self, player=None, library=None, seed=None,
                 source_weights=None, menu_banter_gap=16):
        self.player = player or RadioPlayer()
        self.lib = library or Library()
        self.rng = random.Random(seed)  # seeded per process -> varies each launch
        # `is None`, not `or`: an explicit {} means "no sources", and falling
        # back to the class defaults there would silently ignore the caller.
        self.source_weights = dict(self.SOURCE_WEIGHTS if source_weights is None
                                   else source_weights)
        self.menu_banter_gap = menu_banter_gap

        # No-repeat bags per clip category + per song source.
        self._bags = {cat: ShuffleBag(paths, self.rng)
                      for cat, paths in self.lib.clips.items()}
        # ⚠️ Driven by WHAT LOADED, not by the weight table. A soundtrack that
        # isn't installed simply has no bag and _next_song renormalises over the
        # rest; a soundtrack that IS installed but was never given a weight would
        # otherwise load, count, print in the library dump — and be undrawable
        # forever, because the bags were built from the weights. That is the
        # exact "quietly diminished result" this project's rules forbid, so it
        # gets a default weight and a loud line instead.
        self._song_bags = {}
        for src in sorted({s["source"] for s in self.lib.songs}):
            if src not in self.source_weights:
                self.source_weights[src] = self.UNWEIGHTED_SHARE
                self._log(f"!! soundtrack '{src}' has no DJBrain.SOURCE_WEIGHTS "
                          f"entry — playing it at {self.UNWEIGHTED_SHARE}; add "
                          f"one to set its real share")
            self._song_bags[src] = ShuffleBag(
                [s for s in self.lib.songs if s["source"] == src], self.rng)
        self._menu_bag = ShuffleBag(self.lib.menu_tracks, self.rng)
        # Per-song intro bags so a track's 3 intros rotate instead of repeating.
        self._intro_bags = {a: ShuffleBag(paths, self.rng)
                            for a, paths in self.lib.intros_by_artist.items()}
        self._generic_intro_bag = ShuffleBag(self.lib.generic_intros, self.rng)

        self._voice_lock = threading.Lock()  # one DJ voice clip at a time
        # Starts SET and holds the CURRENT worker's flag. Pre-set so a
        # _halt_worker() before anything has been started is a plain no-op
        # rather than arming a flag some later worker inherits.
        self._stop = threading.Event()
        self._stop.set()
        self._thread = None
        self._raced_session = False  # unlocks recap banter after the first race

        # --- status feed for the in-game HUD (radio_server.py's StatusWriter,
        # optional --statusfile) --------------------------------------------
        # `track` here is metadata only (title/artist/source); elapsed/duration
        # are NOT cached -- get_status() reads them live off self.player so a
        # poller always sees a current number, not one stamped at the last
        # transition.
        self._status_lock = threading.Lock()
        self._status = {"state": "idle", "track": None, "dj_talking": False}
        self._status_listener = None  # optional no-arg callable, see below

    def set_status_listener(self, fn):
        """Register a no-arg callable invoked every time the status snapshot
        changes, so a poller (StatusWriter) can push an update immediately
        instead of waiting out its tick. Best-effort: an exception from the
        listener is swallowed here so a HUD-reporting hiccup can never take
        down playback."""
        self._status_listener = fn

    def get_status(self):
        """Current snapshot for the HUD feed: {state, track, dj_talking}.
        See module docstring users (radio_server.py StatusWriter) for the JSON
        shape this is serialised into. `track` is None when nothing is
        currently playing; elapsed/duration are computed live from the player,
        never from a value stamped at the last transition."""
        with self._status_lock:
            state = self._status["state"]
            meta = self._status["track"]
            dj_talking = self._status["dj_talking"]
        track = None
        if meta is not None:
            elapsed = self.player.elapsed()
            track = {
                "title": meta.get("title"),
                "artist": meta.get("artist"),
                "source": meta.get("source"),
                "elapsed": elapsed if elapsed is not None else 0.0,
                "duration": self.player.duration(),
            }
        return {"state": state, "track": track, "dj_talking": dj_talking,
                "paused": self.player.is_paused()}

    def _set_status(self, **changes):
        """Update one or more status fields (state/track/dj_talking) and
        notify the listener, if any. `track` should be a small dict
        (title/artist/source) or None -- never call this with elapsed/duration,
        those are computed live in get_status()."""
        with self._status_lock:
            self._status.update(changes)
        if self._status_listener is not None:
            try:
                self._status_listener()
            except Exception:
                pass  # a HUD notification must never break playback

    # --- public API (driven by the plugin over IPC) ----------------------
    def start_course(self, name=""):
        """A race started: intro -> song (no menu chatter)."""
        self._raced_session = True  # from now on the lobby may recap races
        self._set_status(state="racing", track=None)
        self._begin(self._race_broadcast)

    def enter_menu(self):
        """Back at the lobby: menu loops with banter spliced in."""
        self._set_status(state="menu", track=None)
        self._begin(self._menu_broadcast)

    def finish(self):
        """Race finished (FINISHED on screen): sign off NOW, then fade the bed —
        fires here so it never bleeds into the next race's start."""
        self._halt_worker()
        self._set_status(state="finished", track=None)
        threading.Thread(target=self._do_outro, daemon=True).start()

    def stop_all(self, fade_ms=600):
        """Full stop — e.g. the game quit and the socket dropped."""
        self._halt_worker()
        self._set_status(state="idle", track=None, dj_talking=False)
        self.player.stop(fade_ms=fade_ms)

    # --- transport (the pill's buttons) ---------------------------------
    def skip(self):
        """Next track now. The broadcast worker is already blocked in
        _wait_for_track_end, and that wait is driven entirely by "is the bed
        still busy" -- so ending the bed IS the skip. Nothing here has to know
        which worker is running or what it planned to play next."""
        self._log("skip -> ending current track")
        self.player.skip_track()

    def set_paused(self, paused):
        """Pause or resume the music bed. Returns the resulting paused state.

        Note the worker keeps running: _wait_for_track_end also waits out a
        pause (see there), so a paused track does not silently advance the
        playlist while the rider is in the menu."""
        changed = self.player.pause() if paused else self.player.resume()
        if changed:
            self._log("paused" if paused else "resumed")
            # Push the new icon state to the HUD immediately rather than
            # letting it wait out the status writer's next tick.
            self._set_status()
        return self.player.is_paused()

    def toggle_pause(self):
        """Flip pause state. Returns the resulting paused state."""
        return self.set_paused(not self.player.is_paused())

    def react(self, kind):
        """Reactive one-liner for a gameplay beat (combo/knockdown/...).

        Deliberately a no-op. The Radio Big voice pack has NO short in-the-moment
        barks — every content clip is a 12-20s broadcast segment (verified against
        the clip manifest), so reacting to a single trick would drop a monologue
        mid-run. The game-side event hooks and this EVENT verb stay wired so a
        future pack with real barks is a one-line enable; today it does nothing."""
        return

    # --- worker lifecycle ------------------------------------------------
    def _begin(self, target):
        """Start a broadcast, guaranteeing the previous one is really finished.

        ⚠️ Each worker gets its OWN stop Event, passed in as an argument, and a
        halted worker's Event is never cleared again. Do not go back to one
        shared `self._stop` that `_begin` clears: a worker mid-clip outlives the
        halt by design (see _halt_worker), so the clear un-stopped a thread that
        was still running, and the resurrected menu worker went on splicing
        banter every `menu_banter_gap` seconds OVER the race for the rest of the
        session. That is the "DJ talks over every song" bug, and every startable
        broadcast could stack another zombie on top."""
        self._halt_worker()
        stop = threading.Event()
        self._stop = stop
        self._thread = threading.Thread(target=target, args=(stop,), daemon=True)
        self._thread.start()

    def _halt_worker(self):
        """Ask the current broadcast to end. Does NOT wait for it to.

        ⚠️ A halted worker that is mid-clip goes on talking until the clip ends
        — on purpose. Atomika finishing his sentence before the race intro takes
        over is the station feel, and the handover is clean because the incoming
        worker's first _say has to take the voice lock this one still holds.

        Correctness therefore rests entirely on the flag being per-worker and
        never cleared, NOT on the join: whenever the lingering worker next looks
        up, its own Event is set and it exits. The join is a short courtesy reap
        for workers that are merely sleeping, and _begin runs on the IPC thread,
        so it must not sit here for the length of a clip."""
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=0.25)
        self._thread = None

    # --- race: intro -> song, looping for long runs ----------------------
    def _race_broadcast(self, stop):
        while not stop.is_set():
            song = self._next_song()
            if song is None:
                break
            self._say(self._intro_for(song), stop=stop)  # names the artist when we can
            if stop.is_set():
                break
            self.player.play_music(song["path"])
            # Status update sits HERE (after play_music, not when the song was
            # drawn above) so title/artist line up with elapsed/duration, which
            # the player only starts counting from once play_music actually
            # starts the track -- setting it before the intro line would show
            # the new title against the previous track's elapsed/duration for
            # the length of the intro clip.
            self._set_status(state="racing", track={
                "title": song["title"],
                "artist": _display_artist(song.get("artist_id")),
                "source": song["source"],
            })
            self._log(f"NOW PLAYING: {song['title']} "
                      f"[{song['source']}]" + ("" if song["artist_id"] else " (no intro)"))
            self._wait_for_track_end(stop)  # let the song finish before the next intro

    def _do_outro(self):
        with self._voice_lock:                 # don't collide with a race clip
            clip = self._draw("RadioBigOutros")
            if clip and self.player.music_busy():
                self._set_status(dj_talking=True)
                try:
                    self.player.say(clip, restore=False)  # stay ducked, then fade
                finally:
                    self._set_status(dj_talking=False)
        self.player.stop(fade_ms=1400)

    # --- menu: lobby loops with banter spliced in ------------------------
    def _menu_broadcast(self, stop):
        first = True
        while not stop.is_set():
            track = self._menu_bag.draw()
            if track is None:
                break
            self.player.play_music(track["path"], fade_ms=1200 if first else 800)
            self._set_status(state="menu", track={
                "title": track["title"],
                "artist": _display_artist(track.get("artist_id")),
                "source": track["source"],
            })
            self._log(f"MENU: {track['title']} [{track['source']}]")
            first = False
            # Splice a banter line every menu_banter_gap seconds until the loop
            # track ends, then move to the next one.
            while self.player.music_busy() and not stop.is_set():
                if self._sleep_interruptible(self.menu_banter_gap, stop):
                    return
                if not self.player.music_busy() or stop.is_set():
                    break
                self._say(self._draw_menu_banter(), stop=stop)

    def _wait_for_track_end(self, stop):
        """Block until the current song finishes, waking early on stop.

        Songs play to completion — a race ending fires finish(), which halts
        this worker and rolls the outro, so there's no reason to cut a track
        short mid-run (the old fixed segment cap chopped every song that ran
        longer than it, which was every real track)."""
        # `or is_paused()` matters: pygame reports a paused stream as not
        # busy on some backends, which would read as "song over" and skip to
        # the next track the moment you hit pause.
        while (self.player.music_busy() or self.player.is_paused()) and not stop.is_set():
            time.sleep(0.15)

    def _sleep_interruptible(self, seconds, stop):
        """Sleep, returning True if a stop was requested mid-sleep."""
        step, waited = 0.1, 0.0
        while waited < seconds:
            if stop.is_set():
                return True
            time.sleep(step)
            waited += step
        return False

    # --- selection helpers ----------------------------------------------
    def _next_song(self):
        """Weighted draw across the installed soundtracks.

        Weights are renormalised over the bags that exist, so an install missing
        On Tour plays the other two at their old ratio rather than silently
        going quiet 15% of the time."""
        if not self._song_bags:
            return None
        # Drop non-positive weights rather than handing them to rng.choices,
        # which raises on a total of zero — and would happily let a negative
        # weight cancel a positive one out of the running.
        srcs = [s for s in self._song_bags if self.source_weights.get(s, 0) > 0]
        weights = [self.source_weights[s] for s in srcs]
        if not srcs:                  # every installed source weighted <= 0
            srcs = list(self._song_bags)
            weights = [1.0] * len(srcs)
        src = self.rng.choices(srcs, weights=weights, k=1)[0]
        song = self._song_bags[src].draw()
        if song:
            return song
        # A bag can only come back empty if its pool was empty, which the
        # constructor already filters out -- but fall through rather than
        # returning None and dropping a broadcast on the floor.
        for other in self._song_bags:
            song = self._song_bags[other].draw()
            if song:
                return song
        return None

    def _intro_for(self, song):
        a = song.get("artist_id")
        if a and self._intro_bags.get(a):
            return self._intro_bags[a].draw()
        return self._generic_intro_bag.draw()

    def _draw_menu_banter(self):
        pool = self.MENU_BANTER_CATS
        if self._raced_session:  # recaps earn their way in after the first race
            pool = pool + self.POSTRACE_BANTER_CATS
        cats, weights = zip(*pool)
        cat = self.rng.choices(cats, weights=weights, k=1)[0]
        return self._draw(cat)

    def _draw(self, cat):
        bag = self._bags.get(cat)
        return bag.draw() if bag else None

    # --- voice with a single-speaker lock --------------------------------
    def _say(self, path, stop=None, blocking=True):
        """Speak a clip, waiting for whoever is talking to finish first.

        ⚠️ This is where a halted broadcast is actually stopped, and `stop` (the
        CALLING WORKER's own Event) is what does it — clips themselves always run
        to the end, so the only safe place to drop a line is BEFORE it starts.
        Two checks, and both are load-bearing:

          * while waiting for the lock — a worker can sit queued here across its
            own halt, because the clip ahead of it plays out in full;
          * again after acquiring it — by then the halt may have landed and a
            race started, and a plain `with self._voice_lock` would wake up and
            play one stale banter line straight over it."""
        if not path:
            return
        if blocking:
            while not self._voice_lock.acquire(timeout=0.1):
                if stop is not None and stop.is_set():
                    return
            try:
                if stop is not None and stop.is_set():
                    return
                self._set_status(dj_talking=True)
                try:
                    self.player.say(path)
                finally:
                    self._set_status(dj_talking=False)
            finally:
                self._voice_lock.release()
        else:
            # Reactive: skip rather than queue if the DJ is already talking.
            if self._voice_lock.acquire(blocking=False):
                try:
                    self._set_status(dj_talking=True)
                    try:
                        self.player.say(path)
                    finally:
                        self._set_status(dj_talking=False)
                finally:
                    self._voice_lock.release()

    def _log(self, msg):
        print(f"[dj] {msg}", flush=True)


# --- standalone dogfood: a compressed broadcast you can hear, no game ----
def demo():
    # Compressed timings so the whole lifecycle plays out fast.
    dj = DJBrain(menu_banter_gap=8)
    print("[demo] MENU: lobby loop + banter")
    dj.enter_menu()
    time.sleep(16)
    print("[demo] START: race (intro -> song, no chatter)")
    dj.start_course("Demo Peak")
    time.sleep(12)
    print("[demo] FINISH: outro fires immediately, then fade")
    dj.finish()
    time.sleep(6)
    print("[demo] back to MENU")
    dj.enter_menu()
    time.sleep(10)
    print("[demo] game quit -> stop_all")
    dj.stop_all()
    while dj.player.music_busy():
        time.sleep(0.1)
    print("[demo] done")
    return 0


if __name__ == "__main__":
    sys.exit(demo())
