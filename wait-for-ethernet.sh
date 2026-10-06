#!/bin/bash

INTERFACE="${INTERFACE:-eth0}"
TOTAL_TIMEOUT="${TOTAL_TIMEOUT:-180}"
if [[ ! "$TOTAL_TIMEOUT" =~ ^[0-9]+$ ]]; then
    echo "Error: TOTAL_TIMEOUT must be a nonnegative integer" >&2
    exit 1
fi
DEADLINE=$((SECONDS + TOTAL_TIMEOUT))
CHECK_INTERVAL=2
DHCP_TIMEOUT=120

log()
{
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}

has_ipv4()
{
    local address
    address=$(get_ipv4)
    case "$address" in
        ""|0.*|127.*|169.254.*) return 1 ;;
    esac
    return 0
}

get_ipv4()
{
    ip -4 -o addr show dev "$INTERFACE" scope global 2>/dev/null |
        awk '{print $4}' |
        cut -d/ -f1 |
        head -n1
}

link_is_up()
{
    [[ "$(cat "/sys/class/net/${INTERFACE}/carrier" 2>/dev/null)" == "1" ]]
}

check_deadline()
{
    if (( SECONDS >= DEADLINE )); then
        log "ERROR: Ethernet unavailable after ${TOTAL_TIMEOUT} seconds"
        exit 1
    fi
}

# Wait for eth0 to be created by the kernel
log "Waiting for ${INTERFACE}..."

while [[ ! -d "/sys/class/net/${INTERFACE}" ]]; do
    check_deadline
    sleep 1
done

log "${INTERFACE} found"

#
# Do NOT change speed, duplex or autonegotiation.
# Leave Ethernet PHY configuration completely automatic.
#

while true; do

    log "Waiting for Ethernet link..."

    # Wait until physical Ethernet link exists
    while ! link_is_up; do
        check_deadline
        sleep "$CHECK_INTERVAL"
    done

    log "Ethernet link is up"
    log "Waiting up to ${DHCP_TIMEOUT} seconds for DHCP address..."

    elapsed=0

    while (( elapsed < DHCP_TIMEOUT )); do
        check_deadline

        if has_ipv4; then
            IP_ADDRESS=$(get_ipv4)

            log "DHCP IPv4 address obtained: ${IP_ADDRESS}"
            log "Ethernet initialization successful"
            exit 0
        fi

        # If cable/link disappears, go back to waiting for link
        if ! link_is_up; then
            log "Ethernet link lost"
            break
        fi

        check_deadline
        sleep "$CHECK_INTERVAL"
        ((elapsed += CHECK_INTERVAL))
    done

    if link_is_up; then
        log "No DHCP address after ${DHCP_TIMEOUT} seconds"
        log "Retrying DHCP..."

        # Ask NetworkManager to retry the connection
        nmcli --wait 10 device disconnect "$INTERFACE" >/dev/null 2>&1 || true
        sleep 2
        nmcli --wait 10 device connect "$INTERFACE" >/dev/null 2>&1 || true
    fi

done
