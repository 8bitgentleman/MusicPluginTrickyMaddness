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
    # Categories used as the "warm-up" line before the music intro. Weighted so
    # the mountain feels alive (news/riders) more than trivia.
    WARMUP_CATS = [
        ("BigMountainLocalNews", 5),
        ("RiderBackstories", 4),
        ("RiderCircuitProgressio", 3),
        ("CurrentWeatherConditio", 3),
        ("CurrentTerrainConditio", 2),
        ("BigMountainHistory", 2),
        ("PeakRivalQuotes", 1),
    ]
    REACT_CATS = {
        "combo": ["FreestyleHigh-Score", "AggressionDuringEvents"],
        "knockdown": ["AggressionDuringEvents", "PeakRivalQuotes"],
        "finish": ["RiderCircuitProgressio", "EventIntroductions"],
    }

    def __init__(self, player=None, library=None, seed=None,
                 segment_seconds=95, ssx3_bias=0.78):
        self.player = player or RadioPlayer()
        self.lib = library or Library()
        self.rng = random.Random(seed)  # seeded per process -> varies each launch
        self.segment_seconds = segment_seconds
        self.ssx3_bias = ssx3_bias

        # No-repeat bags per clip category + per song source.
        self._bags = {cat: ShuffleBag(paths, self.rng)
                      for cat, paths in self.lib.clips.items()}
        ssx3 = [s for s in self.lib.songs if s["source"] == "ssx3"]
        tricky = [s for s in self.lib.songs if s["source"] == "tricky"]
        self._ssx3_bag = ShuffleBag(ssx3, self.rng)
        self._tricky_bag = ShuffleBag(tricky, self.rng)
        # Per-song intro bags so a track's 3 intros rotate instead of repeating.
        self._intro_bags = {a: ShuffleBag(paths, self.rng)
                            for a, paths in self.lib.intros_by_artist.items()}
        self._generic_intro_bag = ShuffleBag(self.lib.generic_intros, self.rng)

        self._voice_lock = threading.Lock()  # one DJ voice clip at a time
        self._stop = threading.Event()
        self._thread = None
        self._first_id = True  # WSfx station sting on the first ID, NoSfx after

    # --- public API (driven by the plugin over IPC) ----------------------
    def start_course(self, name=""):
        self.stop_course(fade_ms=200)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._broadcast, args=(name,), daemon=True)
        self._thread.start()

    def stop_course(self, fade_ms=800):
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=2.0)
        self.player.stop(fade_ms=fade_ms)

    def react(self, kind):
        """One-off ducked line for a gameplay beat. Dropped if the DJ is busy."""
        cats = self.REACT_CATS.get(kind)
        if not cats:
            return
        cat = self.rng.choice(cats)
        clip = self._bags.get(cat)
        clip = clip.draw() if clip else None
        if clip:
            threading.Thread(target=self._say, args=(clip,),
                             kwargs=dict(blocking=False), daemon=True).start()

    # --- broadcast loop --------------------------------------------------
    def _broadcast(self, name):
        self._say(self._station_id())
        while not self._stop.is_set():
            song = self._next_song()
            if song is None:
                break
            # Warm-up line, then the (ideally artist-matched) music intro.
            self._say(self._draw_warmup())
            if self._stop.is_set():
                break
            self._say(self._intro_for(song))
            if self._stop.is_set():
                break
            self.player.play_music(song["path"])
            self._log(f"NOW PLAYING: {song['title']} "
                      f"[{song['source']}]" + ("" if song["artist_id"] else " (no intro)"))
            # Let it ride under gameplay; yield to a mid-course break after
            # segment_seconds, or when the track ends early.
            self._hold(self.segment_seconds)
        # Sign-off.
        if self.player.music_busy():
            self._say(self._draw("RadioBigOutros"))
        self.player.stop(fade_ms=1000)

    def _hold(self, seconds):
        """Sleep up to `seconds`, waking early on stop or track end."""
        end = seconds
        step = 0.15
        waited = 0.0
        while waited < end and not self._stop.is_set():
            if not self.player.music_busy():
                return  # track finished -> start the next segment now
            time.sleep(step)
            waited += step

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

    def _station_id(self):
        cat = "RadioBigIntrosWSfx" if self._first_id else "RadioBigIntrosNoSfx"
        self._first_id = False
        return self._draw(cat)

    def _draw_warmup(self):
        cats, weights = zip(*self.WARMUP_CATS)
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
    # Short segment so the second song comes around quickly.
    dj = DJBrain(segment_seconds=14)
    print("[demo] course start -> broadcasting")
    dj.start_course("Demo Peak")
    time.sleep(20)
    print("[demo] simulating a big combo")
    dj.react("combo")
    time.sleep(18)
    print("[demo] course end -> sign off + fade")
    dj.stop_course()
    while dj.player.music_busy():
        time.sleep(0.1)
    print("[demo] done")
    return 0


if __name__ == "__main__":
    sys.exit(demo())
