#!/usr/bin/env bash
set -euo pipefail
CONFIG_FILE="${1:-/etc/cups/cups-browsed.conf}"
if (( $# > 1 )) || [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Usage: $0 [existing_cups_browsed_config]" >&2
    exit 1
fi
CONFIG_FILE=$(readlink -f -- "$CONFIG_FILE")
TMP_FILE=$(mktemp "${CONFIG_FILE}.tmp.XXXXXX")
trap 'rm -f -- "$TMP_FILE"' EXIT
# Replace any active setting, or add one if only commented defaults exist.
awk '
    /^[[:space:]]*BrowseRemoteProtocols[[:space:]]+/ {
        if (!found++) print "BrowseRemoteProtocols none"
        next
    }
    {print}
    END {if (!found) print "BrowseRemoteProtocols none"}
' "$CONFIG_FILE" > "$TMP_FILE"
if cmp -s -- "$CONFIG_FILE" "$TMP_FILE"; then
    echo "Already configured: $CONFIG_FILE"
    exit 0
fi
cp -p -- "$CONFIG_FILE" "${CONFIG_FILE}.$(date +%Y%m%d-%H%M%S-%N).bak"
# Preserve metadata and replace atomically on the same filesystem.
chmod --reference="$CONFIG_FILE" "$TMP_FILE"
chown --reference="$CONFIG_FILE" "$TMP_FILE"
mv -f -- "$TMP_FILE" "$CONFIG_FILE"
echo "Configuration updated: $CONFIG_FILE"
