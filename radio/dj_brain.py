#!/usr/bin/env python3
"""Radio Big DJ brain — the scheduler that makes it feel like a station.

The BepInEx plugin only forwards game events (course start/end, combo, knockdown,
finish). ALL the pacing and song/clip selection lives here so it can be retuned by
editing Python, no DLL rebuild. A "broadcast" runs on its own thread the moment a
course starts:

    station ID  ->  [warm-up banter]  ->  artist-matched intro  ->  SONG
                 ->  (song rides under gameplay) ->  [banter] -> intro -> SONG ...
    course end  ->  outro  ->  fade

"Smarter than random": when the next song is an SSX3 track with a dedicated
Atomika intro, the DJ actually names the artist about to play (dj_library). Every
category is drawn from a no-repeat shuffle bag, so two loads never sound the same.

Reactive lines (combo/knockdown/finish) duck in over the bed, best-effort — a live
reaction is dropped rather than queued if the DJ is already mid-sentence.
"""
import os
import sys
import time
import random
import threading

from radio_player import RadioPlayer
from dj_library import Library


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
    # (in-race it was too much dead air, so race mode is intro/outro only).
    MENU_BANTER_CATS = [
        ("BigMountainLocalNews", 5),
        ("RiderBackstories", 4),
        ("RiderCircuitProgressio", 3),
        ("CurrentWeatherConditio", 2),
        ("CurrentTerrainConditio", 2),
        ("BigMountainHistory", 2),
        ("PeakRivalQuotes", 1),
        ("FreeRideQuotes", 1),
        ("BackcountryQuotes", 1),
        ("TextMessageReminders", 1),
    ]
    REACT_CATS = {
        "combo": ["FreestyleHigh-Score", "AggressionDuringEvents"],
        "knockdown": ["AggressionDuringEvents", "PeakRivalQuotes"],
    }

    def __init__(self, player=None, library=None, seed=None,
                 segment_seconds=95, ssx3_bias=0.78, menu_banter_gap=16):
        self.player = player or RadioPlayer()
        self.lib = library or Library()
        self.rng = random.Random(seed)  # seeded per process -> varies each launch
        self.segment_seconds = segment_seconds
        self.ssx3_bias = ssx3_bias
        self.menu_banter_gap = menu_banter_gap

        # No-repeat bags per clip category + per song source.
        self._bags = {cat: ShuffleBag(paths, self.rng)
                      for cat, paths in self.lib.clips.items()}
        ssx3 = [s for s in self.lib.songs if s["source"] == "ssx3"]
        tricky = [s for s in self.lib.songs if s["source"] == "tricky"]
        self._ssx3_bag = ShuffleBag(ssx3, self.rng)
        self._tricky_bag = ShuffleBag(tricky, self.rng)
        self._menu_bag = ShuffleBag(self.lib.menu_tracks, self.rng)
        # Per-song intro bags so a track's 3 intros rotate instead of repeating.
        self._intro_bags = {a: ShuffleBag(paths, self.rng)
                            for a, paths in self.lib.intros_by_artist.items()}
        self._generic_intro_bag = ShuffleBag(self.lib.generic_intros, self.rng)

        self._voice_lock = threading.Lock()  # one DJ voice clip at a time
        self._stop = threading.Event()
        self._thread = None

    # --- public API (driven by the plugin over IPC) ----------------------
    def start_course(self, name=""):
        """A race started: intro -> song (no menu chatter)."""
        self._begin(self._race_broadcast)

    def enter_menu(self):
        """Back at the lobby: menu loops with banter spliced in."""
        self._begin(self._menu_broadcast)

    def finish(self):
        """Race finished (FINISHED on screen): sign off NOW, then fade the bed —
        fires here so it never bleeds into the next race's start."""
        self._halt_worker()
        threading.Thread(target=self._do_outro, daemon=True).start()

    def stop_all(self, fade_ms=600):
        """Full stop — e.g. the game quit and the socket dropped."""
        self._halt_worker()
        self.player.stop(fade_ms=fade_ms)

    def react(self, kind):
        """One-off ducked line for a gameplay beat. Dropped if the DJ is busy."""
        cats = self.REACT_CATS.get(kind)
        if not cats:
            return
        cat = self.rng.choice(cats)
        bag = self._bags.get(cat)
        clip = bag.draw() if bag else None
        if clip:
            threading.Thread(target=self._say, args=(clip,),
                             kwargs=dict(blocking=False), daemon=True).start()

    # --- worker lifecycle ------------------------------------------------
    def _begin(self, target):
        self._halt_worker()
        self._stop.clear()
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def _halt_worker(self):
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=2.0)
        self._thread = None

    # --- race: intro -> song, looping for long runs ----------------------
    def _race_broadcast(self):
        while not self._stop.is_set():
            song = self._next_song()
            if song is None:
                break
            self._say(self._intro_for(song))   # names the artist when we can
            if self._stop.is_set():
                break
            self.player.play_music(song["path"])
            self._log(f"NOW PLAYING: {song['title']} "
                      f"[{song['source']}]" + ("" if song["artist_id"] else " (no intro)"))
            self._hold(self.segment_seconds)   # next song only on long races

    def _do_outro(self):
        with self._voice_lock:                 # don't collide with a race clip
            clip = self._draw("RadioBigOutros")
            if clip and self.player.music_busy():
                self.player.say(clip, restore=False)  # stay ducked, then fade
        self.player.stop(fade_ms=1400)

    # --- menu: lobby loops with banter spliced in ------------------------
    def _menu_broadcast(self):
        first = True
        while not self._stop.is_set():
            track = self._menu_bag.draw()
            if track is None:
                break
            self.player.play_music(track["path"], fade_ms=1200 if first else 800)
            self._log(f"MENU: {track['title']} [{track['source']}]")
            first = False
            # Splice a banter line every menu_banter_gap seconds until the loop
            # track ends, then move to the next one.
            while self.player.music_busy() and not self._stop.is_set():
                if self._sleep_interruptible(self.menu_banter_gap):
                    return
                if not self.player.music_busy() or self._stop.is_set():
                    break
                self._say(self._draw_menu_banter())

    def _hold(self, seconds):
        """Sleep up to `seconds`, waking early on stop or track end."""
        step, waited = 0.15, 0.0
        while waited < seconds and not self._stop.is_set():
            if not self.player.music_busy():
                return  # track finished -> start the next segment now
            time.sleep(step)
            waited += step

    def _sleep_interruptible(self, seconds):
        """Sleep, returning True if a stop was requested mid-sleep."""
        step, waited = 0.1, 0.0
        while waited < seconds:
            if self._stop.is_set():
                return True
            time.sleep(step)
            waited += step
        return False

    # --- selection helpers ----------------------------------------------
    def _next_song(self):
        want_ssx3 = self.rng.random() < self.ssx3_bias
        first = self._ssx3_bag if want_ssx3 else self._tricky_bag
        second = self._tricky_bag if want_ssx3 else self._ssx3_bag
        return first.draw() or second.draw()

    def _intro_for(self, song):
        a = song.get("artist_id")
        if a and self._intro_bags.get(a):
            return self._intro_bags[a].draw()
        return self._generic_intro_bag.draw()

    def _draw_menu_banter(self):
        cats, weights = zip(*self.MENU_BANTER_CATS)
        cat = self.rng.choices(cats, weights=weights, k=1)[0]
        return self._draw(cat)

    def _draw(self, cat):
        bag = self._bags.get(cat)
        return bag.draw() if bag else None

    # --- voice with a single-speaker lock --------------------------------
    def _say(self, path, blocking=True):
        if not path:
            return
        if blocking:
            with self._voice_lock:
                self.player.say(path)
        else:
            # Reactive: skip rather than queue if the DJ is already talking.
            if self._voice_lock.acquire(blocking=False):
                try:
                    self.player.say(path)
                finally:
                    self._voice_lock.release()

    def _log(self, msg):
        print(f"[dj] {msg}", flush=True)


# --- standalone dogfood: a compressed broadcast you can hear, no game ----
def demo():
    # Compressed timings so the whole lifecycle plays out fast.
    dj = DJBrain(segment_seconds=14, menu_banter_gap=8)
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
