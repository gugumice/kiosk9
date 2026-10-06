#!/usr/bin/env bash
# Install a source copy on this Pi, without copying a foreign virtual environment.
set -euo pipefail
SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
INSTALL_DIR=/opt/kiosk
if [[ ${1:-} == --check || ${1:-} == --help ]]; then
    exec bash "$SOURCE_DIR/preppi.sh" "$@"
fi
if (( $# )); then
    echo "Usage: $0 [--check|--help]" >&2
    exit 1
fi
if [[ $EUID -ne 0 ]]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
fi
# Validate the target before copying or changing any system settings.
bash "$SOURCE_DIR/preppi.sh" --check
if [[ "$SOURCE_DIR" != "$INSTALL_DIR" ]]; then
    python3 "$SOURCE_DIR/kiosk_install.py" "$SOURCE_DIR" "$INSTALL_DIR"
fi
exec bash "$INSTALL_DIR/preppi.sh"
