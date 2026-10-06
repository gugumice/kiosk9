#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
# Reuse the maintained launcher; the former test.py target does not exist.
exec "$SCRIPT_DIR/start_kiosk.sh" "$@"
