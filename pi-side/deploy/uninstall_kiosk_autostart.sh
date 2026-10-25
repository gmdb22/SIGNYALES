#!/bin/bash
# Signyales — Kiosk Auto-Start Uninstaller
# Removes the desktop autostart entry, so the app no longer opens by itself
# at login. Run as your normal user (not sudo):
#   bash ~/SIGNYALES/pi-side/deploy/uninstall_kiosk_autostart.sh
# It does not change Desktop Autologin or Screen Blanking (sudo raspi-config),
# and does not re-enable the console service (sudo systemctl enable --now signyales).

DESKTOP_FILE="$HOME/.config/autostart/signyales-kiosk.desktop"

if [ -f "$DESKTOP_FILE" ]; then
  rm -f "$DESKTOP_FILE"
  echo "Removed $DESKTOP_FILE. The kiosk won't start at the next login."
else
  echo "Nothing to remove: $DESKTOP_FILE doesn't exist."
fi
pkill -f "gui/signyales_gui.py --kiosk" 2>/dev/null && echo "Closed the running kiosk."
exit 0
