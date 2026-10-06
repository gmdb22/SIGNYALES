#!/bin/bash
# Signyales — Auto-Start Service Uninstaller
# Stops and removes the systemd service entirely. Use this if you want to
# go back to manually running main.py by hand, with no auto-start behavior
# at all — not just temporarily stopping it (for that, use
# `sudo systemctl stop signyales` instead, which survives a reboot).

set -e

if [ "$EUID" -ne 0 ]; then
  echo "This needs to run with sudo."
  echo "Try: sudo ./deploy/uninstall_service.sh"
  exit 1
fi

systemctl stop signyales.service 2>/dev/null || true
systemctl disable signyales.service 2>/dev/null || true
rm -f /etc/systemd/system/signyales.service
systemctl daemon-reload

echo "Removed. The app will no longer start automatically on boot."
