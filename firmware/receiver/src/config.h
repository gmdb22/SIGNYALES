/*
  Signyales — Receiver Dongle Build Configuration
*/

#pragma once

// ---------------------------------------------------------------
// UART link to the Raspberry Pi. Deliberately a SEPARATE hardware
// UART (Serial1) from the USB debug console (Serial), so plugging
// this board into a laptop for debugging never interferes with the
// live link to the Pi, and vice versa.
// ---------------------------------------------------------------
#define PI_UART_TX_PIN   17
#define PI_UART_RX_PIN   18
#define PI_UART_BAUD     460800   // must match the Pi-side pyserial config exactly

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

// How often to print link statistics to the USB debug console.
#define DEBUG_STATS_INTERVAL_MS  1000
