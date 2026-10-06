#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if (( $# > 1 )); then
    echo "Usage: $0 [cmdline_file]" >&2
    exit 1
fi
exec python3 "$SCRIPT_DIR/kiosk_boot_config.py" cmdline "${1:-${CMDLINE_FILE:-/boot/firmware/cmdline.txt}}"
