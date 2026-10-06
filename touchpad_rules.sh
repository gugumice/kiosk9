#!/usr/bin/env bash

set -euo pipefail

RULES_FILE="/etc/udev/rules.d/99-waveshare-touch.rules"
TEMP_FILE=""

create_temp_rules_file() {
    local tmp;
    tmp="$TEMP_FILE"
    printf "Creating temporary udev rules file...\n"

    {
        #printf "video=DSI-1:800x480M@60,rotate=90\n\n"
        printf "#90°:\n"
        printf '#ENV{ID_INPUT_TOUCHSCREEN}=="1", ENV{LIBINPUT_CALIBRATION_MATRIX}="0 -1 1 1 0 0"\n\n'
        printf "#180°:\n"
        printf '#ENV{ID_INPUT_TOUCHSCREEN}=="1", ENV{LIBINPUT_CALIBRATION_MATRIX}="-1 0 1 0 -1 1"\n\n'
        printf "#270°:\n"
        printf 'ENV{ID_INPUT_TOUCHSCREEN}=="1", ENV{LIBINPUT_CALIBRATION_MATRIX}="0 1 0 -1 0 1"\n'
    } > "$tmp"

    if [[ ! -s "$tmp" ]]; then
        printf "Error: Temporary rules file was not created or is empty.\n" >&2
        return 1
    fi
}

write_rules_file() {
    if [[ "$(id -u)" -ne 0 ]]; then
        printf "Error: Script must be run as root to write to %s\n" "$RULES_FILE" >&2
        return 1
    fi

    if ! install -m 644 "$TEMP_FILE" "$RULES_FILE"; then
        printf "Error: Failed to install udev rules file.\n" >&2
        return 1
    fi
    printf "Successfully wrote udev rules to %s\n" "$RULES_FILE"
}

cleanup_temp_file() {
    if [[ -f "$TEMP_FILE" ]]; then
        rm -f "$TEMP_FILE"
    fi
}

main() {
    if [[ "$EUID" -ne 0 ]]; then
        echo "Error: Script must be run as root" >&2
        return 1
    fi
    TEMP_FILE=$(mktemp) || return 1
    trap cleanup_temp_file EXIT

    create_temp_rules_file || return 1
    write_rules_file || return 1
}

main
