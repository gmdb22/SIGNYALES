/*
  Signyales — Receiver Dongle Build Configuration
*/

#pragma once

// ---------------------------------------------------------------
// Links to the Raspberry Pi (29 Oct 2026: USB is the default).
//
// USB (default): the receiver's USB cable to a Pi USB port carries
// power AND data. The USB port always shows the human-readable text
// ([stats] every second). Frames are added on it only while the Pi
// keeps asking for them: the Pi sends the letter 'b' about once a
// second; if no 'b' arrives for USB_FRAMES_TIMEOUT_MS, the receiver
// goes back to text only. A laptop serial monitor never sends 'b', so
// on a laptop it looks exactly as before.
//
// UART (option): a separate hardware UART (Serial1) on D17/D18 wired
// to the Pi's GPIO header. Frames are ALWAYS sent here, so the UART
// wiring keeps working with no setting on the receiver; the choice is
// made on the Pi (GUI setting, or config.py).
// ---------------------------------------------------------------
#define USB_BAUD              115200   // must match usb_baud in pi-side config.py
#define USB_FRAMES_TIMEOUT_MS 3000
#define PI_UART_TX_PIN   17
#define PI_UART_RX_PIN   18
#define PI_UART_BAUD     460800   // must match uart_baud in pi-side config.py

// ---------------------------------------------------------------
// A glove packet is considered "fresh" for a given output frame if
// it arrived within this many milliseconds of "now". At 50 Hz
// gloves (20ms period), 30ms tolerates one missed beat's worth of
// jitter without immediately marking that hand stale.
// ---------------------------------------------------------------
#define FRESH_WINDOW_MS    30

// ---------------------------------------------------------------
// How often the receiver assembles and forwards a combined frame to
// the Pi, regardless of whether new glove packets have arrived. This
// keeps the Pi's input stream at a constant, predictable rate — the
// same rate the TinyML model was trained to expect — rather than one
// that speeds up or stalls with the radio link.
// ---------------------------------------------------------------
#define FORWARD_INTERVAL_MS  20   // 50 Hz, matching SAMPLE_RATE_HZ in the glove firmware

// ---------------------------------------------------------------
// Onboard status LED (optional). Solid/blinking patterns are used in
// loop() to give a no-laptop-needed visual for "both gloves linked".
// ---------------------------------------------------------------
#define STATUS_LED_PIN     2

// How often to print link statistics ([stats] line) on USB.
#define DEBUG_STATS_INTERVAL_MS  1000
