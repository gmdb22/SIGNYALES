# Signyales — Auto-Start on Boot

There are two ways to start Signyales automatically. Use one, not both
(they would fight over the serial port):

| | Plug and play: kiosk at startup | Console service |
|---|---|---|
| What starts | The Signyales app, full screen, straight to recognition (subtitles + speech) | The console app `signyales_hub.main` |
| Needs | The Pi's desktop and a screen | No screen |
| Install | `bash deploy/install_kiosk_autostart.sh` (normal user) | `sudo ./deploy/install_service.sh` |
| Section | Right below | "Console service" further down |

## Plug and play: kiosk at startup

After this, switching the Pi on is enough. Run on the Pi, as your normal
user (not sudo), once the setup is done (`pi-side/venv` exists,
`python3-tk` installed):

```bash
bash ~/SIGNYALES/pi-side/deploy/install_kiosk_autostart.sh
# options go to the app, e.g.  ... install_kiosk_autostart.sh --share
```

It puts `signyales-kiosk.desktop` in `~/.config/autostart`, the standard
desktop autostart folder: current Raspberry Pi OS (Wayland, labwc) runs it at
login, and so do older versions (Wayfire, X11). The entry runs
`deploy/start_kiosk.sh`, which waits a few seconds for the desktop and audio,
then starts `gui/signyales_gui.py --kiosk` and logs to `~/signyales_kiosk.log`.
If the console service is installed, the script disables it (asks for your
password).

Then, once, in `sudo raspi-config`:

1. **System Options → Boot / Auto Login → Desktop Autologin**, so the Pi
   reaches the desktop without a password.
2. **Display Options → Screen Blanking → No**, so the screen stays on.
3. Pick the speaker (right-click the speaker icon in the top bar).
4. Put the trained model (`model.tflite`, `labels.json`, `scaler.json`) in
   `pi-side/model/`. Without one the kiosk still runs and shows glove status.

Try it without rebooting: `~/SIGNYALES/pi-side/deploy/start_kiosk.sh &`.
In the kiosk: Esc = full screen on/off, F2 = full app, Ctrl+Q = quit. To
switch off safely, press the Pi 5's power button once (or `sudo shutdown now`).
Undo: `bash ~/SIGNYALES/pi-side/deploy/uninstall_kiosk_autostart.sh`.

Status: the scripts and the kiosk were tested on a Linux desktop session
with fake glove data (install, autostart command, uninstall, screens of
800 x 480 to 1920 x 1080). Not yet run on the real Pi; desktop autologin and
the timing at boot can only be checked there.

## Console service

Without this, "deployed" means someone has to SSH or plug in a keyboard and
run `python -m signyales_hub.main` by hand every time the Pi powers on.
With this installed, the app starts itself as soon as the Pi finishes
booting — power it on, and it's running, no terminal required.

This uses `systemd`, the standard Linux service manager already built into
Raspberry Pi OS — nothing extra to install beyond what's already on the Pi.

**Note:** this starts the console app (`signyales_hub.main`), not the GUI.
To start the GUI on boot, use the kiosk above instead. If you run the GUI by
hand, stop this service first (`sudo systemctl stop signyales`): both need
the serial port.

## Install

```bash
cd pi-side                         # must run from here
source venv/bin/activate           # make sure the venv already exists
pip install -r requirements.txt    # and is already set up
deactivate                         # the installer itself doesn't need the venv active

chmod +x deploy/install_service.sh
sudo ./deploy/install_service.sh
```

The script detects your username and the repo's actual file path
automatically — nothing to hand-edit. It starts the app with `--model-dir
model`, on the receiver link saved in the GUI (USB by default); if you want different flags,
edit `ExecStart=` in `/etc/systemd/system/signyales.service` afterward and
run `sudo systemctl daemon-reload`.

## ⚠️ The one thing that will confuse you if you don't know it up front

**Once this is installed and enabled, the service claims the serial port on
every boot — including right now, if you start it immediately.** If you
then try to manually run `main.py`, `accuracy_logger.py`, or
`performance_logger.py` yourself in a terminal, you'll get a "port already
in use" error, because the background service already has it open.

**Before any manual testing session, stop the service first:**
```bash
sudo systemctl stop signyales
```
It'll resume auto-starting on the *next* reboot regardless — `stop` only
pauses the current run, it doesn't disable the auto-start behavior. Use
`sudo systemctl disable signyales` if you want it to stay off until you
explicitly re-enable it.

## Checking on it

```bash
sudo systemctl status signyales     # is it running right now?
journalctl -u signyales -f          # watch its live output (same as -v logging)
```

## Uninstall

```bash
sudo ./deploy/uninstall_service.sh
```

## Why `multi-user.target` and not something network-related

This app makes no network calls at all — inference and text-to-speech are
both fully offline. Tying it to a network-ready target would just make
boot slower for no benefit, waiting on a network connection the app will
never use.
