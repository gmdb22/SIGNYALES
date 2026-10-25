#!/bin/bash
# Signyales — kiosk launcher
# ===========================
# Started at desktop login by ~/.config/autostart/signyales-kiosk.desktop
# (created by install_kiosk_autostart.sh). Runs the app full screen in
# kiosk mode and appends its output to ~/signyales_kiosk.log.
# Any options given are passed on (e.g. --share, --no-speech, --port ...).
#
# Can also be run by hand from a terminal on the Pi's desktop:
#   ~/SIGNYALES/pi-side/deploy/start_kiosk.sh

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DEPLOY_DIR/../.." && pwd)"
PYTHON_BIN="$REPO/pi-side/venv/bin/python"
LOG="$HOME/signyales_kiosk.log"

# Give the desktop and the audio system a moment to finish starting.
sleep "${SIGNYALES_KIOSK_DELAY:-4}"

# Keep the log from growing forever: keep one old copy.
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 1000000 ]; then
  mv -f "$LOG" "$LOG.old"
fi
echo "=== $(date) starting Signyales kiosk ===" >> "$LOG"

cd "$REPO" || exit 1
exec "$PYTHON_BIN" "$REPO/gui/signyales_gui.py" --kiosk "$@" >> "$LOG" 2>&1
