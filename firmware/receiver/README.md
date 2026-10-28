# Signyales — Receiver Dongle Firmware

Layer 2 of the pipeline: gloves → **receiver dongle** → Pi hub → TinyML → TTS.
This board receives both gloves' ESP-NOW packets, checks them, and forwards a
combined bimanual frame to the Raspberry Pi at a fixed 50 Hz rate, over its
USB cable (default since 29 Oct 2026) or the UART pins (option).

## What's in this folder

| File | Purpose |
|---|---|
| `packet.h` | Copied verbatim from the glove firmware. Do not edit independently. |
| `frame.h` | New contract: the combined frame + UART framing sent to the Pi. |
| `config.h` | USB and UART link settings, freshness window, forward rate. |
| `receiver_firmware.ino` | The firmware itself. |

## Build steps

1. Board: **ESP32 Dev Module**. The receiver that was bought is a 30-pin ESP32-WROOM-32 DevKit with
   USB-C; its USB chip looks like a CH340, so Windows may need the CH340 driver to show a COM port.
2. No extra libraries needed beyond what ships with the ESP32 Arduino core.
3. Flash `receiver_firmware.ino`. Open Serial Monitor at 115200 baud — on boot
   it prints its own MAC address. **Copy that into `RECEIVER_MAC` in both
   gloves' `config.h`** before flashing them (see the glove firmware README).
4. Connect it to the Pi. Two ways; the receiver firmware supports both at
   once, and the choice is made on the Pi (GUI Active mode → "Receiver
   link", saved for the kiosk; or `--link usb|uart` on the command line):

   **USB cable (default).** One USB-A to USB-C **data** cable from a Pi USB
   port to the receiver. It powers the receiver and carries the frames. The
   Pi finds the receiver by its CH340 USB chip, so the port name doesn't
   matter, and no raspi-config step or loopback test is needed.
   How it works: the USB port always shows the text output (boot lines and
   `[stats]`, 115200 baud, `USB_BAUD`). The Pi sends the letter `b` about
   once a second; while those keep arriving the receiver also sends every
   frame on USB, and about 3 s after they stop (`USB_FRAMES_TIMEOUT_MS`) it
   goes back to text only. A laptop serial monitor never sends `b`, so on a
   laptop it looks the same as before. The Pi skips the text between frames
   (it never contains the `0xAA` sync byte) and reads the `[stats]` numbers
   from it.

   **UART wires (option).** Wire `PI_UART_TX_PIN` (default GPIO17) and
   `PI_UART_RX_PIN` (default GPIO18) to the Raspberry Pi's UART RX and TX
   pins respectively (cross them: receiver TX → Pi RX, receiver RX → Pi
   TX), plus a shared ground; the USB cable then only gives power. Frames
   are always sent here, whether or not USB is also used.
5. UART option only: on the Pi, enable the hardware UART (`raspi-config` → Interface Options →
   Serial Port → login shell: no, hardware enabled: yes) and open it at
   **460800 baud** to match `PI_UART_BAUD`. **Pi 5-specific:** use
   `/dev/ttyAMA0`, not `/dev/serial0` — on the Pi 5, `/dev/serial0` points
   to a separate debug connector, not these GPIO pins. Verify with a
   loopback test before trusting it; see
   `docs/testing_handoff/Signyales_Hardware_Testing_Handoff.md`, Stage 5,
   for the exact steps.

## How synchronization works

Rather than waiting for a matched left+right pair to arrive together (which
would stall indefinitely if one glove drops a packet), this firmware runs on
a fixed 20ms timer (`FORWARD_INTERVAL_MS`, 50 Hz) and forwards whatever the
freshest known data for each hand is at that moment:

- If a hand's last packet arrived within `FRESH_WINDOW_MS` (30ms default),
  it's marked `*_valid = 1` in the frame.
- If a hand hasn't been heard from recently — glove is off, out of range, or
  dropped a packet — its last known values are still sent, but marked
  `*_valid = 0`, so the Pi can decide how to handle it (hold last gesture,
  flag low confidence, etc.) instead of the link silently going stale.

This keeps the Pi's input stream at a constant rate matching what the
TinyML model was trained on, regardless of radio conditions.

## The frame contract (`frame.h`)

Every frame sent to the Pi is: `0xAA 0x55 <len_lo> <len_hi> <combined_frame_t bytes>`.
The Pi-side reader should scan for the two sync bytes to (re)synchronize if
it ever loses byte alignment, then read the length-prefixed payload and
verify `checksum` before trusting it.

A minimal Python-side reference for parsing this on the Pi (using `pyserial`
and `struct`) — the actual Pi hub application is the next layer to build,
but the unpacking logic will look like this:

```python
import struct

# Mirrors glove_packet_t exactly: <B I I 5H 3f 3f B
GLOVE_FMT = "<BII5H3f3fB"
GLOVE_SIZE = struct.calcsize(GLOVE_FMT)

# Mirrors combined_frame_t: frame_seq, frame_timestamp_ms, left_valid,
# right_valid, left glove_packet_t, right glove_packet_t, checksum
FRAME_FMT = f"<IIBB{GLOVE_FMT[1:]}{GLOVE_FMT[1:]}B"
```

Getting this struct format string exactly right (byte order, field widths,
no implicit padding) is the single most common integration bug between
firmware and Python — worth writing a one-off test that sends a known frame
and confirms the Pi decodes every field back correctly before building
anything on top of it.

## Debug stats

Once per second, the USB port prints a line like (on the USB link the Pi
reads it too, between frames, and shows it in Active mode, on the laptop
mirror and in the kiosk with F3):

```
[stats] frames=1500 | left: ratio=98.7% dropped=13 corrupt=2 | right: ratio=99.1% dropped=9 corrupt=1
```

`ratio` is the packet delivery ratio computed from the highest sequence
number seen so far minus dropped packets — this is the ESP-NOW-specific,
per-hand figure for the proposal's Technical Performance Checklist.
`pi-side/tools/receiver_link_logger.py` can log it to CSV across a testing
session when the receiver's USB goes to a laptop (UART link to the Pi); on
the USB link, `live_view.py` on the Pi prints the same numbers.

This is a different (lower-level) measurement than the Pi hub's own
packet delivery figures: this counts loss on the glove-to-receiver
ESP-NOW hop specifically, while the Pi-side `performance_logger.py`
reports how often each hand's data was *fresh* by the time a combined
frame reached the Pi — useful for telling apart "the glove dropped a
packet" from "the packet arrived but just missed this frame's window".

## Known limitations

- No retry/ACK logic beyond what ESP-NOW itself provides — a glove whose
  packets are consistently lost will simply show as stale, not reconnect
  automatically. Power-cycling the glove is the current recovery path.
- `left`/`right` in a frame marked invalid still contain the last real
  values received, not zeros — make sure Pi-side code checks `*_valid`
  before using them, rather than assuming zero means "no signal."
