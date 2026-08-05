#!/usr/bin/env python3
"""The station feel, as a test: a lobby line that is already playing when you
drop into a course must FINISH, and the race intro must start after it — not
over it, and not instead of it.

This is the flip side of test_worker_lifecycle_zombie.py. That one proves a
halted broadcast stops talking; this one proves it stops talking *at the end of
its sentence*. A fix for either that breaks the other is not a fix.

No audio: a fake player records (start, end, thread, clip) per line so overlap
is measurable rather than something you have to listen for.
"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dj_brain import DJBrain

SAY_SECS = 1.5          # stands in for a real 12-20s clip


class FakePlayer:
    """A clip always runs to completion, exactly like RadioPlayer.say."""
    def __init__(self):
        self.lines = []          # (start, end, thread, path)
        self.lock = threading.Lock()

    def play_music(self, path, fade_ms=800):
        pass

    def music_busy(self):
        return True

    def say(self, path, tail=0.0, restore=True):
        t0 = time.time()
        time.sleep(SAY_SECS)
        with self.lock:
            self.lines.append((t0, time.time(), threading.current_thread().name, path))

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
    dj = DJBrain(player=p, library=FakeLib(), seed=1, menu_banter_gap=0.3)

    print("-- menu; wait until a banter line is mid-sentence")
    dj.enter_menu()
    time.sleep(0.8)                      # gap (0.3) elapsed, so we're inside a clip
    print("-- start a course RIGHT NOW, mid-line")
    t_start = time.time()
    dj.start_course("Test Peak")
    time.sleep(4.0)
    dj.stop_all()

    lines = sorted(p.lines)
    banter = [l for l in lines if "generic" not in l[3] and "outro" not in l[3]]
    intros = [l for l in lines if "generic" in l[3]]
    for t0, t1, th, path in lines:
        print(f"   {t0 - t_start:+6.2f}s .. {t1 - t_start:+6.2f}s  {path}")

    fails = []
    interrupted = [l for l in banter if l[1] - l[0] < SAY_SECS * 0.95]
    if interrupted:
        fails.append(f"a lobby line was cut short ({len(interrupted)} of "
                     f"{len(banter)}) — the handover feel is gone")
    if not intros:
        fails.append("the race intro never played")
    else:
        # the intro must begin at or after the in-flight lobby line ended
        last_banter_end = max((l[1] for l in banter), default=0)
        if intros[0][0] < last_banter_end - 0.05:
            fails.append("the race intro started ON TOP of the lobby line")
    # and nothing may talk once the in-flight line is done and the race is on
    if len(banter) > 1 and banter[-1][0] > t_start:
        fails.append("a lobby line STARTED after the race began")

    print()
    if fails:
        for f in fails:
            print("FAIL:", f)
        return 1
    print("clean: the lobby line finished, then the race intro took over.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
