#!/bin/bash
# One-time boot configuration. Disable this unit only after successful setup.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
    echo "Run this script as root" >&2
    exit 1
fi
ip_address=$(ip -o -4 addr show dev eth0 scope global | awk 'NR == 1 {split($4, address, "/"); print address[1]}')
if [[ ! "$ip_address" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    echo "No usable eth0 IPv4 address; first-boot setup will retry on the next boot" >&2
    exit 1
fi
hostname_suffix=${BASH_REMATCH[2]}
WORK_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
board=$(python3 "$WORK_DIR/kiosk_platform.py" board)
new_hostname="rapi${board}-kiosk9DSI-${hostname_suffix}"
raspi-config nonint do_expand_rootfs
cp -p /etc/hosts "/etc/hosts.$(date +%Y%m%d-%H%M%S-%N).bak"
hostnamectl set-hostname "$new_hostname" --static
# Replace only the local hostname record; keep aliases and unrelated entries intact.
hosts_temp=$(mktemp)
cron_temp=$(mktemp)
trap 'rm -f -- "$hosts_temp" "$cron_temp"' EXIT
awk -v hostname="$new_hostname" '
    $1 == "127.0.1.1" {print "127.0.1.1\t" hostname; found=1; next}
    {print}
    END {if (!found) print "127.0.1.1\t" hostname}
' /etc/hosts > "$hosts_temp"
cat "$hosts_temp" > /etc/hosts
for entry in '10.100.20.104 laiks.egl.local' '10.100.50.102 cache.egl.local'; do
    read -r address name <<< "$entry"
    if ! awk -v name="$name" '{for (i=2; i<=NF; i++) if ($i == name) found=1} END {exit !found}' /etc/hosts; then
        printf '%s\t%s\n' "$address" "$name" >> /etc/hosts
    fi
done
install -d -m 755 /etc/systemd/timesyncd.conf.d
printf '[Time]\nFallbackNTP=laiks.egl.local\n' > /etc/systemd/timesyncd.conf.d/kiosk.conf
crontab -l > "$cron_temp" 2>/dev/null || true
# Migrate the earlier entry without scheduling two reboots at the same time.
sed -i '\|^02 10 \* \* \* sudo reboot 2>/home/pi/reboot.log$|d' "$cron_temp"
if ! grep -Eq '^[[:space:]]*02[[:space:]]+10[[:space:]]+\*[[:space:]]+\*[[:space:]]+\*[[:space:]]+/sbin/reboot[[:space:]]+# kiosk daily reboot$' "$cron_temp"; then
    printf '\n02 10 * * * /sbin/reboot # kiosk daily reboot\n' >> "$cron_temp"
fi
crontab "$cron_temp"
systemctl enable kiosk.service
systemctl disable firstboot.service
printf '%s\n' 'First-boot setup complete; rebooting.'
/sbin/shutdown -r now
