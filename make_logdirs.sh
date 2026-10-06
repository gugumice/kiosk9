#!/usr/bin/env bash

TARGET_PATH=""
TARGET_DIR=""
TARGET_FILE=""

validate_and_parse_arguments() {
    if [[ $# -ne 1 ]]; then
        printf "Usage: %s <full_path_to_file>\n" "$0" >&2
        return 1
    fi

    TARGET_PATH="$1"

    if [[ "$TARGET_PATH" != /* ]]; then
        printf "Error: Path must be absolute: %s\n" "$TARGET_PATH" >&2
        return 1
    fi

    TARGET_DIR=$(dirname "$TARGET_PATH")
    TARGET_FILE=$(basename "$TARGET_PATH")

    if [[ -z "$TARGET_DIR" || -z "$TARGET_FILE" ]]; then
        printf "Error: Invalid path provided: %s\n" "$TARGET_PATH" >&2
        return 1
    fi
}

create_directory_and_file() {
    if ! mkdir -p -- "$TARGET_DIR"; then
        printf "Error: Failed to create directory: %s\n" "$TARGET_DIR" >&2
        return 1
    fi

    if [[ -e "$TARGET_PATH" && ! -f "$TARGET_PATH" ]]; then
        printf "Error: Not a regular file: %s\n" "$TARGET_PATH" >&2
        return 1
    fi
    if [[ ! -f "$TARGET_PATH" ]]; then
        if ! touch -- "$TARGET_PATH"; then
            printf "Error: Failed to create file: %s\n" "$TARGET_PATH" >&2
            return 1
        fi
    fi
}

main() {
    if ! validate_and_parse_arguments "$@"; then
        return 1
    fi

    if ! create_directory_and_file; then
        return 1
    fi

    printf "File ready at: %s\n" "$TARGET_PATH"
}

main "$@"
