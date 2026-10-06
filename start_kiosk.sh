#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-${HOME:?}/.Xauthority}"
# Display extensions depend on the installed X server and connected panel.
xset s off || true
xset s noblank || true
xset -dpms || true
xrandr --output DSI-1 --rotate right || true
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/kiosk_main.py" "$@"
