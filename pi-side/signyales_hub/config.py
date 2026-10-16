"""
Signyales Pi-Side App — Configuration

Target hardware: Raspberry Pi 5 (4GB), Raspberry Pi OS Bookworm (64-bit).
All tunables live here so nothing downstream needs code changes when a
value shifts during testing (baud rate, window size, thresholds, etc).
"""

from dataclasses import dataclass


@dataclass
class HubConfig:
    # --- Link to the receiver dongle ---
    # Pi 5-specific correction: unlike earlier Pi models, /dev/serial0 on
    # the Pi 5 points to a separate 3-pin debug UART connector, NOT the
    # GPIO14/15 header pins we actually wire the receiver to. Use
    # /dev/ttyAMA0 directly instead. Verify this with a loopback test
    # before trusting it (see docs/testing_handoff/ for the exact steps) —
    # do not assume based on the device file simply existing.
    serial_port: str = "/dev/ttyAMA0"
    serial_baud: int = 460800  # MUST match PI_UART_BAUD in the receiver's config.h

    # --- Feature window fed to the model ---
    # At 50 Hz (matching the glove/receiver sample rate), window_size_samples
    # covers window_size_samples / 50 seconds of motion per inference.
    window_size_samples: int = 50   # 1.0s of context per inference
    # The Pi 5's quad-core Cortex-A76 has comfortable headroom for more
    # frequent inference than a Pi 4 or Pi Zero would — a stride of 5
    # (~10 inferences/sec) is a reasonable starting point. Profile with
    # `tools/benchmark_inference.py` once a real model is in place and
    # tighten or loosen this based on measured latency.
    stride_samples: int = 5

    # --- Feature vector layout ---
    # This order is a CONTRACT with the training pipeline. Changing it
    # here without retraining/re-exporting the model will silently
    # produce garbage predictions.
    # [left_flex(5), right_flex(5), left_accel(3), left_gyro(3),
    #  right_accel(3), right_gyro(3)] = 22 features per timestep
    feature_count: int = 22

    # --- Model artifacts ---
    # A model "directory" is expected to contain three files, all
    # produced together by the training pipeline:
    #   model.tflite   - the quantized/optimized TinyML model
    #   labels.json    - list of gesture labels, index-aligned to model output
    #   scaler.json    - {"mean": [...], "std": [...]} for feature normalization,
    #                    computed on the SAME training data the model was fit on
    model_dir: str = "model"

    # --- Prediction stability ---
    confidence_threshold: float = 0.70
    debounce_required_consecutive: int = 3  # consecutive agreeing inferences
                                             # needed before a gesture is "spoken"

    # --- Labels that mean "no sign" ---
    # A model trained with a rest/idle class (recorded like any other
    # gesture, e.g. collect_gesture.py --label rest) needs somewhere to go
    # when nobody is signing. Labels listed here are never printed or
    # spoken. When one is confirmed by the debouncer (same rules as a real
    # gesture), it re-arms the debouncer, so the same word signed twice
    # with a rest in between is spoken twice. Has no effect if the model's
    # labels.json contains none of these names. Which motions count as
    # rest, and what the label is called, is a data-collection decision
    # (finding F4); keep this list in sync with it.
    silent_labels: tuple = ("rest",)

    # --- Frame freshness (mirrors the receiver's own concept) ---
    # If BOTH hands are marked invalid in an incoming frame, it's treated
    # as "no signal" and does not advance the inference window — this
    # avoids feeding the model long runs of frozen/stale data.
    require_at_least_one_hand_valid: bool = True

    # --- Status LED (optional, Raspberry Pi GPIO via gpiozero) ---
    status_led_enabled: bool = False
    status_led_pin: int = 27  # BCM numbering
