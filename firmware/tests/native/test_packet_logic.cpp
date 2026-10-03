/*
  Signyales — Native Logic Test (no ESP32 toolchain, no hardware)
  ==================================================================
  Compiles and runs the ACTUAL packet.h / frame.h header files — the same
  files the real firmware includes — using your computer's own C compiler,
  not an ESP32 toolchain. This works because compute_checksum() and
  compute_frame_checksum() are pure byte arithmetic with zero dependency
  on Arduino.h, WiFi, or any ESP32-specific API.

  This does NOT prove the firmware runs correctly on real hardware — it
  proves the checksum logic itself is correct, independent of hardware,
  which is one real thing fewer to worry about once you do have hardware.

  Build and run (from this directory):
      gcc -I../../glove/src -o test_packet_logic test_packet_logic.c && ./test_packet_logic

  Expected output: every line starts with PASS, and the program exits 0.
*/

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "packet.h"

static int failures = 0;

#define CHECK(label, cond) do { \
    if (cond) { printf("PASS - %s\n", label); } \
    else { printf("FAIL - %s\n", label); failures++; } \
} while (0)

int main(void) {
    printf("=== Signyales native packet logic test ===\n\n");

    // --- Struct size sanity check ---
    // This is the single most important check here: if packing/padding
    // ever changes (e.g. someone removes #pragma pack), this struct's
    // size would silently grow, and EVERY downstream layer (receiver,
    // Python parser) would start misreading every field after the first
    // one affected. Expected size: 1+4+4+(2*5)+(4*3)+(4*3)+1 = 44 bytes.
    CHECK("glove_packet_t is exactly 44 bytes (no padding)",
          sizeof(glove_packet_t) == 44);

    // --- Checksum correctness ---
    glove_packet_t pkt;
    memset(&pkt, 0, sizeof(pkt));
    pkt.glove_id = GLOVE_ID_LEFT;
    pkt.seq = 12345;
    pkt.timestamp_ms = 987654;
    pkt.flex_raw[0] = 100; pkt.flex_raw[1] = 200; pkt.flex_raw[2] = 300;
    pkt.flex_raw[3] = 400; pkt.flex_raw[4] = 500;
    pkt.accel[0] = 0.1f; pkt.accel[1] = 0.2f; pkt.accel[2] = 9.8f;
    pkt.gyro[0] = 1.0f; pkt.gyro[1] = 2.0f; pkt.gyro[2] = 3.0f;

    uint8_t checksum = compute_checksum(&pkt);
    pkt.checksum = checksum;

    // Recomputing on the now-complete packet (with checksum field set)
    // should still match, since compute_checksum() explicitly excludes
    // the checksum byte itself from the sum.
    CHECK("checksum is stable once set (excludes itself from the sum)",
          compute_checksum(&pkt) == checksum);

    // --- Checksum actually catches corruption ---
    glove_packet_t corrupted = pkt;
    corrupted.flex_raw[2] ^= 0xFF;  // flip bits in one finger's reading
    CHECK("checksum correctly changes when payload is corrupted",
          compute_checksum(&corrupted) != checksum);

    // --- Checksum is deterministic across repeated calls ---
    CHECK("checksum is deterministic (same input -> same output every time)",
          compute_checksum(&pkt) == compute_checksum(&pkt));

    // --- Different packets should (almost always) produce different checksums ---
    glove_packet_t other = pkt;
    other.seq = 99999;
    CHECK("different packet content produces a different checksum",
          compute_checksum(&other) != checksum);

    printf("\n=== %d check(s) failed ===\n", failures);
    return failures == 0 ? 0 : 1;
}
