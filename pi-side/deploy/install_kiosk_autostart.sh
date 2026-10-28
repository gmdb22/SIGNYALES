#!/bin/bash
# Signyales — Kiosk Auto-Start Installer (plug and play)
# =======================================================
# After this, switching the Pi on is enough: it logs into the desktop and
# opens the Signyales app full screen, straight to recognition (subtitles +
# speech). It keeps retrying by itself, so the receiver and gloves can be
# switched on in any order.
#
# Run it ON THE PI, as your normal user (NOT with sudo), after the setup
# script (pi-side/venv exists and python3-tk is installed):
#   bash ~/SIGNYALES/pi-side/deploy/install_kiosk_autostart.sh
# Options are passed to the app, for example:
#   bash .../install_kiosk_autostart.sh --share       # also share words with a laptop
#   bash .../install_kiosk_autostart.sh --no-speech   # subtitles only
#
# It uses the standard desktop autostart folder (~/.config/autostart), which
# current Raspberry Pi OS (labwc) and older versions (Wayfire, X11) all read.
# Undo with: bash .../uninstall_kiosk_autostart.sh

set -e

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user, not with sudo:"
  echo "  bash $0"
  exit 1
fi

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DEPLOY_DIR/../.." && pwd)"
PYTHON_BIN="$REPO/pi-side/venv/bin/python"
LAUNCHER="$DEPLOY_DIR/start_kiosk.sh"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP_FILE="$AUTOSTART_DIR/signyales-kiosk.desktop"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "No Python environment at $PYTHON_BIN."
  echo "Run the Pi setup first: bash $REPO/pi-side/deploy/setup_pi.sh (steps in flashing_kit/4_Raspberry_Pi/)."
  exit 1
fi
if ! "$PYTHON_BIN" -c "import tkinter" 2>/dev/null; then
  echo "Tk is missing (the app's windows need it). Install it with:"
  echo "  sudo apt install -y python3-tk"
  exit 1
fi
if [ ! -f "$REPO/gui/kiosk_view.py" ]; then
  echo "This copy of the code has no kiosk mode ($REPO/gui/kiosk_view.py). Update it first:"
  echo "  cd $REPO && git pull"
  exit 1
fi

chmod +x "$LAUNCHER"

# The console auto-start service (install_service.sh) would hold the serial
# port, so the kiosk could never connect. Turn it off if it's installed.
if systemctl list-unit-files signyales.service 2>/dev/null | grep -q '^signyales.service'; then
  echo "The console auto-start service (signyales.service) is installed. It would block"
  echo "the serial port, so it is being stopped and disabled (needs your password):"
  sudo systemctl disable --now signyales.service
  echo "  To use it again later: sudo systemctl enable --now signyales"
fi

# Quote the launcher path for the desktop file; extra options follow it.
EXTRA=""
for arg in "$@"; do
  EXTRA="$EXTRA \"$arg\""
done

mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Signyales
Comment=Signyales FSL translation, kiosk mode (installed by install_kiosk_autostart.sh)
Exec="$LAUNCHER"$EXTRA
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo
echo "Installed: $DESKTOP_FILE"
echo "The app will open full screen in kiosk mode every time you log into the desktop."
echo
echo "Finish the plug-and-play setup (one time, in: sudo raspi-config):"
echo "  1. System Options -> Boot / Auto Login -> Desktop Autologin"
echo "     (so the Pi goes straight to the desktop without a password)"
echo "  2. Display Options -> Screen Blanking -> No"
echo "     (so the screen doesn't turn off while nobody touches it)"
echo "  3. Pick the speaker once: right-click the speaker icon in the top bar."
echo "  4. Put a trained model (model.tflite, labels.json, scaler.json) in:"
echo "     $REPO/pi-side/model"
echo "     Without one, the kiosk still runs and shows the gloves' status."
echo
echo "Try it now without rebooting:  $LAUNCHER &"
echo "In the kiosk: Esc = full screen on/off, F2 = full app, Ctrl+Q = quit."
echo "Log: ~/signyales_kiosk.log    Undo: bash $DEPLOY_DIR/uninstall_kiosk_autostart.sh"
echo "To switch the Pi off safely, press its power button once (or: sudo shutdown now)."
