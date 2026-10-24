/*
  Signyales — Native Logic Test for frame.h (no ESP32 toolchain, no hardware)
  ==============================================================================
  Same idea as test_packet_logic.cpp, but for the receiver's combined_frame_t
  and compute_frame_checksum(). Must be compiled as C++ (g++), matching how
  the real Arduino/ESP32 toolchain compiles .ino files — see the note in
  test_packet_logic.cpp about why a plain C compiler fails on inline linkage.

  Build and run (from this directory):
      g++ -I../../receiver/src -o test_frame_logic test_frame_logic.cpp && ./test_frame_logic
*/

#include <stdio.h>
#include <string.h>
#include "frame.h"

static int failures = 0;

#define CHECK(label, cond) do { \
    if (cond) { printf("PASS - %s\n", label); } \
    else { printf("FAIL - %s\n", label); failures++; } \
} while (0)

static glove_packet_t make_glove_packet(uint8_t id, uint32_t seq) {
    glove_packet_t p;
    memset(&p, 0, sizeof(p));
    p.glove_id = id;
    p.seq = seq;
    p.timestamp_ms = 1000;
    p.flex_raw[0] = 100; p.flex_raw[1] = 200; p.flex_raw[2] = 300;
    p.flex_raw[3] = 400; p.flex_raw[4] = 500; p.flex_raw[5] = 600;
    p.accel[0] = 0.1f; p.accel[1] = 0.2f; p.accel[2] = 9.8f;
    p.gyro[0] = 1.0f; p.gyro[1] = 2.0f; p.gyro[2] = 3.0f;
    p.checksum = compute_checksum(&p);
    return p;
}

int main(void) {
    printf("=== Signyales native frame logic test ===\n\n");

    // Expected size: 4+4+1+1 + 46 + 46 + 1 = 103 bytes (6 flex sensors per glove).
    // This number matters beyond this test: pi-side/signyales_hub/serial_link.py
    // hardcodes the equivalent size via its FRAME_FMT struct string — if this
    // ever drifts, that Python file needs updating in the same commit.
    CHECK("combined_frame_t is exactly 103 bytes (no padding)",
          sizeof(combined_frame_t) == 103);

    combined_frame_t frame;
    memset(&frame, 0, sizeof(frame));
    frame.frame_seq = 42;
    frame.frame_timestamp_ms = 5000;
    frame.left_valid = 1;
    frame.right_valid = 1;
    frame.left = make_glove_packet(GLOVE_ID_LEFT, 10);
    frame.right = make_glove_packet(GLOVE_ID_RIGHT, 10);

    uint8_t checksum = compute_frame_checksum(&frame);
    frame.checksum = checksum;

    CHECK("frame checksum is stable once set",
          compute_frame_checksum(&frame) == checksum);

    combined_frame_t corrupted = frame;
    corrupted.left.flex_raw[0] ^= 0xFF;
    CHECK("frame checksum catches corruption in the LEFT glove's data",
          compute_frame_checksum(&corrupted) != checksum);

    combined_frame_t corrupted2 = frame;
    corrupted2.right.accel[1] += 1.0f;
    CHECK("frame checksum catches corruption in the RIGHT glove's data",
          compute_frame_checksum(&corrupted2) != checksum);

    combined_frame_t staleRight = frame;
    staleRight.right_valid = 0;
    CHECK("frame checksum changes when a validity flag changes",
          compute_frame_checksum(&staleRight) != checksum);

    printf("\n=== %d check(s) failed ===\n", failures);
    return failures == 0 ? 0 : 1;
}
