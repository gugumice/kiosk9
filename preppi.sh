#!/bin/bash
# Prepare this kiosk from any working directory. Run explicitly as root.
set -euo pipefail
KIOSK_USER="pi"
KIOSK_GROUP="kiosk"
WORK_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
USER_DIR=$(getent passwd "$KIOSK_USER" | cut -d: -f6)
if [[ $EUID -ne 0 ]]; then
    echo "Please run this script as root (e.g. sudo $0)" >&2
    exit 1
fi
[[ -n "$USER_DIR" ]] || { echo "Kiosk user does not exist" >&2; exit 1; }
getent group "$KIOSK_GROUP" >/dev/null || groupadd --system "$KIOSK_GROUP"
getent group watchdog >/dev/null || groupadd --system watchdog
# Some Pi images do not ship both Bluetooth services.
for unit in bluetooth.service hciuart.service; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
        systemctl disable "$unit"
    fi
done

apt-get install -y python3-tk python3-pil.imagetk python3-pip python3-venv \
    xserver-xorg xserver-xorg-legacy xinit openbox xterm x11-xserver-utils xinput \
    fonts-dejavu fonts-liberation fonts-freefont-ttf fonts-noto-core \
    gcc python3-dev libcups2-dev cups cups-bsd cups-browsed poppler-utils alsa-utils ethtool
# Configure noninteractive X startup after installing Xorg legacy.
cat > /etc/X11/Xwrapper.config <<'EOF'
allowed_users=anybody
needs_root_rights=yes
EOF
usermod -aG "$KIOSK_GROUP",lpadmin,lp,dialout,audio,video,watchdog "$KIOSK_USER"
"$WORK_DIR/change_cups-browsed.sh"
systemctl restart cups.service cups-browsed.service
"$WORK_DIR/touchpad_rules.sh"
"$WORK_DIR/update_config_txt.sh" /boot/firmware/config.txt
"$WORK_DIR/update_cmdline.sh"
printf 'KERNEL=="watchdog", MODE="0660", OWNER="%s", GROUP="watchdog"\n' "$KIOSK_USER" \
    > /etc/udev/rules.d/60-watchdog.rules
udevadm control --reload-rules

python3 -m venv --system-site-packages "$WORK_DIR/.venv"
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
