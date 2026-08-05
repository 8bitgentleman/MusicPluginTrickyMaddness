#!/usr/bin/env python3
"""Second-order repro: a worker queued behind the (deliberately uninterruptible)
outro sign-off wakes up after being halted and plays one line over the race.

Same fake player as repro_zombie.py; the difference is the sequence — menu ->
finish (outro takes the voice lock) -> menu (worker blocks on the lock) ->
start race. Nothing should talk during the race.
"""
import sys, time, threading
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dj_brain import DJBrain

SAY_SECS = 1.5
JOIN_TIMEOUT = 0.2


class FakePlayer:
    def __init__(self):
        self.said = []
        self.lock = threading.Lock()

    def play_music(self, path, fade_ms=800):
        pass

    def music_busy(self):
        return True

    def say(self, path, tail=0.0, restore=True):
        with self.lock:
            self.said.append((time.time(), threading.current_thread().name, path))
        time.sleep(SAY_SECS)

    def stop(self, fade_ms=600):
        pass


class FakeLib:
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

    def patched_halt(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=JOIN_TIMEOUT)
        self._thread = None
    DJBrain._halt_worker = patched_halt

    print("-- menu")
    dj.enter_menu()
    time.sleep(0.8)
    print("-- finish: outro takes the voice lock for a full clip")
    dj.finish()
    time.sleep(0.1)
    print("-- back to menu while the sign-off is still going")
    dj.enter_menu()
    # Long enough for the new menu worker to clear its banter_gap sleep and be
    # sitting INSIDE _say blocked on the voice lock. That is the only window
    # this bug lives in — halt it any earlier and it exits on the gap sleep.
    time.sleep(0.6)
    print("-- race starts before the sign-off has released the lock")
    dj.start_course("Test Peak")

    before = len(p.said)
    time.sleep(4.0)
    during = [s for s in p.said[before:] if "outro" not in s[2] and "generic" not in s[2]]

    print(f"\nbanter clips played DURING the race: {len(during)}")
    for s in during:
        print(f"   {s[1]} -> {s[2]}")
    print(f"live daemon worker threads: "
          f"{len([t for t in threading.enumerate() if t.is_alive() and t.daemon])}")
    dj.stop_all()
    if during:
        print("\nREPRO CONFIRMED: a lock-queued worker talked over the race.")
        return 1
    print("\nclean: race stayed quiet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
