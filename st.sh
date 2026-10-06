#!/bin/sh
set -eu
export XAUTHORITY="${XAUTHORITY:-/home/pi/.Xauthority}"
printf '%s\n' "Launching xinit"
exec /usr/bin/xinit /opt/kiosk/start_kiosk.sh -- :0 -nolisten tcp
