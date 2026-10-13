"""
Signyales Pi-Side App — Model Runtime

Wraps a TensorFlow Lite model for gesture inference. Loading is
defensive by design: this module is expected to run correctly BEFORE
a trained model exists, since the hub application, receiver, and
gloves are built and tested in parallel with the ML training pipeline
(see the Agile Scrum sprint structure in the proposal). When no model
is present, predict() returns (None, 0.0) rather than raising, so the
rest of the pipeline (serial parsing, windowing, TTS wiring) can still
be exercised end to end.

On a Raspberry Pi 5 (4GB), the quad-core Cortex-A76 comfortably runs
full TensorFlow's interpreter even without the separate tflite-runtime
package, which has had inconsistent aarch64/Python 3.11 wheel
availability — see the README for an install recommendation.

Expected model directory contents (all produced together by the
training pipeline — see Jupyter Notebook training scripts):
    model.tflite   - the trained, quantized model
    labels.json    - JSON list of gesture label strings, index-aligned
                     to the model's output classes, e.g. ["kumusta",
                     "salamat", "oo", "hindi", ...]
    scaler.json    - {"mean": [22 floats], "std": [22 floats]}, computed
                     on the SAME training data the model was fit on.
                     Must use the exact feature order in config.py.
"""

import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("signyales.model_runtime")


class GestureClassifier:
    def __init__(self, model_dir: str):
        self.model_dir = Path(model_dir)
        self.available = False
        self.interpreter = None
        self.labels = []
        self.mean = None
        self.std = None
        self.input_details = None
        self.output_details = None

        try:
            self._load()
            self.available = True
            log.info("Model loaded from %s (%d classes)", self.model_dir, len(self.labels))
        except Exception as exc:
            log.warning(
                "No usable model at %s (%s). Running with inference disabled — "
                "the rest of the pipeline will still work, but predict() "
                "always returns (None, 0.0) until a model is placed here.",
                self.model_dir, exc,
            )

    def _load(self):
        Interpreter = self._get_interpreter_class()

        model_path = self.model_dir / "model.tflite"
        labels_path = self.model_dir / "labels.json"
        scaler_path = self.model_dir / "scaler.json"
        for p in (model_path, labels_path, scaler_path):
            if not p.exists():
                raise FileNotFoundError(str(p))

        self.interpreter = Interpreter(model_path=str(model_path))
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        with open(labels_path) as f:
            self.labels = json.load(f)

        with open(scaler_path) as f:
            scaler = json.load(f)
        self.mean = np.array(scaler["mean"], dtype=np.float32)
        self.std = np.array(scaler["std"], dtype=np.float32)
        # Guard against divide-by-zero on any constant feature column.
        self.std[self.std == 0] = 1.0

    @staticmethod
    def _get_interpreter_class():
        """
        Tries three interpreter sources, in order of preference:
          1. tflite-runtime — lightest weight, if a matching wheel exists
          2. ai_edge_litert — Google's newer replacement for tf.lite.Interpreter
          3. full TensorFlow's bundled tf.lite.Interpreter — always available if
             `tensorflow` is installed, but emits a deprecation warning as of
             TF 2.20+ pointing at ai_edge_litert as the eventual replacement.
        On a Pi 5, installing full `tensorflow` (option 3) is still the path of
        least resistance for getting something running (see README), but if
        `ai_edge_litert` is available it's used automatically here instead.
        """
        try:
            from tflite_runtime.interpreter import Interpreter
            return Interpreter
        except ImportError:
            pass
        try:
            from ai_edge_litert.interpreter import Interpreter
            return Interpreter
        except ImportError:
            pass
        from tensorflow.lite.python.interpreter import Interpreter
        return Interpreter

    def predict(self, window: np.ndarray):
        """
        window: np.ndarray of shape (window_size, feature_count),
        oldest sample first (see WindowBuffer.as_array()).

        Returns (label: str | None, confidence: float).
        """
        if not self.available:
            return None, 0.0

        x = (window - self.mean) / self.std

        input_dtype = self.input_details[0]["dtype"]
        if input_dtype in (np.int8, np.uint8):
            # Quantized model: apply the input tensor's quantization
            # params rather than feeding it raw floats.
            scale, zero_point = self.input_details[0]["quantization"]
            info = np.iinfo(input_dtype)
            x = np.clip(np.round(x / scale + zero_point), info.min, info.max).astype(input_dtype)
        else:
            x = x.astype(input_dtype)

        x = np.expand_dims(x, axis=0)  # add batch dimension
        self.interpreter.set_tensor(self.input_details[0]["index"], x)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]["index"])[0]

        if output.dtype in (np.int8, np.uint8):
            # Quantized output: convert back to real-valued probabilities
            # using the output tensor's scale/zero-point. Without this the
            # "confidence" would be a raw integer (e.g. -128..127) and any
            # confidence threshold would be meaningless.
            out_scale, out_zero = self.output_details[0]["quantization"]
            output = (output.astype(np.float32) - out_zero) * out_scale

        idx = int(np.argmax(output))
        confidence = float(output[idx])
        label = self.labels[idx] if idx < len(self.labels) else "UNKNOWN"
        return label, confidence
