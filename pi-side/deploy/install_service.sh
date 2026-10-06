#!/bin/bash
# Signyales — Auto-Start Service Installer
# ===========================================
# Run this from INSIDE pi-side/, after you've already created the venv and
# installed requirements.txt there. It does not hardcode any paths or
# usernames — everything below is detected from where you actually run it,
# since those differ depending on which user account you set up during
# Raspberry Pi OS imaging and where you cloned the repo.
#
# Usage:
#   cd pi-side
#   chmod +x deploy/install_service.sh
#   sudo ./deploy/install_service.sh

set -e

if [ ! -d "venv" ]; then
  echo "No venv/ found in the current directory."
  echo "Run this from inside pi-side/, after setting up the virtual environment:"
  echo "  python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [ "$EUID" -ne 0 ]; then
  echo "This needs to run with sudo (it writes to /etc/systemd/system/)."
  echo "Try: sudo ./deploy/install_service.sh"
  exit 1
fi

INSTALL_DIR="$(pwd)"
# SUDO_USER is the account that ran `sudo`, not root itself — this is who
# the service will actually run as, so it has normal access to audio and
# serial devices rather than running everything as root unnecessarily.
RUN_USER="${SUDO_USER:-$(whoami)}"
PYTHON_BIN="$INSTALL_DIR/venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Expected a virtual environment's Python at $PYTHON_BIN but didn't find it."
  exit 1
fi

SERVICE_PATH="/etc/systemd/system/signyales.service"

cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=Signyales FSL Translation System
# multi-user.target (not network-online.target) — this app makes no network
# calls at all (offline inference, offline TTS), so there's no reason to
# make boot wait on networking before starting it.
After=multi-user.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON_BIN -m signyales_hub.main --port /dev/serial0 --model-dir model
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable signyales.service

echo ""
echo "Installed and enabled. The app will now start automatically on every boot."
echo ""
echo "Useful commands:"
echo "  sudo systemctl start signyales      # start it right now, without rebooting"
echo "  sudo systemctl status signyales     # check if it's running"
echo "  journalctl -u signyales -f          # follow live logs (Ctrl+C to stop watching)"
echo "  sudo systemctl stop signyales       # stop it (do this before manual testing —"
echo "                                      # otherwise both will fight over the serial port)"
echo "  sudo systemctl disable signyales    # stop it from auto-starting on future boots"
