"""
Signyales Pi Hub — Frame Format Round-Trip Test

Packs a synthetic combined_frame_t using the exact same struct layout
the receiver firmware uses, computes the checksum the same way the
firmware does, and confirms serial_link.parse_frame() decodes it back
correctly.

This exists specifically because struct format mismatches between
firmware and Python are the most common integration bug in this kind
of pipeline (see the receiver firmware README) — run this BEFORE
plugging in real hardware, and again any time packet.h/frame.h change.

Run: python tests/test_frame_roundtrip.py
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signyales_hub.serial_link import GLOVE_FMT, FRAME_SIZE, parse_frame  # noqa: E402


def pack_glove(glove_id, seq, ts, flex, accel, gyro, checksum=0):
    return struct.pack(GLOVE_FMT, glove_id, seq, ts, *flex, *accel, *gyro, checksum)


def build_test_frame():
    left_flex = (100, 200, 300, 400, 500)
    right_flex = (150, 250, 350, 450, 550)
    left_accel = (0.1, 0.2, 9.8)
    left_gyro = (1.0, 2.0, 3.0)
    right_accel = (0.0, 0.1, 9.7)
    right_gyro = (0.5, 1.5, 2.5)

    left = pack_glove(0, 1, 1000, left_flex, left_accel, left_gyro)
    right = pack_glove(1, 1, 1000, right_flex, right_accel, right_gyro)

    header = struct.pack("<IIBB", 42, 5000, 1, 1)  # frame_seq, ts, left_valid, right_valid
    body = header + left + right
    checksum = sum(body) & 0xFF
    payload = body + struct.pack("<B", checksum)

    expected = {
        "frame_seq": 42,
        "frame_timestamp_ms": 5000,
        "left_valid": True,
        "right_valid": True,
        "left_flex": left_flex,
        "right_flex": right_flex,
    }
    return payload, expected


def main():
    payload, expected = build_test_frame()
    assert len(payload) == FRAME_SIZE, (
        f"Packed payload is {len(payload)} bytes but FRAME_SIZE is {FRAME_SIZE} — "
        "the Python struct format has drifted from the C struct layout."
    )

    frame = parse_frame(payload)
    assert frame is not None, "parse_frame rejected a validly-checksummed payload"

    assert frame["frame_seq"] == expected["frame_seq"]
    assert frame["frame_timestamp_ms"] == expected["frame_timestamp_ms"]
    assert frame["left_valid"] == expected["left_valid"]
    assert frame["right_valid"] == expected["right_valid"]
    assert frame["left"]["flex"] == expected["left_flex"]
    assert frame["right"]["flex"] == expected["right_flex"]

    # Corrupt one byte and confirm the checksum check actually catches it.
    corrupted = bytearray(payload)
    corrupted[10] ^= 0xFF
    assert parse_frame(bytes(corrupted)) is None, "Corrupted payload was NOT rejected"

    print("PASS: frame format round-trips correctly and checksum validation works.")


if __name__ == "__main__":
    main()
