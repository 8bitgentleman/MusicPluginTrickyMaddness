#!/usr/bin/env python3
"""Radio Big IPC front-end.

The BepInEx plugin forwards game events here; this server owns the DJBrain and
all the audio. Two transports, same verbs and dispatch:

  * --cmdfile <path>  (what the game uses): tail a shared command file the plugin
    appends to. This exists because under wine (CrossOver) the game's Unity Mono
    never delivered our localhost datagrams to the player — the send succeeded and
    every standalone wine repro worked, but in-game nothing arrived (7 dead socket
    playtests). The filesystem is shared by both wine processes and sidesteps the
    whole wine-networking / Unity-Mono socket layer. It's also debuggable: the
    command file on disk shows exactly what the plugin wrote.
  * default: bind a localhost UDP socket (dev / native use).

One line = one command (newline-terminated, case-insensitive verb):

    HELLO                 ->  hello / heartbeat (no-op)
    PING                  ->  heartbeat (keeps managed grace alive)
    START <level name>    ->  race broadcast (intro -> song)
    FINISH                ->  race finished: outro NOW, then fade
    MENU                  ->  lobby broadcast (menu loops + banter)
    EVENT <combo|knockdown>  ->  ducked reactive DJ line
    SKIP | NEXT           ->  end the current track, play the next
    PAUSE / RESUME        ->  suspend / resume the music bed
    TOGGLE                ->  flip pause state
    QUIT                  ->  stop the music and exit

UDP, not TCP, on purpose: the plugin runs as Windows Mono under wine (CrossOver),
where Mono's Socket send/recv timeouts, Poll waits, and linger are all ignored,
so every connection-oriented design either hung the sender or closed before we
read the line (the "muted but silent" CrossOver bug). UDP has no connect/close/
reply/timeout to depend on — the plugin just fires datagrams. We never reply;
the plugin never reads. Deliberately forgiving: a bad line is logged, never
fatal. Because UDP is connectionless there's no disconnect to detect a quit, so
managed mode leans on a heartbeat (see MANAGED_GRACE_SECONDS).

There's also a THIRD, separate, opposite-direction channel: --statusfile <path>
(optional). Where --cmdfile is game -> Python, this is Python -> game: the
StatusWriter below mirrors DJBrain's live state/track/dj_talking as JSON so the
plugin can poll it for an in-game "now playing" HUD. One-way and read-only from
the game's side — nothing the game writes to that file is ever read back here.
"""
import argparse
import json
import os
import socket
import sys
import threading
import time

# --assets <dir> is folded into the environment BEFORE dj_brain (-> dj_library)
# is imported, because the library resolves its asset paths at import time. The
# plugin passes it both ways; the CLI arg is the reliable one under wine, where an
# inherited env var may not reach the child (the CrossOver "muted but silent"
# bug). setdefault so a real env var, if it did propagate, still wins.
for _i, _a in enumerate(sys.argv):
    if _a == "--assets" and _i + 1 < len(sys.argv):
        os.environ.setdefault("RADIO_BIG_ASSETS", sys.argv[_i + 1])

# Force UTF-8 (with replacement) on our log streams BEFORE anything prints. On
# Windows the console/redirect default is cp1252, which raises UnicodeEncodeError
# the instant a track title or asset path holds a char it can't map (⧸, an em-dash,
# a curly quote) — and that exception crashes the whole player. dj_library logs at
# import time, so this has to run before the DJBrain import below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # already UTF-8, or a stream that can't be reconfigured — fine either way

from dj_brain import DJBrain
# Imported after the --assets/env fold above, for the same reason dj_brain is:
# dj_library resolves its pool paths at IMPORT time, so an earlier import would
# bind them before --assets had a chance to set RADIO_BIG_ASSETS.
from dj_library import Library

# Keep in sync with the plugin's BepInPlugin version in RadioBigPlugin/RadioBig.cs.
# Purely cosmetic now (UDP: we send no reply) — the plugin attr is the version a
# bug reporter's log actually shows. Sync it anyway.
VERSION = "1.5.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 48757  # arbitrary high port; must match the plugin config

# Managed heartbeat window. UDP is connectionless, so there's no dropped socket
# to tell us the game quit. Instead the plugin PINGs every few seconds while it
# runs; if we go this long with NO datagram at all, the game has quit or crashed,
# so we silence the music and exit rather than orphan a player process. Comfortably
# longer than the plugin's KeepAliveMs (5s) so ordinary jitter never trips it.
MANAGED_GRACE_SECONDS = 30.0


def _pid_alive(pid):
    """Is process `pid` still running? The PRIMARY quit signal in managed mode.

    Under wine (CrossOver) Unity never fires OnApplicationQuit, so the plugin
    can't send us a QUIT on game exit — proven in the logs: the game quit, no
    QUIT was ever written, and the player played on until its console window was
    closed by hand. So instead of trusting the game to tell us, we watch its
    process directly and exit the instant it's gone. The plugin passes its own
    PID (--gamepid); we poll it. Same PID namespace on both targets: the player
    is spawned by the game, so on native macOS both are mac processes and under
    wine both live in the same wineserver, so the query resolves either way.

    None => not monitoring (return alive). Windows/wine goes through kernel32
    (os.kill on Windows TERMINATES rather than probes, so it must not be used);
    POSIX uses the signal-0 probe.
    """
    if pid is None:
        return True
    if sys.platform == "win32":
        import ctypes
        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x00000102  # object not signalled => still running
        k = ctypes.windll.kernel32
        h = k.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not h:
            return False  # gone (or already reaped)
        try:
            return k.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
        finally:
            k.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal


class StatusWriter(threading.Thread):
    """Background thread: mirrors DJBrain.get_status() to a JSON file the
    C# plugin polls to drive an in-game "now playing" HUD widget. This is a
    NEW, separate, one-way channel in the opposite direction of --cmdfile
    (Python -> game instead of game -> Python) — reporting only, it never
    reads anything back.

    Entirely optional: only constructed/started when --statusfile is passed.
    Writes atomically (tmp file + os.replace) so a poller reading mid-write
    never sees a half-written/truncated JSON file. Writes on a ~220ms tick
    AND immediately on every DJBrain status transition, via the nudge()
    wired in as DJBrain's status listener (see RadioServer.__init__)."""
    INTERVAL = 0.22

    def __init__(self, dj, path):
        super().__init__(daemon=True, name="RadioBig-StatusWriter")
        self.dj = dj
        self.path = path
        self._stop = threading.Event()
        self._wake = threading.Event()
        # Guards the tmp-write + os.replace critical section. Without this, the
        # background loop's own write and stop()'s synchronous final write (called
        # from a different thread) can both open the SAME "<path>.tmp" at once;
        # whichever renames second finds its tmp file already moved away by the
        # other and os.replace raises FileNotFoundError. Caller ordering (always
        # dj.stop_all() before status_writer.stop()) makes the two writes' CONTENT
        # identical, so this lock only needs to stop them stepping on each other's
        # tmp file, not decide which write "wins".
        self._write_lock = threading.Lock()

    def run(self):
        while True:
            self._write_status()
            if self._stop.is_set():
                return
            self._wake.wait(self.INTERVAL)
            self._wake.clear()

    def nudge(self):
        """Ask for an immediate write instead of waiting out the tick. Passed
        to DJBrain.set_status_listener, so this fires on every state/track/
        dj_talking change (song draws, DJ starting/stopping talking, race
        start/finish, menu entry, stop_all) with no polling delay."""
        self._wake.set()

    def stop(self):
        """Stop the writer and leave the status file showing nothing playing.
        Runs SYNCHRONOUSLY on the calling thread (does not wait for the
        background thread to wake up and do it) — this is called right before
        the server process exits, so the idle snapshot must land on disk
        before that happens rather than depend on the daemon thread getting
        scheduled again first."""
        self._stop.set()
        self._wake.set()
        self._write_json({"state": "idle", "track": None, "dj_talking": False})

    def _write_status(self):
        try:
            status = self.dj.get_status()
        except Exception as e:  # a reporting bug must never take down playback
            print(f"[status] get_status failed: {e}", flush=True)
            return
        self._write_json(status)

    def _write_json(self, status):
        tmp = self.path + ".tmp"
        with self._write_lock:
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(status, f)
                os.replace(tmp, self.path)  # atomic on POSIX and Windows
            except OSError as e:
                print(f"[status] write failed: {e}", flush=True)


class RadioServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, seed=None,
                 managed=False, game_pid=None, sources=None, status_file=None):
        self.host, self.port = host, port
        self.dj = DJBrain(seed=seed, library=Library(sources=sources))
        self.game_pid = game_pid  # watch this; exit when it dies (managed)
        self._lock = threading.Lock()  # serialise command handling
        # Managed = the plugin auto-launched us and owns our lifetime: exit once
        # the game (our one client) disconnects, so we never orphan a silent
        # player process after a quit or crash. Unmanaged (run_radio.sh by hand)
        # keeps serving so the game can reconnect across restarts.
        self.managed = managed
        self._shutdown = threading.Event()

        # Optional reporting side-channel for the in-game "now playing" HUD
        # (--statusfile). Started here, not in serve_forever/serve_file, so the
        # very first write (idle, track=None) lands as soon as the process is up
        # — before the game has sent its first START/MENU — rather than only
        # after the IPC loop begins.
        self.status_writer = None
        if status_file:
            self.status_writer = StatusWriter(self.dj, status_file)
            self.dj.set_status_listener(self.status_writer.nudge)
            self.status_writer.start()

    def serve_forever(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.settimeout(1.0)  # wake periodically to check heartbeat / shutdown
        mode = " (managed)" if self.managed else ""
        print(f"[server] Radio Big listening on {self.host}:{self.port}{mode} [udp]",
              flush=True)
        last_beat = time.time()  # last time we heard ANY datagram
        heard_any = False
        try:
            while not self._shutdown.is_set():
                # Same primary teardown as the file path: exit the moment the game
                # process dies, rather than waiting out the heartbeat grace.
                if self.managed and not _pid_alive(self.game_pid):
                    print("[server] game process gone -> stopping", flush=True)
                    self.dj.stop_all(fade_ms=400)
                    break
                try:
                    data, addr = srv.recvfrom(65535)
                except socket.timeout:
                    # No datagram this tick. In managed mode, a long silence means
                    # the game quit/crashed (UDP has no disconnect to catch), so
                    # stop the music and exit instead of orphaning this process.
                    if (self.managed and heard_any
                            and time.time() - last_beat > MANAGED_GRACE_SECONDS):
                        print("[server] no heartbeat within grace -> stopping",
                              flush=True)
                        self.dj.stop_all(fade_ms=400)
                        break
                    continue
                last_beat = time.time()
                heard_any = True
                # One datagram may carry one line (normal) or a few if the plugin
                # ever coalesces; splitlines handles both and the trailing "\n".
                for raw in data.decode("utf-8", "replace").splitlines():
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        if self._dispatch(line) is False:  # QUIT
                            print("[server] QUIT -> stopping", flush=True)
                            self.dj.stop_all(fade_ms=400)
                            self._shutdown.set()
                            break
                    except Exception as e:  # never let a bad line kill the server
                        print(f"[server] dispatch error ({line!r}): {e}", flush=True)
        except KeyboardInterrupt:
            print("\n[server] shutting down", flush=True)
            self.dj.stop_all(fade_ms=400)
        finally:
            srv.close()
            if self.status_writer:
                self.status_writer.stop()

    def serve_file(self, path):
        # File transport: tail a shared command file the plugin appends verbs to.
        # This is the path the game actually uses under wine (CrossOver), where
        # localhost datagrams from the game's Unity Mono never reached us despite
        # sending cleanly — an unreproducible socket black hole. The filesystem is
        # shared by both wine processes and touches none of that. We re-open and
        # read-from-offset each poll (bulletproof across wine/native vs keeping a
        # handle open past EOF). Same managed-heartbeat teardown as the UDP path:
        # if the file stops growing for the grace window, the game has gone.
        print(f"[server] Radio Big reading commands from {path} (managed={self.managed}) [file]",
              flush=True)
        pos = 0
        last = time.time()
        started = False
        buf = ""
        while not self._shutdown.is_set():
            # Primary managed teardown: the game process is gone. Near-instant and
            # wine-proof (no OnApplicationQuit needed). The file-quiet grace below
            # stays as a backstop for a crash where we somehow keep a live PID.
            if self.managed and not _pid_alive(self.game_pid):
                print("[server] game process gone -> stopping", flush=True)
                self.dj.stop_all(fade_ms=400)
                break
            chunk = ""
            try:
                with open(path, "rb") as f:
                    f.seek(pos)
                    data = f.read()
                    pos = f.tell()
                chunk = data.decode("utf-8", "replace")
            except FileNotFoundError:
                pass  # plugin hasn't created it yet; keep waiting
            if chunk:
                last = time.time()
                started = True
                buf += chunk
                lines = buf.split("\n")
                buf = lines.pop()  # keep any trailing partial line for next read
                for raw in lines:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        if self._dispatch(line) is False:  # QUIT
                            print("[server] QUIT -> stopping", flush=True)
                            self.dj.stop_all(fade_ms=400)
                            self._shutdown.set()
                            break
                    except Exception as e:  # never let a bad line kill the server
                        print(f"[server] dispatch error ({line!r}): {e}", flush=True)
                continue  # drain fully before sleeping
            if (self.managed and started
                    and time.time() - last > MANAGED_GRACE_SECONDS):
                print("[server] no commands within grace -> stopping", flush=True)
                self.dj.stop_all(fade_ms=400)
                break
            time.sleep(0.15)
        if self.status_writer:
            self.status_writer.stop()

    def _dispatch(self, line):
        # Returns False for QUIT (caller shuts down), True otherwise. No reply is
        # sent — the plugin never reads one.
        parts = line.split(None, 1)
        verb = parts[0].upper()
        arg = parts[1].strip() if len(parts) > 1 else ""
        with self._lock:
            if verb in ("HELLO", "PING"):
                return True  # heartbeat only
            if verb == "START":
                self.dj.start_course(arg)
            elif verb == "FINISH":
                self.dj.finish()
            elif verb == "MENU":
                self.dj.enter_menu()
            elif verb == "EVENT":
                self.dj.react(arg.lower())
            elif verb == "SKIP" or verb == "NEXT":
                self.dj.skip()
            elif verb == "PAUSE":
                self.dj.set_paused(True)
            elif verb == "RESUME":
                self.dj.set_paused(False)
            elif verb == "TOGGLE":
                self.dj.toggle_pause()
            elif verb == "QUIT":
                return False
            else:
                print(f"[server] unknown verb {verb}", flush=True)
            return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Radio Big IPC server")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--assets", default=None,
                    help="audio root (dj/ ssx3/ tricky/ sxot/ ssx2012/). Also read "
                         "from "
                         "RADIO_BIG_ASSETS; the CLI arg is preferred under wine, "
                         "where the env var may not reach this child process. "
                         "Consumed at import (see top of file); listed here so "
                         "argparse accepts it.")
    ap.add_argument("--sources", default=None,
                    help="comma-separated soundtracks to play: any of "
                         "ssx3,tricky,sxot,ssx2012. Omitted means all "
                         "installed. Set "
                         "from the plugin's [Sources] config; passed by ARGV "
                         "rather than an env var for the same reason --assets "
                         "is (env does not reliably reach a wine-spawned "
                         "child).")
    ap.add_argument("--managed", action="store_true",
                    help="exit once the game goes quiet — used when the plugin "
                         "auto-launches and owns the player lifetime")
    ap.add_argument("--gamepid", type=int, default=None,
                    help="watch this process id (the game's) and exit the instant "
                         "it dies. The reliable managed-quit signal under wine, "
                         "where the game never delivers an in-app quit event.")
    ap.add_argument("--cmdfile", default=None,
                    help="tail this shared command file instead of binding a UDP "
                         "socket. This is the transport the plugin uses (the socket "
                         "path never delivered under wine); host/port are ignored.")
    ap.add_argument("--statusfile", default=None,
                    help="write live playback status (state/track/dj_talking) as "
                         "JSON to this path, atomically, roughly every 200-250ms "
                         "and on every state change. A separate, opposite-direction "
                         "channel from --cmdfile: this one is Python -> game, for "
                         "an in-game 'now playing' HUD to poll. Optional — omitted "
                         "means no status file is written and behaviour is "
                         "identical to today.")
    args = ap.parse_args(argv)
    sources = None
    if args.sources is not None:
        # An explicit empty string means "all off" -- honour it (the library
        # says so loudly) rather than reading it back as "unset".
        sources = [t.strip() for t in args.sources.split(",") if t.strip()]
    srv = RadioServer(args.host, args.port, args.seed, managed=args.managed,
                      game_pid=args.gamepid, sources=sources,
                      status_file=args.statusfile)
    if args.cmdfile:
        srv.serve_file(args.cmdfile)
    else:
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
