#!/usr/bin/env python3
"""Radio Big IPC front-end.

A tiny localhost socket the BepInEx plugin talks to. The game side stays dumb:
it forwards events, this server owns the DJBrain and all the audio. One line =
one command (newline-terminated, case-insensitive verb):

    HELLO                 ->  OK Radio Big <version>
    PING                  ->  PONG
    START <level name>    ->  race broadcast (intro -> song)
    FINISH                ->  race finished: outro NOW, then fade
    MENU                  ->  lobby broadcast (menu loops + banter)
    EVENT <combo|knockdown>  ->  ducked reactive DJ line
    QUIT                  ->  close this connection

Deliberately single-purpose and forgiving: unknown verbs get `ERR ...` but never
crash the server. A dropped connection (the game quit) stops the music — that's
the one place the socket lifetime maps to the broadcast lifetime.
"""
import argparse
import socket
import sys
import threading

from dj_brain import DJBrain

# Keep in sync with the plugin's BepInPlugin version in RadioBigPlugin/RadioBig.cs.
# Only surfaced in the HELLO reply (which the plugin doesn't currently read), so
# this copy is cosmetic — the plugin attr is the one bug reporters actually see.
VERSION = "1.0.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 48757  # arbitrary high port; must match the plugin config


class RadioServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, seed=None,
                 managed=False):
        self.host, self.port = host, port
        self.dj = DJBrain(seed=seed)
        self._lock = threading.Lock()  # serialise command handling
        # Managed = the plugin auto-launched us and owns our lifetime: exit once
        # the game (our one client) disconnects, so we never orphan a silent
        # player process after a quit or crash. Unmanaged (run_radio.sh by hand)
        # keeps serving so the game can reconnect across restarts.
        self.managed = managed
        self._shutdown = threading.Event()

    def serve_forever(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(1)
        srv.settimeout(1.0)  # wake periodically to check for shutdown
        mode = " (managed)" if self.managed else ""
        print(f"[server] Radio Big listening on {self.host}:{self.port}{mode}",
              flush=True)
        try:
            while not self._shutdown.is_set():
                try:
                    conn, addr = srv.accept()
                except socket.timeout:
                    continue
                print(f"[server] client connected: {addr}", flush=True)
                threading.Thread(target=self._handle, args=(conn,),
                                 daemon=True).start()
        except KeyboardInterrupt:
            print("\n[server] shutting down", flush=True)
            self.dj.stop_all(fade_ms=400)
        finally:
            srv.close()

    def _handle(self, conn):
        # A hard game crash sends an RST, so the read below raises
        # ConnectionResetError rather than returning EOF. Wrap the whole session
        # in try/finally so the radio is silenced on ANY teardown — clean quit,
        # QUIT verb, or crash-RST — instead of the exception skipping stop_all.
        try:
            with conn, conn.makefile("r", encoding="utf-8", newline="\n") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        reply = self._dispatch(line)
                    except Exception as e:  # never let a bad line kill the connection
                        reply = f"ERR {e}"
                    if reply is None:  # QUIT
                        break
                    try:
                        conn.sendall((reply + "\n").encode("utf-8"))
                    except OSError:
                        break
        except OSError as e:  # RST / reset by peer when the game crashes
            print(f"[server] client link lost ({e})", flush=True)
        finally:
            # Connection gone (the game quit / crashed) -> silence the radio too.
            print("[server] client disconnected -> stopping broadcast", flush=True)
            self.dj.stop_all(fade_ms=400)
            if self.managed:  # plugin owns us -> shut down with the game
                print("[server] managed mode -> exiting", flush=True)
                self._shutdown.set()

    def _dispatch(self, line):
        parts = line.split(None, 1)
        verb = parts[0].upper()
        arg = parts[1].strip() if len(parts) > 1 else ""
        with self._lock:
            if verb == "HELLO":
                return f"OK Radio Big {VERSION}"
            if verb == "PING":
                return "PONG"
            if verb == "START":
                self.dj.start_course(arg)
                return f"OK started {arg}"
            if verb == "FINISH":
                self.dj.finish()
                return "OK finish"
            if verb == "MENU":
                self.dj.enter_menu()
                return "OK menu"
            if verb == "EVENT":
                self.dj.react(arg.lower())
                return f"OK event {arg}"
            if verb == "QUIT":
                return None
            return f"ERR unknown verb {verb}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Radio Big IPC server")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--managed", action="store_true",
                    help="exit once the game (client) disconnects — used when "
                         "the plugin auto-launches and owns the player lifetime")
    args = ap.parse_args(argv)
    RadioServer(args.host, args.port, args.seed,
                managed=args.managed).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
