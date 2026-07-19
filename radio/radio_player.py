#!/usr/bin/env python3
"""Radio Big companion audio player (Route C).

Unity audio is disabled in Tricky Madness and Wwise can't play our files without
bank authoring (see ssx/MUSIC_MOD_RE.md), so the radio plays OUTSIDE the game
through this process. The BepInEx plugin will drive it over IPC; for now this
module is the audio core plus a standalone ducking demo you can hear with no game
running.

Two live streams, independent volume (that's what buys us ducking):
  * MUSIC  -> pygame.mixer.music (streaming, one track at a time, fade support)
  * VOICE  -> a reserved mixer Channel (the DJ talks OVER the music bed)

Ducking = ramp the music volume down while a voice clip plays, ramp back when it
ends. SSX3 itself mostly talked at full over the bed, but real ducking reads far
more like a radio station, so we do it from the start (user's call).
"""
import os
import sys
import time
import threading
import pygame


class RadioPlayer:
    def __init__(self, music_full=1.0, music_ducked=0.28, duck_ramp=0.35):
        # 44.1k stereo, small buffer for responsive ducking.
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.mixer.set_num_channels(8)
        self._voice_ch = pygame.mixer.Channel(0)   # reserved for the DJ
        self.music_full = music_full
        self.music_ducked = music_ducked
        self.duck_ramp = duck_ramp
        self._music_target = music_full
        pygame.mixer.music.set_volume(music_full)

    # --- music bed -------------------------------------------------------
    def play_music(self, path, fade_ms=800):
        pygame.mixer.music.load(path)
        pygame.mixer.music.play(fade_ms=fade_ms)
        self._ramp_music(self._music_target, 0.05)

    def music_busy(self):
        return pygame.mixer.music.get_busy()

    def _ramp_music(self, target, seconds):
        """Smoothly move the music volume to `target` over `seconds`."""
        start = pygame.mixer.music.get_volume()
        steps = max(1, int(seconds / 0.02))
        for i in range(1, steps + 1):
            v = start + (target - start) * (i / steps)
            pygame.mixer.music.set_volume(v)
            time.sleep(0.02)

    # --- DJ voice, with ducking -----------------------------------------
    def say(self, path, tail=0.25):
        """Duck the bed, play a voice clip to completion, then un-duck.
        `tail` = extra seconds of ducking after the voice ends (breathing room)."""
        snd = pygame.mixer.Sound(path)
        self._ramp_music(self.music_ducked, self.duck_ramp)
        self._voice_ch.play(snd)
        while self._voice_ch.get_busy():
            time.sleep(0.03)
        time.sleep(tail)
        self._music_target = self.music_full
        self._ramp_music(self.music_full, self.duck_ramp)

    def stop(self, fade_ms=600):
        pygame.mixer.music.fadeout(fade_ms)


# --- standalone dogfood demo --------------------------------------------
SSX3 = "/Users/mtvogel/Documents/PythonScripts/youtube-dl/SSX 3 [Soundtrack⧸Gamerip]"
RADIO = "/Users/mtvogel/Downloads/claude_scratch/Radio_Big/Radio_Big_Sections"


def demo():
    """The real feature in miniature: Atomika introduces Placebo, THEN the
    Placebo track plays — with the bed ducking under his voice."""
    song = os.path.join(SSX3, "26 - The Bitter End (Placebo) - SSX 3 [Soundtrack].mp3")
    intro = os.path.join(RADIO, "295_MusicIntroductions_Placebo-riding-with-bros.mp3")
    station = os.path.join(RADIO, "437_RadioBigIntrosWSfx_Youre-listening-to-Radio-Big.mp3")
    for p in (song, intro, station):
        if not os.path.exists(p):
            print(f"MISSING: {p}", file=sys.stderr)
            return 1

    rp = RadioPlayer()
    print("[radio] starting music bed (Placebo - The Bitter End)...")
    rp.play_music(song)
    time.sleep(3)

    print("[radio] station ID (ducked)...")
    rp.say(station)
    time.sleep(1.5)

    print("[radio] artist intro: Placebo (ducked)...")
    rp.say(intro)

    print("[radio] ...music swells back, let it ride a few seconds.")
    time.sleep(6)
    rp.stop()
    while rp.music_busy():
        time.sleep(0.1)
    print("[radio] demo done.")
    return 0


if __name__ == "__main__":
    sys.exit(demo())
