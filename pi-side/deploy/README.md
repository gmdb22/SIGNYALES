# Signyales — Auto-Start on Boot

Without this, "deployed" means someone has to SSH or plug in a keyboard and
run `python -m signyales_hub.main` by hand every time the Pi powers on.
With this installed, the app starts itself as soon as the Pi finishes
booting — power it on, and it's running, no terminal required.

This uses `systemd`, the standard Linux service manager already built into
Raspberry Pi OS — nothing extra to install beyond what's already on the Pi.

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
automatically — nothing to hand-edit. It starts the app with `--port
/dev/serial0 --model-dir model` by default; if you want different flags,
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
