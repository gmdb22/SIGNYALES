"""
Signyales Pi-Side App — Serial Link

Parses the combined_frame_t stream produced by the receiver dongle
(see receiver_firmware/frame.h). This struct format string is the
Python-side half of that contract — if the C struct changes, this
must change to match, byte for byte.
"""

import re
import struct
import time
import random
import logging

log = logging.getLogger("signyales.serial_link")

# Flex sensors per glove, in packet order. Must equal FLEX_PER_GLOVE in
# firmware packet.h (6 since October 2026: 5 fingers + 1 palm sensor).
FLEX_PER_GLOVE = 6
FLEX_NAMES = ("thumb", "index", "middle", "ring", "pinky", "palm")

# Mirrors glove_packet_t exactly (packet.h):
#   uint8_t  glove_id                  -> B
#   uint32_t seq                       -> I
#   uint32_t timestamp_ms              -> I
#   uint16_t flex_raw[FLEX_PER_GLOVE]  -> 6H
#   float    accel[3]                  -> 3f
#   float    gyro[3]                   -> 3f
#   uint8_t  checksum                  -> B
GLOVE_FMT = f"<BII{FLEX_PER_GLOVE}H3f3fB"
GLOVE_SIZE = struct.calcsize(GLOVE_FMT)        # 46 bytes
GLOVE_FIELDS = 3 + FLEX_PER_GLOVE + 3 + 3 + 1  # values struct.unpack gives per glove

# Mirrors combined_frame_t exactly (frame.h):
#   uint32_t frame_seq            -> I
#   uint32_t frame_timestamp_ms   -> I
#   uint8_t  left_valid           -> B
#   uint8_t  right_valid          -> B
#   glove_packet_t left           -> GLOVE_FMT body
#   glove_packet_t right          -> GLOVE_FMT body
#   uint8_t  checksum             -> B
FRAME_FMT = "<IIBB" + GLOVE_FMT[1:] + GLOVE_FMT[1:] + "B"
FRAME_SIZE = struct.calcsize(FRAME_FMT)        # 103 bytes

SYNC_BYTE_0 = 0xAA
SYNC_BYTE_1 = 0x55

# The receiver's once-a-second text line (receiver_firmware.ino). On the USB
# link it arrives between frames; it never contains SYNC_BYTE_0 (not ASCII),
# so it can't be mistaken for a frame.
STATS_RE = re.compile(
    r"\[stats\] frames=(\d+) \| left: ratio=([\d.]+)% dropped=(\d+) corrupt=(\d+) "
    r"\| right: ratio=([\d.]+)% dropped=(\d+) corrupt=(\d+)"
)


def parse_stats_line(line):
    """The receiver's [stats] line as a dict, or None if it isn't one."""
    m = STATS_RE.search(line)
    if not m:
        return None
    frames, lr, ld, lc, rr, rd, rc = m.groups()
    return {"frames": int(frames),
            "left_ratio": float(lr), "left_dropped": int(ld), "left_corrupt": int(lc),
            "right_ratio": float(rr), "right_dropped": int(rd), "right_corrupt": int(rc)}


def _unpack_glove(fields):
    """fields is the GLOVE_FIELDS-tuple slice belonging to one glove_packet_t."""
    glove_id, seq, ts = fields[0:3]
    flex = tuple(fields[3:3 + FLEX_PER_GLOVE])
    ax, ay, az, gx, gy, gz, checksum = fields[3 + FLEX_PER_GLOVE:]
    return {
        "glove_id": glove_id,
        "seq": seq,
        "timestamp_ms": ts,
        "flex": flex,
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
    #                <GLOVE_FIELDS left>, <GLOVE_FIELDS right>, checksum
    frame_seq, frame_ts, left_valid, right_valid = values[0:4]
    left_fields = values[4:4 + GLOVE_FIELDS]
    right_fields = values[4 + GLOVE_FIELDS:4 + 2 * GLOVE_FIELDS]
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
    Reads frames from the receiver dongle (USB or UART link).
    Iterate over an instance to get parsed frame dicts, one per
    successfully-decoded frame. Resynchronizes automatically if byte
    alignment is ever lost.

    With request_frames=True (the USB link) it sends REQUEST_BYTE to the
    receiver every REQUEST_EVERY_S seconds; the receiver only sends frames
    on USB while these keep arriving, and goes back to text only about 3 s
    after they stop. That also covers the receiver restarting (it starts in
    text-only mode). Text between frames is read too: the latest [stats]
    line is kept in receiver_stats (dict, see parse_stats_line) with the
    time.monotonic() it arrived in receiver_stats_at.
    """

    REQUEST_BYTE = b"b"
    REQUEST_EVERY_S = 1.0
    MAX_TEXT = 512

    # Class-level defaults, so a reader built without __init__ (the tests
    # do this to skip opening a real port) still works.
    request_frames = False
    port = ""
    link = ""
    receiver_stats = None
    receiver_stats_at = None

    def __init__(self, port: str, baud: int, timeout: float = 1.0, request_frames: bool = False,
                 link: str = ""):
        import serial  # pyserial — imported lazily so --simulate mode
                        # doesn't require it to be installed
        ser = serial.Serial()
        ser.port, ser.baudrate, ser.timeout = port, baud, timeout
        if request_frames:
            # Keep the USB chip's DTR/RTS lines released when the port opens:
            # on ESP32 dev boards they drive the reset and boot pins. (On some
            # systems the board still restarts once; the requests recover it.)
            ser.dtr = False
            ser.rts = False
        ser.open()
        self._ser = ser
        self.port, self.link, self.request_frames = port, link, request_frames
        log.info("Opened serial link on %s @ %d baud%s", port, baud,
                 " (asking the receiver for frames on USB)" if request_frames else "")

    def close(self):
        try:
            self._ser.close()
        except Exception:
            pass

    def _take_text(self, text, data):
        """Collects the bytes between frames and reads complete text lines."""
        text.extend(data)
        while True:
            nl = text.find(b"\n")
            if nl == -1:
                break
            line = bytes(text[:nl]).decode("ascii", errors="ignore").strip()
            del text[:nl + 1]
            stats = parse_stats_line(line)
            if stats is not None:
                self.receiver_stats = stats
                self.receiver_stats_at = time.monotonic()
            elif line:
                log.debug("receiver: %s", line)
        if len(text) > self.MAX_TEXT:
            del text[:-self.MAX_TEXT]

    def __iter__(self):
        buf = bytearray()
        text = bytearray()
        last_request = None
        while True:
            if self.request_frames:
                now = time.monotonic()
                if last_request is None or now - last_request >= self.REQUEST_EVERY_S:
                    self._ser.write(self.REQUEST_BYTE)
                    last_request = now
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
                        self._take_text(text, buf[:-1])
                        del buf[:-1]
                    break

                if sync_idx > 0:
                    self._take_text(text, buf[:sync_idx])
                    del buf[:sync_idx]  # drop garbage (or receiver text) before the marker

                if len(buf) < 4:
                    break  # need the 2-byte length field too

                length = buf[2] | (buf[3] << 8)
                if length != FRAME_SIZE:
                    # Not a real frame header (e.g. 0xAA 0x55 appearing inside
                    # payload data or boot noise). Trusting this length would
                    # make the reader wait for up to 64 KB, swallowing every
                    # real frame in the meantime. Skip this marker and rescan.
                    del buf[:2]
                    continue
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
            "flex": tuple(random.randint(0, 4095) for _ in range(FLEX_PER_GLOVE)),
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


def open_receiver(cfg, port=None, baud=None, link=None):
    """
    A SerialFrameReader for the receiver, on the link chosen by
    receiver_link.resolve() (USB by default: found automatically and asked
    for frames; UART: cfg.uart_port).
    """
    from .receiver_link import LINK_USB, resolve
    port, baud, link = resolve(cfg, port=port, baud=baud, link=link)
    return SerialFrameReader(port, baud, request_frames=(link == LINK_USB), link=link)
