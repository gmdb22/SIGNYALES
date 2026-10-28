#!/usr/bin/env bash
# Signyales: Raspberry Pi 5 setup script (prepared 25 Oct 2026, updated 29 Oct 2026)
#
# Does steps A3-A6 of the handoff guide in one go:
#   - updates the Pi and installs git, python3-venv, python3-tk, espeak-ng,
#     and swig + liblgpio-dev (needed to build the lgpio package)
#   - downloads the code to ~/SIGNYALES (branch code-tasks)
#   - makes the Python environment pi-side/venv and installs the packages
#     (falls back to a smaller package list if TensorFlow won't install)
#   - turns on the GPIO serial port (adds dtparam=uart0=on to config.txt)
#   - prints the versions to report
#
# Lives in the repository at pi-side/deploy/setup_pi.sh. Get it onto a new
# Pi (before the code is there) with:
#     curl -fsSL https://raw.githubusercontent.com/gmdb22/SIGNYALES/code-tasks/pi-side/deploy/setup_pi.sh -o ~/setup_pi.sh
# Run it on the Pi, as your normal user (NOT with sudo), from any folder:
#     bash setup_pi.sh
# It asks for your password when it needs sudo. Safe to run again.
# Everything it prints is also saved to ~/signyales_setup_log.txt.
#
# STATUS: the 25 Oct version was run on the project's Pi 5 on 26-27 Oct 2026
# and finished on the third run. Run 2 failed building lgpio ("command 'swig'
# failed"); installing swig and liblgpio-dev by hand fixed it. This version
# installs them itself (29 Oct). This updated version has not been run on a
# fresh Pi yet. If a step fails, the script stops and tells you which one;
# send ~/signyales_setup_log.txt to Claude.

set -euo pipefail

BRANCH="code-tasks"
REPO_URL="https://github.com/gmdb22/SIGNYALES.git"
REPO_DIR="$HOME/SIGNYALES"
CONFIG_TXT="/boot/firmware/config.txt"
LOG="$HOME/signyales_setup_log.txt"

exec > >(tee -a "$LOG") 2>&1
step() { echo; echo "=== $* ==="; }
trap 'echo; echo "STOPPED: the step above failed. Send $LOG to Claude."' ERR

if [ "$(id -u)" -eq 0 ]; then
  echo "Please run this as your normal user, not with sudo:  bash setup_pi.sh"
  exit 1
fi

echo "Signyales Pi setup started $(date)"

step "1/6 Check the internet connection"
if ! ping -c 2 -W 3 raspberrypi.com >/dev/null 2>&1; then
  echo "No internet. Connect Wi-Fi (network icon, top bar) or Ethernet, then run this again."
  exit 1
fi
echo "Internet OK."

step "2/6 Update the Pi and install system packages (several minutes)"
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y git python3-venv python3-tk espeak-ng
# Build tools for the lgpio Python package (gpiozero's backend on the Pi 5).
# Without them pip fails with "command 'swig' failed".
sudo apt install -y swig liblgpio-dev
# Serial port access for this user (usually already set on Raspberry Pi OS).
sudo usermod -aG dialout "$USER"

step "3/6 Get the code ($BRANCH)"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" fetch --tags --force origin
  git -C "$REPO_DIR" checkout "$BRANCH"
  git -C "$REPO_DIR" pull --ff-only origin "$BRANCH"
else
  git clone "$REPO_URL" "$REPO_DIR"
  git -C "$REPO_DIR" checkout "$BRANCH"
fi
echo "Code version: $(git -C "$REPO_DIR" --no-pager log -1 --oneline)"

step "4/6 Python environment and packages (TensorFlow is large: can take 10+ minutes)"
cd "$REPO_DIR/pi-side"
if [ ! -x venv/bin/python ]; then
  python3 -m venv venv
fi
venv/bin/python -m pip install --upgrade pip
if venv/bin/python -m pip install -r requirements.txt; then
  echo "Full package install OK."
else
  echo
  echo "Full install failed (usually TensorFlow). Installing the smaller list instead."
  echo "Without TensorFlow everything works except loading a trained model."
  venv/bin/python -m pip install pyserial numpy pyttsx3 pyfiglet gpiozero lgpio
fi

step "5/6 Turn on the GPIO serial port (UART0 on pins 8 and 10)"
if grep -q '^dtparam=uart0=on' "$CONFIG_TXT"; then
  echo "Already on."
else
  echo 'dtparam=uart0=on' | sudo tee -a "$CONFIG_TXT" >/dev/null
  echo "Added dtparam=uart0=on to $CONFIG_TXT (takes effect after reboot)."
fi

step "6/6 Versions to report"
tr -d '\0' < /proc/device-tree/model; echo
grep PRETTY_NAME /etc/os-release
python3 --version
echo "Code: $(git -C "$REPO_DIR" --no-pager log -1 --oneline)"
git --version
espeak-ng --version | head -n 1
venv/bin/python -c "import serial, numpy; print('pyserial', serial.__version__, '| numpy', numpy.__version__)"
venv/bin/python -c "import tensorflow as tf; print('tensorflow', tf.__version__)" 2>/dev/null \
  || echo "tensorflow: not installed (fine until a trained model exists)"

trap - ERR
echo
echo "DONE. Next:"
echo "  1. Restart the Pi:   sudo reboot"
echo "  2. Then follow flashing_kit/4_Raspberry_Pi/4_Raspberry_Pi_Setup.txt from step 4.4 (software checks)."
echo "Log saved to $LOG"
