"""
Signyales Pi-Side App — Serial Link

Parses the combined_frame_t stream produced by the receiver dongle
(see receiver_firmware/frame.h). This struct format string is the
Python-side half of that contract — if the C struct changes, this
must change to match, byte for byte.
"""

import struct
import time
import random
import logging

log = logging.getLogger("signyales.serial_link")

# Mirrors glove_packet_t exactly (packet.h):
#   uint8_t  glove_id       -> B
#   uint32_t seq            -> I
#   uint32_t timestamp_ms   -> I
#   uint16_t flex_raw[5]    -> 5H
#   float    accel[3]       -> 3f
#   float    gyro[3]        -> 3f
#   uint8_t  checksum       -> B
GLOVE_FMT = "<BII5H3f3fB"
GLOVE_SIZE = struct.calcsize(GLOVE_FMT)

# Mirrors combined_frame_t exactly (frame.h):
#   uint32_t frame_seq            -> I
#   uint32_t frame_timestamp_ms   -> I
#   uint8_t  left_valid           -> B
#   uint8_t  right_valid          -> B
#   glove_packet_t left           -> GLOVE_FMT body
#   glove_packet_t right          -> GLOVE_FMT body
#   uint8_t  checksum             -> B
FRAME_FMT = "<IIBB" + GLOVE_FMT[1:] + GLOVE_FMT[1:] + "B"
FRAME_SIZE = struct.calcsize(FRAME_FMT)

SYNC_BYTE_0 = 0xAA
SYNC_BYTE_1 = 0x55


def _unpack_glove(fields):
    """fields is the 15-tuple slice belonging to one glove_packet_t."""
    glove_id, seq, ts, f0, f1, f2, f3, f4, ax, ay, az, gx, gy, gz, checksum = fields
    return {
        "glove_id": glove_id,
        "seq": seq,
        "timestamp_ms": ts,
        "flex": (f0, f1, f2, f3, f4),
        "accel": (ax, ay, az),
        "gyro": (gx, gy, gz),
        "checksum": checksum,
    }


def parse_frame(payload: bytes):
    """
    Parses one FRAME_SIZE-byte payload (already stripped of the sync
    bytes and length prefix) into a dict, or returns None if the
    checksum doesn't match.

    Checksum matches the firmware's compute_frame_checksum(): an
    additive sum (mod 256) over every byte except the checksum byte
    itself.
    """
    if len(payload) != FRAME_SIZE:
        log.debug("frame size mismatch: got %d, expected %d", len(payload), FRAME_SIZE)
        return None

    computed = sum(payload[:-1]) & 0xFF
    received = payload[-1]
    if computed != received:
        log.debug("frame checksum mismatch: computed=%d received=%d", computed, received)
        return None

    values = struct.unpack(FRAME_FMT, payload)
    # values layout: frame_seq, frame_timestamp_ms, left_valid, right_valid,
    #                <15 left fields>, <15 right fields>, checksum
    frame_seq, frame_ts, left_valid, right_valid = values[0:4]
    left_fields = values[4:4 + 15]
    right_fields = values[4 + 15:4 + 30]
    checksum = values[-1]

    return {
        "frame_seq": frame_seq,
        "frame_timestamp_ms": frame_ts,
        "left_valid": bool(left_valid),
        "right_valid": bool(right_valid),
        "left": _unpack_glove(left_fields),
        "right": _unpack_glove(right_fields),
        "checksum": checksum,
    }


class SerialFrameReader:
    """
    Reads frames from the real UART link to the receiver dongle.
    Iterate over an instance to get parsed frame dicts, one per
    successfully-decoded frame. Resynchronizes automatically if byte
    alignment is ever lost.
    """

    def __init__(self, port: str, baud: int, timeout: float = 1.0):
        import serial  # pyserial — imported lazily so --simulate mode
                        # doesn't require it to be installed
        self._ser = serial.Serial(port, baud, timeout=timeout)
        log.info("Opened serial link on %s @ %d baud", port, baud)

    def __iter__(self):
        buf = bytearray()
        while True:
            chunk = self._ser.read(max(1, self._ser.in_waiting or 1))
            if not chunk:
                continue  # timeout with no data — just keep waiting
            buf.extend(chunk)

            while True:
                sync_idx = buf.find(bytes([SYNC_BYTE_0, SYNC_BYTE_1]))
                if sync_idx == -1:
                    # No sync marker at all yet — keep at most the last
                    # byte in case it's a split SYNC_BYTE_0.
                    if len(buf) > 1:
                        del buf[:-1]
                    break

                if sync_idx > 0:
                    del buf[:sync_idx]  # drop garbage before the marker

                if len(buf) < 4:
                    break  # need the 2-byte length field too

                length = buf[2] | (buf[3] << 8)
                total_needed = 4 + length
                if len(buf) < total_needed:
                    break  # wait for the rest of this frame to arrive

                payload = bytes(buf[4:total_needed])
                del buf[:total_needed]

                frame = parse_frame(payload)
                if frame is not None:
                    yield frame
                else:
                    log.warning("Dropped a corrupt/misframed payload")


class SimulatedFrameSource:
    """
    Generates synthetic frames at a fixed rate, matching the real
    frame's shape and value ranges, so the rest of the pipeline
    (windowing, inference, debouncing, TTS) can be developed and
    tested before hardware or a trained model exist.

    Not a substitute for real sensor testing — just enough to exercise
    every stage of the code path end to end.
    """

    def __init__(self, rate_hz: int = 50):
        self._period = 1.0 / rate_hz
        self._seq = 0

    def _fake_glove(self, glove_id: int):
        return {
            "glove_id": glove_id,
            "seq": self._seq,
            "timestamp_ms": int(time.time() * 1000) & 0xFFFFFFFF,
            "flex": tuple(random.randint(0, 4095) for _ in range(5)),
            "accel": tuple(random.uniform(-2.0, 2.0) for _ in range(3)),
            "gyro": tuple(random.uniform(-50.0, 50.0) for _ in range(3)),
            "checksum": 0,
        }

    def __iter__(self):
        while True:
            time.sleep(self._period)
            self._seq += 1
            yield {
                "frame_seq": self._seq,
                "frame_timestamp_ms": int(time.time() * 1000) & 0xFFFFFFFF,
                "left_valid": True,
                "right_valid": True,
                "left": self._fake_glove(0),
                "right": self._fake_glove(1),
                "checksum": 0,
            }
