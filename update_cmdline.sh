#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if (( $# > 1 )); then
    echo "Usage: $0 [cmdline_file]" >&2
    exit 1
fi
CMDLINE_PATH=${1:-${CMDLINE_FILE:-}}
if [[ -z "$CMDLINE_PATH" ]]; then
    BOOT_DIR=$(python3 "$SCRIPT_DIR/kiosk_platform.py" boot-dir)
    CMDLINE_PATH="$BOOT_DIR/cmdline.txt"
fi
exec python3 "$SCRIPT_DIR/kiosk_boot_config.py" cmdline "$CMDLINE_PATH"
