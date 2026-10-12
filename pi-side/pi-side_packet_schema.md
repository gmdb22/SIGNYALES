# Sensor Packet Schema (Glove → Dongle → Pi)

> **SUPERSEDED.** This document was an early draft (CSV-based, accelerometer-only,
> no integrity checking). The implemented format is binary and is defined in code,
> not markdown, specifically so firmware and Pi-side parsing can never drift apart:
>
> - [`firmware/glove/src/packet.h`](../firmware/glove/src/packet.h) — one glove's
>   sensor packet, sent glove → receiver over ESP-NOW
> - [`firmware/receiver/src/frame.h`](../firmware/receiver/src/frame.h) — the
>   combined bimanual frame, sent receiver → Pi over UART
> - [`pi-side/signyales_hub/serial_link.py`](signyales_hub/serial_link.py) — the
>   Python-side struct definitions that must match the above byte-for-byte
>
> ## What changed from this draft, and why
>
> | | This draft | Implemented |
> |---|---|---|
> | Format | CSV text | Binary struct |
> | IMU data | Accelerometer only (3-axis) | Accelerometer **+ gyroscope** (6-axis) |
> | Integrity | None | Additive checksum per packet |
> | Loss detection | None | Per-glove sequence number |
> | Timestamp | float, seconds since boot | `uint32_t`, milliseconds since boot |
> | Hand ID | `"L"` / `"R"` string | `0` / `1` int |
>
> - **Binary instead of CSV**: fits ESP-NOW's 250-byte payload limit more
>   efficiently and avoids parsing overhead on every packet at 50 Hz.
> - **Added gyroscope data**: several FSL handshapes and movements are
>   distinguished by wrist rotation, which an accelerometer alone cannot
>   capture. This is reflected throughout the feature vector, model input
>   shape, and training pipeline — not just the packet.
> - **Added checksum + sequence number**: lets the receiver detect corrupted
>   or dropped packets and report a real delivery ratio, instead of silently
>   forwarding bad data or having no visibility into wireless link quality
>   during hardware bring-up.
>
> The two open questions in the original draft were confirmed during
> implementation: **5 flex sensors per glove** (one per finger), and an
> **MPU6050** IMU.
>
> This file is kept as a record of the design decision, not as the current
> source of truth — see the linked files above for that.
