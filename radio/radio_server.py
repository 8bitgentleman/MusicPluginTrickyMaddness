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

VERSION = "0.1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 48757  # arbitrary high port; must match the plugin config


class RadioServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, seed=None):
        self.host, self.port = host, port
        self.dj = DJBrain(seed=seed)
        self._lock = threading.Lock()  # serialise command handling

    def serve_forever(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(1)
        print(f"[server] Radio Big listening on {self.host}:{self.port}", flush=True)
        try:
            while True:
                conn, addr = srv.accept()
                print(f"[server] client connected: {addr}", flush=True)
                threading.Thread(target=self._handle, args=(conn,),
                                 daemon=True).start()
        except KeyboardInterrupt:
            print("\n[server] shutting down", flush=True)
            self.dj.stop_course(fade_ms=400)
        finally:
            srv.close()

    def _handle(self, conn):
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
        # Connection gone (the game quit / crashed) -> silence the radio too.
        print("[server] client disconnected -> stopping broadcast", flush=True)
        self.dj.stop_all(fade_ms=400)

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
    args = ap.parse_args(argv)
    RadioServer(args.host, args.port, args.seed).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
