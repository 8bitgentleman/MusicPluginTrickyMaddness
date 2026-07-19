#!/bin/sh
# Start the Radio Big companion player. Run this BEFORE (or any time after)
# launching Tricky Madness with the RadioBigTM plugin — the plugin reconnects, so
# order doesn't matter. Ctrl-C to stop. Needs python3 + pygame (`pip3 install pygame`).
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$HERE/radio_server.py" "$@"
