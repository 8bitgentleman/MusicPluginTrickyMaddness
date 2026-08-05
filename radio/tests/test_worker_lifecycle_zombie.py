#!/usr/bin/env python3
"""Repro: a menu worker survives _halt_worker and keeps talking over the race.

No audio — a fake player stands in for RadioPlayer so the timings are compressed
and the test is deterministic. The only thing under test is DJBrain's worker
lifecycle.
"""
import sys, time, threading
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dj_brain
from dj_brain import DJBrain

SAY_SECS = 1.5          # stands in for a real 12-20s banter clip
JOIN_TIMEOUT = 0.2      # stands in for the real join(timeout=2.0)


class FakePlayer:
    """Blocks in say() the way the real one does, and reports music as playing."""
    def __init__(self):
        self.said = []
        self.lock = threading.Lock()

    def play_music(self, path, fade_ms=800):
        pass

    def music_busy(self):
        return True                      # a song is always rolling

    def say(self, path, tail=0.0, restore=True):
        """Mirrors RadioPlayer.say: a clip ALWAYS runs to the end, so this
        blocking wait outlives the halt on purpose."""
        with self.lock:
            self.said.append((time.time(), threading.current_thread().name, path))
        time.sleep(SAY_SECS)

    def stop(self, fade_ms=600):
        pass


class FakeLib:
    """Minimum shape DJBrain's constructor needs."""
    clips = {c: [f"{c}.mp3"] for c, _ in
             DJBrain.MENU_BANTER_CATS + DJBrain.POSTRACE_BANTER_CATS}
    clips["RadioBigOutros"] = ["outro.mp3"]
    songs = [{"path": "s.mp3", "title": "Song", "source": "ssx3", "artist_id": None}]
    menu_tracks = [{"path": "m.mp3", "title": "Hub", "source": "ssx3"}]
    intros_by_artist = {}
    generic_intros = ["generic.mp3"]


def main():
    p = FakePlayer()
    dj = DJBrain(player=p, library=FakeLib(), seed=1, menu_banter_gap=0.4)
    # Shrink the join timeout to keep the real clip:join ratio (a 1.5s clip
    # against a 0.2s join is the same "clip far outlives the join" shape as
    # 12-20s against 2s). Otherwise this mirrors _halt_worker exactly, so the
    # lifecycle under test is the shipped one.
    def patched_halt(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=JOIN_TIMEOUT)
        self._thread = None
    DJBrain._halt_worker = patched_halt

    print("-- entering menu (banter every 0.4s, each clip blocks 1.5s)")
    dj.enter_menu()
    time.sleep(1.0)                      # land inside a blocking say()

    menu_threads = {t.name for t in threading.enumerate() if t.daemon}
    print(f"-- starting a course while the DJ is mid-sentence")
    dj.start_course("Test Peak")

    before = len(p.said)
    time.sleep(4.0)                      # race is running; nobody should chatter
    # The race's OWN intro is expected here — only lobby banter is a defect.
    # (The in-flight lobby line finishing is fine too; it started before the
    #  race did, and letting it land is deliberate — see test_voice_handover.)
    new = [s for s in p.said[before:]
           if "generic" not in s[2] and "outro" not in s[2]]

    live = [t.name for t in threading.enumerate() if t.is_alive() and t.daemon]
    for _, th, path in new:
        print(f"   stray: {th} -> {path}")
    print(f"\nlobby banter STARTED during the race: {len(new)}")
    print(f"live daemon worker threads: {len(live)}")
    print(f"stop flag currently set? {dj._stop.is_set()}")
    dj.stop_all()
    if new:
        print("\nREPRO CONFIRMED: the menu worker survived and kept talking "
              "over the race.")
        return 1
    print("\nno zombie: race stayed quiet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
