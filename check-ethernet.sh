#!/bin/bash

INTERFACE="${INTERFACE:-eth0}"
ETHTOOL="/usr/sbin/ethtool"
IP="/usr/sbin/ip"
NMCLI="/usr/bin/nmcli"

DEFAULT_WAIT_SECONDS=30
FALLBACK_WAIT_SECONDS=30

log()
{
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}

interface_exists()
{
    [[ -d "/sys/class/net/${INTERFACE}" ]]
}

link_is_up()
{
    [[ "$(cat "/sys/class/net/${INTERFACE}/carrier" 2>/dev/null)" == "1" ]]
}

has_valid_ipv4()
{
    local address

    address=$(
        "$IP" -4 -o address show dev "$INTERFACE" scope global 2>/dev/null |
        awk '{print $4}' |
        cut -d/ -f1 |
        head -n1
    )

    [[ -n "$address" ]] || return 1

    # Reject unspecified, loopback, and IPv4 link-local addresses.
    case "$address" in
        0.*|127.*|169.254.*)
            return 1
            ;;
    esac

    return 0
}

show_status()
{
    local carrier="down"
    local address="none"
    local speed="unknown"

    if link_is_up; then
        carrier="up"
    fi

    address=$(
        "$IP" -4 -o address show dev "$INTERFACE" scope global 2>/dev/null |
        awk '{print $4}' |
        head -n1
    )
    address="${address:-none}"

    speed=$(cat "/sys/class/net/${INTERFACE}/speed" 2>/dev/null)
    speed="${speed:-unknown}"

    log "Interface=${INTERFACE}, link=${carrier}, speed=${speed} Mb/s, IPv4=${address}"
}

wait_for_connection()
{
    local timeout="$1"
    local elapsed=0

    while (( elapsed < timeout )); do
        if link_is_up && has_valid_ipv4; then
            return 0
        fi

        sleep 1
        ((elapsed++))
    done

    return 1
}

restart_network_connection()
{
    log "Restarting NetworkManager connection for ${INTERFACE}"

    "$NMCLI" --wait 10 device disconnect "$INTERFACE" >/dev/null 2>&1 || true
    sleep 2
    "$NMCLI" --wait 10 device connect "$INTERFACE" >/dev/null 2>&1 || true
}

# Wait for the kernel to create eth0.
for (( attempt=0; attempt<30; attempt++ )); do
    if interface_exists; then
        break
    fi

    sleep 1
done

if ! interface_exists; then
    log "ERROR: Interface ${INTERFACE} does not exist"
    exit 1
fi

log "Trying default Ethernet settings"
if ! "$ETHTOOL" -s "$INTERFACE" autoneg on; then
    log "ERROR: Failed to enable Ethernet auto-negotiation"
    exit 1
fi

restart_network_connection

if wait_for_connection "$DEFAULT_WAIT_SECONDS"; then
    log "Ethernet connection works with default settings"
    show_status
    exit 0
fi

log "No working connection with default settings"
show_status

log "Applying fallback: 10 Mbps, full duplex, auto-negotiation off"

if ! "$ETHTOOL" -s "$INTERFACE" speed 10 duplex full autoneg off; then
    log "ERROR: Failed to apply fallback Ethernet settings"
    exit 1
fi

restart_network_connection

if wait_for_connection "$FALLBACK_WAIT_SECONDS"; then
    log "Ethernet connection works with fallback settings"
    show_status
    exit 0
fi

log "ERROR: Ethernet still has no link or valid IPv4 address"
show_status
exit 1
