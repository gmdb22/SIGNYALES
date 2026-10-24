/*
  Signyales — Shared Packet Definition
  ------------------------------------
  This header MUST be copied identically into the receiver dongle
  firmware project. If the two sides disagree on this struct's layout,
  ESP-NOW will still deliver bytes, but the receiver will misread them
  (fields shifted, floats interpreted as garbage, etc.) with no error
  raised anywhere in the pipeline. Treat this file as the single
  source of truth for the wire format.

  Field order also matters downstream: whatever order flex_raw/accel/
  gyro appear in here is the order the TinyML model's input vector
  must be trained on. If you change this struct, you must also update
  the Raspberry Pi's parsing code AND retrain/re-export the model with
  matching feature order.
*/

#pragma once
#include <stdint.h>

#define GLOVE_ID_LEFT  0
#define GLOVE_ID_RIGHT 1

// Flex sensors per glove: 5 fingers + 1 palm sensor (October 2026 design).
// Changing this changes the wire format: update the Pi's serial_link.py
// (FLEX_PER_GLOVE) and config.py (feature_count), and retrain the model.
#define FLEX_PER_GLOVE 6

#pragma pack(push, 1)
typedef struct {
  uint8_t  glove_id;         // GLOVE_ID_LEFT or GLOVE_ID_RIGHT
  uint32_t seq;              // increasing sequence number (wraps at UINT32_MAX) — lets the
                             // receiver detect dropped or out-of-order packets
  uint32_t timestamp_ms;     // millis() on the glove at the moment of sampling
  uint16_t flex_raw[FLEX_PER_GLOVE]; // calibrated 0-4095 flex readings, in this fixed order:
                             // [0]=thumb [1]=index [2]=middle [3]=ring [4]=pinky [5]=palm
  float    accel[3];         // ax, ay, az in g
  float    gyro[3];          // gx, gy, gz in deg/s
  uint8_t  checksum;         // simple additive checksum over every byte above
} glove_packet_t;
#pragma pack(pop)

// Additive checksum over all fields except the checksum byte itself.
// Cheap, catches most transmission corruption. Not cryptographic —
// it doesn't need to be for a point-to-point ESP-NOW link.
inline uint8_t compute_checksum(const glove_packet_t* pkt) {
  const uint8_t* bytes = (const uint8_t*)pkt;
  size_t len = sizeof(glove_packet_t) - sizeof(pkt->checksum);
  uint8_t sum = 0;
  for (size_t i = 0; i < len; i++) sum += bytes[i];
  return sum;
}
