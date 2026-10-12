/*
  Signyales — Receiver-to-Pi Frame Definition
  ---------------------------------------------
  This is the second wire-format contract in the pipeline (the first
  is packet.h, between the two gloves and the receiver). This one
  governs the UART link between the receiver dongle and the Raspberry
  Pi hub. Whatever Python parsing code runs on the Pi MUST match this
  struct's field order and size exactly, and must use the same framing
  (sync bytes + length prefix) implemented in receiver_firmware.ino.

  Why a combined frame instead of just relaying two raw glove_packet_t
  in sequence: the Pi's TinyML model expects one bimanual sample per
  time step (both hands' data together), not two independent unimanual
  streams it has to reassemble itself. Doing that reassembly here,
  once, in the receiver, is simpler than making every downstream
  consumer re-implement the same synchronization logic.
*/

#pragma once
#include <stdint.h>
#include "packet.h"

// Framing markers: every frame sent over UART is preceded by these two
// bytes, followed by a 2-byte little-endian length, then the raw
// combined_frame_t bytes. The Pi-side reader should scan for this
// sequence to resynchronize if it ever loses byte alignment.
#define FRAME_SYNC_BYTE_0 0xAA
#define FRAME_SYNC_BYTE_1 0x55

#pragma pack(push, 1)
typedef struct {
  uint32_t frame_seq;          // receiver-assigned, increments once per forwarded frame
  uint32_t frame_timestamp_ms; // millis() on the RECEIVER when this frame was assembled
                                // (not the same clock as either glove's timestamp_ms)
  uint8_t  left_valid;         // 1 if left.* is fresh this frame, 0 if stale/missing
  uint8_t  right_valid;        // 1 if right.* is fresh this frame, 0 if stale/missing
  glove_packet_t left;         // last known left-glove packet (may be stale if left_valid==0)
  glove_packet_t right;        // last known right-glove packet (may be stale if right_valid==0)
  uint8_t  checksum;           // additive checksum over every byte above
} combined_frame_t;
#pragma pack(pop)

inline uint8_t compute_frame_checksum(const combined_frame_t* f) {
  const uint8_t* bytes = (const uint8_t*)f;
  size_t len = sizeof(combined_frame_t) - sizeof(f->checksum);
  uint8_t sum = 0;
  for (size_t i = 0; i < len; i++) sum += bytes[i];
  return sum;
}
