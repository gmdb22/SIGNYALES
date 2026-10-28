/*
  Signyales — Receiver Dongle Firmware (ESP32)
  ===============================================
  Layer 2 of the Signyales pipeline. Receives glove_packet_t from both
  gloves over ESP-NOW, validates each packet's checksum, and every
  FORWARD_INTERVAL_MS assembles whatever the freshest known data from
  each hand is into a combined_frame_t, which it forwards to the
  Raspberry Pi over USB (default) and/or the UART pins.

  This "sample-and-hold" approach — always forwarding on a fixed
  schedule using the latest available data per hand, rather than only
  forwarding when a matched pair happens to arrive together — keeps
  the Pi's input stream at a constant rate even if one glove
  momentarily drops packets, which is what the TinyML model expects.

  Board: ESP32 Dev Module (or ESP32-S3 — same ESP-NOW APIs apply)

  Links to the Pi (see config.h):
  - USB (Serial, 115200 baud): always prints the text [stats] line.
    While the Pi keeps sending 'b' (about once a second), every frame
    is also sent here. The Pi skips the text between frames (it never
    contains the 0xAA sync byte) and reads the [stats] lines too.
  - UART (Serial1, D17/D18, 460800 baud): every frame, always.
*/

#include <WiFi.h>
#include <esp_now.h>

#include "config.h"
#include "packet.h"
#include "frame.h"

// Last known packet per hand, plus when the receiver got it.
glove_packet_t leftPacket, rightPacket;
uint32_t leftReceivedAt = 0, rightReceivedAt = 0;
bool leftEverSeen = false, rightEverSeen = false;

// Per-hand sequence tracking, for drop detection/logging only —
// this does not block frame forwarding, it just informs the stats
// printed to the debug console.
int32_t lastLeftSeq = -1, lastRightSeq = -1;
uint32_t leftDropped = 0, rightDropped = 0;
uint32_t leftCorrupt = 0, rightCorrupt = 0;
uint32_t framesForwarded = 0;

uint32_t frameSeqCounter = 0;

// When the Pi last asked for frames on USB (millis), and whether it ever did.
uint32_t lastUsbRequestMs = 0;
bool usbRequested = false;

bool usbFramesOn() {
  return usbRequested && (millis() - lastUsbRequestMs) < USB_FRAMES_TIMEOUT_MS;
}

// Reads what arrived on USB. 'b' = "send me frames" (the Pi sends it about
// once a second). Anything else is ignored.
void readUsbCommands() {
  while (Serial.available() > 0) {
    int c = Serial.read();
    if (c == 'b') {
      if (!usbFramesOn()) {
        Serial.println("Pi connected on USB: sending frames here too.");
      }
      usbRequested = true;
      lastUsbRequestMs = millis();
    }
  }
}

// ------------------------------------------------------------------
// Packet handling (shared by both ESP-NOW callback signatures below)
// ------------------------------------------------------------------

void handleIncomingPacket(const uint8_t* data, int len) {
  if (len != sizeof(glove_packet_t)) {
    // Wrong size means either corruption or a stray sender — either
    // way, this is not a frame we can trust. Count it against
    // whichever side it claims to be, if that field is even readable.
    return;
  }

  glove_packet_t pkt;
  memcpy(&pkt, data, sizeof(pkt));

  uint8_t expected = compute_checksum(&pkt);
  if (expected != pkt.checksum) {
    if (pkt.glove_id == GLOVE_ID_LEFT) leftCorrupt++;
    else rightCorrupt++;
    return; // drop silently — a corrupted sample is worse than a missing one
  }

  uint32_t now = millis();

  if (pkt.glove_id == GLOVE_ID_LEFT) {
    if (lastLeftSeq >= 0) {
      int32_t gap = (int32_t)(pkt.seq - (uint32_t)lastLeftSeq) - 1;
      if (gap > 0) leftDropped += gap;
    }
    lastLeftSeq = pkt.seq;
    leftPacket = pkt;
    leftReceivedAt = now;
    leftEverSeen = true;
  } else if (pkt.glove_id == GLOVE_ID_RIGHT) {
    if (lastRightSeq >= 0) {
      int32_t gap = (int32_t)(pkt.seq - (uint32_t)lastRightSeq) - 1;
      if (gap > 0) rightDropped += gap;
    }
    lastRightSeq = pkt.seq;
    rightPacket = pkt;
    rightReceivedAt = now;
    rightEverSeen = true;
  }
  // Unknown glove_id values are silently ignored — defensive against
  // a misconfigured third device ever sending to this receiver.
}

// ESP-NOW's receive callback signature differs between Arduino-ESP32
// core 2.x (first argument is a plain MAC address: const uint8_t*) and
// core 3.x (first argument is a const esp_now_recv_info_t*). An earlier
// version of this file tried to detect which one is installed via the
// ESP_ARDUINO_VERSION_MAJOR macro, but that detection is not reliable in
// practice — confirmed by real compile failures even when that macro
// should theoretically have selected the right branch.
//
// The fix: write this against the older (2.x) signature, which only
// needs a plain pointer as its first argument, then explicitly cast it
// to whatever esp_now_recv_cb_t actually is in your installed core when
// registering it below. This works on BOTH core versions because the
// function body never looks at what that first pointer actually points
// to — it's immediately discarded either way — so the two signatures
// are interchangeable in practice despite not being the same type.
void onDataRecv(const uint8_t* mac, const uint8_t* incomingData, int len) {
  (void)mac;
  handleIncomingPacket(incomingData, len);
}

// ------------------------------------------------------------------
// Setup
// ------------------------------------------------------------------

void setup() {
  Serial.begin(USB_BAUD);        // USB: text, plus frames when the Pi asks
  delay(200);

  Serial1.begin(PI_UART_BAUD, SERIAL_8N1, PI_UART_RX_PIN, PI_UART_TX_PIN); // link to Pi

  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);

  Serial.println("Signyales receiver dongle starting...");
  Serial.print("This device's MAC (give this to both gloves as RECEIVER_MAC): ");
  WiFi.mode(WIFI_STA);
  Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK) {
    Serial.println("FATAL: esp_now_init failed. Halting.");
    while (true) delay(1000);
  }
  // The explicit cast is required: esp_now_register_recv_cb() expects a
  // function pointer matching this core's actual esp_now_recv_cb_t type,
  // which may not textually match onDataRecv's declared signature above
  // (see the comment on onDataRecv for why that's safe here anyway).
  esp_now_register_recv_cb((esp_now_recv_cb_t)onDataRecv);

  Serial.println("Frames go to the UART pins always, and to USB while the Pi asks for them.");
  Serial.println("Setup complete. Waiting for gloves...");
}

// ------------------------------------------------------------------
// Frame assembly and forwarding
// ------------------------------------------------------------------

void forwardCombinedFrame() {
  uint32_t now = millis();

  combined_frame_t frame;
  memset(&frame, 0, sizeof(frame));

  frame.frame_seq = frameSeqCounter++;
  frame.frame_timestamp_ms = now;

  frame.left_valid = (leftEverSeen && (now - leftReceivedAt) <= FRESH_WINDOW_MS) ? 1 : 0;
  frame.right_valid = (rightEverSeen && (now - rightReceivedAt) <= FRESH_WINDOW_MS) ? 1 : 0;

  // Always include the last known data for each side, even if stale —
  // the Pi decides what to do with stale data (e.g. hold last gesture,
  // or flag the frame as unreliable), rather than the receiver having
  // to guess on its behalf.
  frame.left = leftPacket;
  frame.right = rightPacket;

  frame.checksum = compute_frame_checksum(&frame);

  uint8_t header[4] = {
    FRAME_SYNC_BYTE_0,
    FRAME_SYNC_BYTE_1,
    (uint8_t)(sizeof(frame) & 0xFF),
    (uint8_t)((sizeof(frame) >> 8) & 0xFF)
  };
  Serial1.write(header, sizeof(header));
  Serial1.write((uint8_t*)&frame, sizeof(frame));
  if (usbFramesOn()) {
    Serial.write(header, sizeof(header));
    Serial.write((uint8_t*)&frame, sizeof(frame));
  }

  framesForwarded++;

  // Status LED: solid on once both gloves have ever been seen and are
  // currently fresh, otherwise off. Gives a no-laptop-needed check
  // during a live demo.
  digitalWrite(STATUS_LED_PIN, (frame.left_valid && frame.right_valid) ? HIGH : LOW);
}

void printDebugStats() {
  // Packet delivery ratio needs a real "expected total" to divide by.
  // lastLeftSeq/lastRightSeq (highest sequence number seen so far) is
  // that total once you add 1 (sequence numbers start at 0) — a raw
  // "seen" boolean can't give you this, which is why it's computed
  // here rather than left for a downstream tool to approximate.
  long leftExpected = (lastLeftSeq >= 0) ? (lastLeftSeq + 1) : 0;
  long rightExpected = (lastRightSeq >= 0) ? (lastRightSeq + 1) : 0;
  float leftRatio = leftExpected > 0
    ? (100.0f * (leftExpected - (long)leftDropped) / leftExpected) : 0.0f;
  float rightRatio = rightExpected > 0
    ? (100.0f * (rightExpected - (long)rightDropped) / rightExpected) : 0.0f;

  Serial.printf(
    "[stats] frames=%lu | left: ratio=%.1f%% dropped=%lu corrupt=%lu | right: ratio=%.1f%% dropped=%lu corrupt=%lu\n",
    (unsigned long)framesForwarded,
    leftRatio, (unsigned long)leftDropped, (unsigned long)leftCorrupt,
    rightRatio, (unsigned long)rightDropped, (unsigned long)rightCorrupt
  );
}

// ------------------------------------------------------------------
// Loop
// ------------------------------------------------------------------

void loop() {
  static uint32_t lastForward = 0;
  static uint32_t lastStats = 0;

  readUsbCommands();

  uint32_t now = millis();

  if (now - lastForward >= FORWARD_INTERVAL_MS) {
    lastForward = now;
    forwardCombinedFrame();
  }

  if (now - lastStats >= DEBUG_STATS_INTERVAL_MS) {
    lastStats = now;
    printDebugStats();
  }
}
