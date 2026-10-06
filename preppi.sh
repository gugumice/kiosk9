#!/bin/bash
# Provision an installed /opt/kiosk copy. Run explicitly as root.
set -euo pipefail
KIOSK_USER=${KIOSK_USER:-${SUDO_USER:-pi}}
[[ "$KIOSK_USER" != root ]] || KIOSK_USER=pi
KIOSK_GROUP="kiosk"
WORK_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${1:-} == --help ]]; then
    echo "Usage: sudo bash install.sh [--check]"
    echo "Targets Raspberry Pi 4/5 with Raspberry Pi OS and the existing DSI touchscreen."
    echo "KIOSK_USER selects an existing account (default: sudo caller, otherwise pi)."
    exit 0
fi
if (( $# > 1 )) || [[ ${1:-} != '' && ${1:-} != --check ]]; then
    echo "Usage: $0 [--check|--help]" >&2
    exit 1
fi
BOARD=$(python3 "$WORK_DIR/kiosk_platform.py" board)
BOOT_DIR=$(python3 "$WORK_DIR/kiosk_platform.py" boot-dir)
USER_DIR=$(getent passwd "$KIOSK_USER" | cut -d: -f6) || {
    echo "Kiosk user does not exist: $KIOSK_USER" >&2; exit 1;
}
[[ -n "$USER_DIR" ]] || { echo "Kiosk user does not exist" >&2; exit 1; }
[[ "$KIOSK_USER" =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || { echo "Unsupported account name" >&2; exit 1; }
command -v raspi-config >/dev/null || { echo "Raspberry Pi OS with raspi-config is required" >&2; exit 1; }
python3 "$WORK_DIR/kiosk_boot_config.py" config "$BOOT_DIR/config.txt" --board "$BOARD" --check
python3 "$WORK_DIR/kiosk_boot_config.py" cmdline "$BOOT_DIR/cmdline.txt" --check
printf 'Raspberry Pi %s; boot files: %s; kiosk user: %s\n' "$BOARD" "$BOOT_DIR" "$KIOSK_USER"
if [[ ${1:-} == --check ]]; then
    exit 0
fi
if [[ $EUID -ne 0 ]]; then
    echo "Please run this script as root (e.g. sudo $0)" >&2
    exit 1
fi
if [[ "$WORK_DIR" != /opt/kiosk ]]; then
    echo "Run install.sh to copy this package into /opt/kiosk first" >&2
    exit 1
fi
getent group "$KIOSK_GROUP" >/dev/null || groupadd --system "$KIOSK_GROUP"
getent group watchdog >/dev/null || groupadd --system watchdog
# Some Pi images do not ship both Bluetooth services.
for unit in bluetooth.service hciuart.service; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
        systemctl disable "$unit"
    fi
done

apt-get update
apt-get install -y python3-tk python3-pil.imagetk python3-pip python3-venv \
    xserver-xorg xserver-xorg-legacy xinit openbox xterm x11-xserver-utils xinput \
    fonts-dejavu fonts-liberation fonts-freefont-ttf fonts-noto-core \
    gcc python3-dev libcups2-dev libjpeg-dev zlib1g-dev \
    cups cups-bsd cups-browsed poppler-utils alsa-utils ethtool cron
# Configure noninteractive X startup after installing Xorg legacy.
cat > /etc/X11/Xwrapper.config <<'EOF'
allowed_users=anybody
needs_root_rights=yes
EOF
usermod -aG "$KIOSK_GROUP",lpadmin,lp,dialout,audio,video,watchdog "$KIOSK_USER"
for group in input render; do
    if getent group "$group" >/dev/null; then
        usermod -aG "$group" "$KIOSK_USER"
    fi
done
"$WORK_DIR/change_cups-browsed.sh"
systemctl restart cups.service cups-browsed.service
"$WORK_DIR/touchpad_rules.sh"
python3 "$WORK_DIR/kiosk_boot_config.py" config "$BOOT_DIR/config.txt" --board "$BOARD"
"$WORK_DIR/update_cmdline.sh" "$BOOT_DIR/cmdline.txt"
printf 'KERNEL=="watchdog", MODE="0660", OWNER="%s", GROUP="watchdog"\n' "$KIOSK_USER" \
    > /etc/udev/rules.d/60-watchdog.rules
udevadm control --reload-rules

# Rebuild even for an in-place copy: old pycups/Pillow binaries may belong to
# another CPU architecture or Python version.
python3 -m venv --clear --system-site-packages "$WORK_DIR/.venv"
"$WORK_DIR/.venv/bin/python" -m pip --no-input install -r "$WORK_DIR/requirements.txt"
timedatectl set-timezone Europe/Riga
"$WORK_DIR/make_logdirs.sh" "$WORK_DIR/kiosk.log"
"$WORK_DIR/make_logdirs.sh" /var/log/kiosk/kiosk.log
chown "$KIOSK_USER:$KIOSK_GROUP" "$WORK_DIR/kiosk.log" /var/log/kiosk/kiosk.log
ln -sfn -- "$WORK_DIR/kiosk.log" "$USER_DIR/kiosk.log"
for unit in firstboot.service kiosk.service wait-for-ethernet.service; do
    # Copy through a temporary file to avoid preexisting hard-link surprises.
    unit_temp=$(mktemp "/etc/systemd/system/.${unit}.XXXXXX")
    install -m 644 "$WORK_DIR/$unit" "$unit_temp"
    if [[ "$unit" == kiosk.service ]]; then
        sed -i "s/^User=pi$/User=$KIOSK_USER/" "$unit_temp"
    fi
    mv -f -- "$unit_temp" "/etc/systemd/system/$unit"
done
install -m 644 "$WORK_DIR/kiosk-clear-print-jobs.service" /etc/systemd/system/kiosk-clear-print-jobs.service
for unit in cups.service cups.socket cups.path; do
    install -d -m 755 "/etc/systemd/system/${unit}.d"
    install -m 644 "$WORK_DIR/systemd/${unit}.d/kiosk-clear-print-jobs.conf" \
        "/etc/systemd/system/${unit}.d/kiosk-clear-print-jobs.conf"
done
systemctl daemon-reload
systemctl enable firstboot.service wait-for-ethernet.service
printf '%s\n' 'Preparation complete. First-boot configuration will run on the next boot.'
